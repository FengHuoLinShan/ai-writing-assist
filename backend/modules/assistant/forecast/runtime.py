"""Finite saved-content computation over the existing run, gateway and task lease."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from core.config import get_settings
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.agent_runtime import AgentBudgetError, AgentRunBudget
from infrastructure.llm.agent_step_harness import run_managed_structured
from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.workflow_budget import workflow_budget
from infrastructure.tasks.facade import cancel_exact_task, enqueue_operation_task
from modules.assistant.forecast.analysis import (
    INSTRUCTIONS,
    ForecastOutput,
    assessments,
    instructions,
)
from modules.assistant.forecast.context import authorize, materialize
from modules.assistant.forecast.contracts import (
    EvaluateRequest,
    FocusRequest,
    RunSubmission,
    RunView,
    UsageView,
)
from modules.assistant.forecast.deterministic import calculate
from modules.assistant.forecast.policy import effective_policy
from modules.assistant.forecast.registry import (
    CAPABILITIES,
    SEMANTIC,
    defaults,
    require_capabilities,
    require_rollout,
)
from modules.assistant.forecast.service import coverage, explicit_decisions, publish
from modules.assistant.models import AssistantRun
from modules.assistant.proactive import _watch
from modules.evidence.contracts import GroupSource, govern_group_output
from modules.local_agent.facade import local_task_meta, open_task_snapshot_client
from modules.project.facade import (
    build_project_llm_execution_snapshot,
)


def enabled(persona="author"):
    if persona == "rp" and not get_settings().interaction_forecast_enabled:
        raise ValidationError(
            "互动建议尚未开启", code="CAPABILITY_UNAVAILABLE", status_code=503
        )
    if not (
        get_settings().assistant_enabled and get_settings().assistant_forecast_enabled
    ):
        raise ValidationError(
            "前瞻辅助尚未开启", code="CAPABILITY_UNAVAILABLE", status_code=503
        )


async def require_run(db, novel_id, run_id, *, lock=False, persona="author"):
    await authorize(db, novel_id, persona=persona)
    query = select(AssistantRun).where(
        AssistantRun.novel_id == UUID(str(novel_id)), AssistantRun.id == UUID(str(run_id))
    )
    if lock:
        query = query.with_for_update()
    run = await db.scalar(query.execution_options(populate_existing=True))
    if run is None or run.request_json.get("protocol") != "forecast_v1":
        raise NotFoundError("前瞻运行不可访问")
    return run


async def submit(
    db, novel_id, data: EvaluateRequest, *, background=False, persona="author"
):
    enabled(persona)
    ctx = await materialize(db, novel_id, data.context, persona=persona)
    request_hash = content_hash(data.model_dump(mode="json"))
    prior = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.novel_id == UUID(novel_id),
            AssistantRun.operation_id == data.operation_id,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise ConflictError("请求标识已用于不同内容", code="OPERATION_MISMATCH")
        return RunSubmission(
            operation_id=data.operation_id,
            run_id=prior.id,
            replayed=True,
            status=prior.status,
        )
    if not background and data.trigger != "manual":
        raise ValidationError(
            "自动分析只能由已授权的保存事件触发", code="INVALID_TRIGGER", status_code=422
        )
    selected = require_capabilities(
        data.requested_capabilities or defaults(data.context.page, persona=persona),
        persona=persona,
    )
    require_rollout(novel_id, selected)
    if data.context.task_hint == "polish":
        selected = [
            key
            for key in selected
            if key
            not in {
                "writing.next_beat.v1",
                "story.open_question.v1",
                "story.character_response.v1",
                "story.information_window.v1",
                "story.scene_transition.v1",
            }
        ]
    semantic = [key for key in selected if key in SEMANTIC]
    if semantic and not get_settings().assistant_forecast_semantic_enabled:
        raise ValidationError(
            "语义前瞻尚未开启，已有资料仍可查看",
            code="SEMANTIC_UNAVAILABLE",
            status_code=503,
        )
    watch = await _watch(db, novel_id, lock=background)
    if background and (
        watch is None
        or not effective_policy(watch).automatic
        or not get_settings().assistant_forecast_automatic_enabled
    ):
        raise ConflictError("后台计算授权已撤销", code="POLICY_CHANGED")
    snapshot = (
        await build_project_llm_execution_snapshot(db, novel_id, agent_executor=True)
        if semantic
        else None
    )
    choices = await explicit_decisions(db, ctx) if semantic else []
    payload = {
        **data.model_dump(mode="json"),
        "author_decisions": choices,
        "decision_hash": content_hash(choices),
        "protocol": "forecast_v1",
        "selected_capabilities": selected,
        "scope": ctx.scope.model_dump(mode="json"),
        "llm_snapshot": snapshot,
        "chapter_index": ctx.chapter_index,
        "compute_key": content_hash(
            [
                ctx.scope.model_dump(mode="json"),
                selected,
                data.horizon.model_dump(mode="json"),
                content_hash(choices),
            ]
        ),
    }
    run = AssistantRun(
        id=data.operation_id,
        novel_id=UUID(novel_id),
        owner_id=ctx.scope.owner_id,
        operation_id=data.operation_id,
        mode="background" if background else "author",
        request_hash=request_hash,
        request_json=payload,
        budget_json=AgentRunBudget(policy_version="forecast_v1").model_dump(mode="json"),
        checkpoint_json={"phase": "queued"},
    )
    task = await enqueue_operation_task(
        db,
        operation_id=str(data.operation_id),
        task_type="assistant_forecast",
        novel_id=novel_id,
        request_payload=data.model_dump(mode="json"),
        meta={
            "run_id": str(run.id),
            "persona": persona,
            **local_task_meta(snapshot),
            **({"_task_priority": "background"} if background else {}),
        },
    )
    if task.reused:
        previous = await db.scalar(
            select(AssistantRun)
            .where(
                AssistantRun.novel_id == UUID(novel_id),
                AssistantRun.operation_id == data.operation_id,
            )
            .execution_options(populate_existing=True)
        )
        if previous and previous.request_hash == request_hash:
            return RunSubmission(
                operation_id=data.operation_id,
                run_id=previous.id,
                replayed=True,
                status=previous.status,
            )
        raise ConflictError("请求标识已有其他执行记录", code="OPERATION_MISMATCH")
    run.task_id = UUID(task.task_id)
    db.add(run)
    await db.flush()
    return RunSubmission(
        operation_id=data.operation_id, run_id=run.id, replayed=False, status=run.status
    )


async def effective_status(db, run):
    from infrastructure.tasks.facade import list_task_lifecycle_contracts

    if not run.task_id:
        return run.status, None
    life = (
        await list_task_lifecycle_contracts(
            db,
            novel_id=str(run.novel_id),
            task_ids=[str(run.task_id)],
            max_heartbeat_gap=0,
        )
    ).get(str(run.task_id))
    status = (
        life.status
        if life
        and life.status in {"failed", "cancelled"}
        and run.status in {"pending", "running"}
        else run.status
    )
    return status, life


async def view(db, novel_id, run_id, *, persona="author"):
    run = await require_run(db, novel_id, run_id, persona=persona)
    budget = AgentRunBudget.model_validate(run.budget_json)
    can_resume = False
    status, life = await effective_status(db, run)
    if (
        not (run.request_json.get("llm_snapshot") or {}).get("local_agent")
        and status in {"failed", "cancelled"}
        and run.task_id
        and not budget.pending_usage
        and budget.remaining_seconds > 0
    ):
        needed = 1 if run.checkpoint_json.get("proposal") else 2
        if life and "resume" in life.available_actions and budget.requests + needed <= 4:
            try:
                enabled(persona)
                ctx = await materialize(
                    db,
                    novel_id,
                    FocusRequest.model_validate(run.request_json["context"]),
                    persona=persona,
                )
                can_resume = (
                    ctx.scope.model_dump(mode="json") == run.request_json["scope"]
                )
            except DomainError:
                pass
    return RunView(
        can_resume=can_resume,
        run_id=run.id,
        task_id=run.task_id,
        local_agent={
            "kind": run.request_json["llm_snapshot"]["local_agent"]["kind"],
            "approved": bool((run.checkpoint_json or {}).get("local_approved")),
        }
        if (run.request_json.get("llm_snapshot") or {}).get("local_agent")
        else None,
        status=status,
        phase="done"
        if status != run.status
        else (run.checkpoint_json or {}).get("phase", "queued"),
        completion=(run.result_json or {}).get("completion", "not_run"),
        candidate_ids=(run.result_json or {}).get("candidate_ids", []),
        coverage=(run.result_json or {}).get("coverage"),
        usage=UsageView(
            requests=budget.requests,
            input_tokens=budget.prompt_tokens if budget.usage_complete else None,
            output_tokens=budget.completion_tokens if budget.usage_complete else None,
            usage_complete=budget.usage_complete,
        ),
        error_code=(run.result_json or {}).get("error_code"),
    )


async def release_slot(db, novel_id, run_id):
    from modules.assistant.forecast.queue import refresh_due

    watch = await _watch(db, novel_id, lock=True)
    if watch and str(watch.active_run_id) == str(run_id):
        watch.active_run_id = None
        refresh_due(watch)


async def cancel(db, novel_id, run_id, *, persona="author"):
    await authorize(db, novel_id, persona=persona)
    await _watch(db, novel_id, lock=True)
    run = await require_run(db, novel_id, run_id, lock=True, persona=persona)
    if run.status in {"pending", "running"}:
        if run.task_id:
            await cancel_exact_task(
                db,
                task_id=str(run.task_id),
                novel_id=novel_id,
                task_types={"assistant_forecast"},
                transition_reason="forecast_user_stop",
            )
        run.status = "cancelled"
        await release_slot(db, novel_id, run_id)
        await db.flush()
    return await view(db, novel_id, run_id, persona=persona)


async def resume(db, novel_id, run_id, *, persona="author"):
    from infrastructure.tasks.facade import resume_manual_task

    enabled(persona)
    await authorize(db, novel_id, persona=persona)
    watch = await _watch(db, novel_id, lock=True)
    run = await require_run(db, novel_id, run_id, lock=True, persona=persona)
    if (run.request_json.get("llm_snapshot") or {}).get("local_agent"):
        raise ConflictError("本机任务中断后请开始新一轮分析", code="NOT_RESUMABLE")
    run.status, _ = await effective_status(db, run)
    if run.status in {"pending", "running"}:
        return await view(db, novel_id, run_id, persona=persona)
    if run.status not in {"failed", "cancelled"} or not run.task_id:
        raise ConflictError(
            "这一轮不能直接恢复，请重新分析当前资料", code="NOT_RESUMABLE"
        )
    ctx = await materialize(
        db,
        novel_id,
        FocusRequest.model_validate(run.request_json["context"]),
        persona=persona,
    )
    if ctx.scope.model_dump(mode="json") != run.request_json["scope"]:
        raise ConflictError("来源或授权已变化，请重新分析", code="SOURCE_STALE")
    budget = AgentRunBudget.model_validate(run.budget_json)
    needed = 1 if run.checkpoint_json.get("proposal") else 2
    if (
        budget.pending_usage
        or budget.remaining_seconds <= 0
        or budget.requests + needed > 4
    ):
        raise ConflictError(
            "原轮用量未确认或额度不足，请查看记录后明确开始新一轮", code="USAGE_UNKNOWN"
        )
    if run.mode == "background":
        if (
            watch is None
            or not effective_policy(watch).automatic
            or not get_settings().assistant_forecast_automatic_enabled
        ):
            raise ConflictError("原后台授权已关闭", code="POLICY_CHANGED")
        if watch.active_run_id not in {None, run.id}:
            raise ConflictError("另一次后台检查仍在运行", code="ACTIVE_RUN_CONFLICT")
        watch.active_run_id = run.id
    _, life = await effective_status(db, run)
    if life is None or "resume" not in life.available_actions:
        raise ConflictError(
            "原任务没有恢复资格，请重新分析当前资料", code="NOT_RESUMABLE"
        )
    await resume_manual_task(
        db, task_id=str(run.task_id), task_types={"assistant_forecast"}, novel_id=novel_id
    )
    run.status = "pending"
    run.result_json = {**run.result_json, "error_code": None, "completion": "not_run"}
    run.checkpoint_json = {**run.checkpoint_json, "phase": "queued"}
    await db.flush()
    return await view(db, novel_id, run_id, persona=persona)


async def execute(db, task):
    if not getattr(db, "task_checkpoint_enabled", False):
        raise RuntimeError("Forecast execution requires a lease-fenced session")
    novel_id, run_id = str(task.novel_id), str(task.meta["run_id"])
    persona = task.meta.get("persona", "author")
    capability = "interaction.forecast" if persona == "rp" else "assistant.forecast"
    run = await require_run(db, novel_id, run_id, persona=persona)
    payload = dict(run.request_json)
    budget = AgentRunBudget.model_validate(run.budget_json)
    focus = FocusRequest.model_validate(payload["context"])
    selected = payload["selected_capabilities"]

    async def guard(*, phase=None):
        enabled(persona)
        require_rollout(novel_id, selected)
        ctx = await materialize(db, novel_id, focus, persona=persona)
        watch = await _watch(db, novel_id, lock=True)
        current = await require_run(db, novel_id, run_id, lock=True, persona=persona)
        if current.status not in {"pending", "running"} or str(current.task_id) != str(
            task.id
        ):
            raise ConflictError("任务已停止或被替代", code="RUN_SUPERSEDED")
        if ctx.scope.model_dump(mode="json") != payload["scope"]:
            raise ConflictError("保存资料或授权已变化", code="SOURCE_STALE")
        if (
            any(key in SEMANTIC for key in selected)
            and not get_settings().assistant_forecast_semantic_enabled
        ):
            raise ConflictError("语义计算已关闭", code="POLICY_CHANGED")
        if (
            payload.get("decision_hash")
            and any(key in SEMANTIC for key in selected)
            and content_hash(await explicit_decisions(db, ctx))
            != payload["decision_hash"]
        ):
            raise ConflictError(
                "作者处置已经变化，请按当前选择重新分析", code="DECISION_CHANGED"
            )
        if current.mode == "background":
            if (
                watch is None
                or watch.active_run_id != current.id
                or not effective_policy(watch).automatic
                or not get_settings().assistant_forecast_automatic_enabled
            ):
                raise ConflictError("后台授权已撤销", code="POLICY_CHANGED")
        if phase:
            current.checkpoint_json = {**current.checkpoint_json, "phase": phase}
        return current, ctx

    async def checkpoint(values):
        current, _ = await guard()
        current.budget_json = values
        await db.commit()

    try:
        if budget.pending_usage:
            raise ConflictError(
                "上次请求结果或费用尚未确认，请查看记录后决定", code="USAGE_UNKNOWN"
            )
        run, ctx = await guard(phase="materializing")
        run.status = "running"
        prior = await db.scalar(
            select(AssistantRun)
            .where(
                AssistantRun.novel_id == run.novel_id,
                AssistantRun.id != run.id,
                AssistantRun.status == "completed",
                AssistantRun.created_at >= datetime.now(UTC) - timedelta(minutes=5),
                AssistantRun.request_json["compute_key"].as_string()
                == payload["compute_key"],
            )
            .order_by(AssistantRun.created_at.desc())
            .limit(1)
        )
        if prior:
            run.result_json = {**prior.result_json, "cached_from": str(prior.id)}
            run.status = "completed"
            run.checkpoint_json = {**run.checkpoint_json, "phase": "done"}
            await release_slot(db, novel_id, run_id)
            await db.commit()
            return {"run_id": run_id, "cached": True}
        await db.commit()
        calculated, missing = calculate(ctx, selected)
        semantic = [key for key in selected if key in SEMANTIC]
        if semantic and ctx.sources:
            async with open_task_snapshot_client(
                db, task, payload["llm_snapshot"], budget=budget, checkpoint=checkpoint
            ) as client:
                await db.commit()

                async def generate(extra=""):
                    await guard(phase="analyzing")
                    await db.commit()
                    with workflow_budget(budget, checkpoint, future_requests=1):
                        return await run_managed_structured(
                            client,
                            LLMCallRequest(
                                model=client.model_name,
                                messages=[
                                    LLMMessage(role="system", content=INSTRUCTIONS),
                                    LLMMessage(
                                        role="user",
                                        content=json.dumps(
                                            {
                                                "author_decisions": payload.get(
                                                    "author_decisions", []
                                                ),
                                                "intent": focus.explicit_instruction,
                                                "task": focus.task_hint,
                                                "horizon": payload["horizon"],
                                                "analyses": instructions(semantic),
                                                "sources": ctx.sources,
                                                "review_feedback": extra,
                                                ("coverage"): (
                                                    "只核对以上保存资料；未搜索全书"
                                                ),
                                            },
                                            ensure_ascii=False,
                                        ),
                                    ),
                                ],
                            ),
                            ForecastOutput,
                            step_name=f"{capability}.propose",
                            capability_id="assistant.forecast",
                            max_fix_attempts=0,
                            transport_retries=False,
                        )

                output = (
                    ForecastOutput.model_validate(run.checkpoint_json["proposal"])
                    if run.checkpoint_json.get("proposal")
                    else await generate()
                )
                assessments(output, ctx, semantic, {})
                current, _ = await guard(phase="validating")
                current.checkpoint_json = {
                    **current.checkpoint_json,
                    "proposal": output.model_dump(mode="json"),
                }
                await db.commit()

                async def repair(feedback):
                    budget.reserve(future_requests=2)
                    return (await generate(feedback)).model_dump_json()

                with workflow_budget(budget, checkpoint):
                    reviewed = await govern_group_output(
                        client,
                        capability=capability,
                        novel_id=novel_id,
                        group_key=ctx.scope.context_hash,
                        sources=[
                            GroupSource(
                                source_key=ref.evidence_id,
                                source_type=ref.resource_kind,
                                source_id=str(ref.resource_id),
                                content_hash=ref.source_hash,
                                label=ref.label,
                            )
                            for ref in ctx.evidence
                        ],
                        output=output.model_dump_json(),
                        task_instruction=INSTRUCTIONS
                        + json.dumps(
                            {
                                "author_decisions": payload.get("author_decisions", []),
                                "intent": focus.explicit_instruction,
                                "task": focus.task_hint,
                                "horizon": payload["horizon"],
                                "analyses": instructions(semantic),
                            },
                            ensure_ascii=False,
                        ),
                        generator_context=ctx.text,
                        repair=repair,
                    )
                if reviewed["status"] != "passed":
                    raise ConflictError(
                        "本次建议未通过资料与方向复核", code="OUTPUT_REJECTED"
                    )
                output = ForecastOutput.model_validate_json(reviewed["text"])
                calculated += assessments(
                    output,
                    ctx,
                    semantic,
                    {"status": reviewed["status"], "review": reviewed["review"]},
                )
        run, latest = await guard(phase="publishing")
        rows = await publish(db, run, latest, calculated)
        report = coverage(
            {
                "presented": len(rows),
                "merged": len(calculated) - len(rows),
                "not_checked": len(missing),
            },
            omissions=[
                {
                    "code": "source_unavailable",
                    "description": "当前焦点缺少这项检查所需的原领域资料："
                    + CAPABILITIES[key]["title"],
                }
                for key in sorted(missing)
            ],
            semantic="complete_for_declared_plan"
            if semantic and ctx.sources
            else "not_run",
        )
        run.result_json = {
            "completion": "partial" if missing else "complete",
            "candidate_ids": [str(row.id) for row in rows],
            "coverage": report.model_dump(mode="json"),
        }
        run.status = "completed"
        run.checkpoint_json = {"phase": "done"}
        await release_slot(db, novel_id, run_id)
        await db.commit()
        return {"run_id": run_id, "candidate_ids": run.result_json["candidate_ids"]}
    except Exception as error:
        await db.rollback()
        await _watch(db, novel_id, lock=True)
        current = await require_run(db, novel_id, run_id, lock=True, persona=persona)
        if current.status in {"pending", "running"}:
            current.status = (
                "budget_exceeded" if isinstance(error, AgentBudgetError) else "failed"
            )
            current.result_json = {
                "completion": "not_run",
                "error_code": error.code
                if isinstance(error, (ConflictError, ValidationError))
                else "FORECAST_FAILED",
            }
            await release_slot(db, novel_id, run_id)
            await db.commit()
        raise
