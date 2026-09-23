"""One exact choice creates one child run and one original domain action batch."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.collaboration import content_hash
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.forecast.context import authorize
from modules.assistant.forecast.contracts import PreparationReceipt
from modules.assistant.forecast.ranking import declined_direction_ids, hidden_by_decision
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.operations import operation_manifest, prepare_actions
from modules.assistant.schemas import ProposedAction, WorkContext


def actions_for(proposal, ctx, capability):
    if ctx.scope.persona == "rp":
        return [
            {
                "action_id": "interaction.prefill." + direction.direction_id,
                "label": "带入输入框",
                "kind": "inspect",
                "requires_confirmation": False,
                "available": True,
            }
            for direction in proposal.directions
        ]
    result = []
    for direction in proposal.directions:
        if not ctx.excluded_targets and not ctx.focus.context_confirmation_id:
            domain = (
                "evidence"
                if capability == "evidence.next_query.v1"
                else "world"
                if capability == "world.rule_decision.v1"
                and ctx.focus.target
                and ctx.focus.target.resource_kind
                in {"world_bible_draft", "world_bible_page"}
                else None
            )
            if domain:
                result.append(
                    {
                        "action_id": (
                            f"{domain}.prepare_direction.{direction.direction_id}"
                        ),
                        "label": "预览这次资料补查"
                        if domain == "evidence"
                        else "预览把方案记入资料工作稿",
                        "kind": "prepare_domain",
                        "requires_confirmation": True,
                        "available": True,
                    }
                )
        if ctx.focus.draft_id and not ctx.excluded_targets:
            revision = ctx.focus.task_hint in {"polish", "revise"}
            action = "discuss_revision" if revision else "prepare_candidate"
            result.append(
                {
                    "action_id": f"writing.{action}.{direction.direction_id}",
                    "label": f"与伙伴修订：{direction.title}"
                    if revision
                    else f"试写：{direction.title}",
                    "kind": "inspect" if revision else "prepare_domain",
                    "requires_confirmation": not revision,
                    "available": True,
                }
            )
        if capability in {"story.open_question.v1", "story.information_window.v1"}:
            result.append(
                {
                    (
                        "action_id"
                    ): f"story.prepare_information_plan.{direction.direction_id}",
                    "label": f"建立安排：{direction.title}",
                    "kind": "prepare_domain",
                    "requires_confirmation": True,
                    "available": True,
                }
            )
    result.append(
        {
            "action_id": "project.prepare_task",
            "label": "加入稍后处理",
            "kind": "prepare_domain",
            "requires_confirmation": True,
            "available": True,
        }
    )
    return result


async def work_context(db, novel_id, ctx):
    focus = ctx.focus
    selection = {}
    if focus.selected_range:
        from modules.writing.facade import get_draft

        draft = await get_draft(db, novel_id, str(focus.draft_id))
        if draft is None or draft.content_hash != ctx.saved_draft_hash:
            raise ConflictError("所选正文已变化", code="SOURCE_STALE")
        start, end = focus.selected_range.start_offset, focus.selected_range.end_offset
        selection = {
            "selection": draft.content[start:end],
            "selection_start": start,
            "selection_end": end,
        }
    return WorkContext(
        page=focus.page
        if focus.page
        in {
            "today",
            "world",
            "writing",
            "outline",
            "scene",
            "map",
            "rag",
            "project",
            "generate",
        }
        else "today",
        scope="current",
        task_hint=focus.task_hint,
        **selection,
        chapter_index=ctx.chapter_index,
        scene_id=focus.scene_id,
        draft_id=focus.draft_id,
        source_hash=ctx.saved_draft_hash,
        context_confirmation_id=focus.context_confirmation_id,
        context_confirmation_action=focus.context_confirmation_action,
        excluded_targets=[] if focus.context_confirmation_id else ctx.excluded_targets,
    )


async def require_parent(db, novel_id, run):
    from modules.assistant.forecast.service import (
        require_candidate,
        require_current_notice,
    )

    parent = run.request_json.get("forecast_parent")
    if not parent:
        return
    candidate, _ = await require_candidate(db, novel_id, parent["candidate_id"])
    notice = await require_current_notice(db, candidate)
    from modules.assistant.forecast.registry import SEMANTIC, require_rollout
    from modules.assistant.forecast.runtime import enabled, get_settings

    enabled()
    require_rollout(novel_id, [candidate.capability_id])
    if (
        candidate.capability_id in SEMANTIC
        and not get_settings().assistant_forecast_semantic_enabled
    ):
        raise ConflictError(
            "语义前瞻已暂停，原采用记录仍保留", code="SEMANTIC_UNAVAILABLE"
        )
    if candidate.assessment_hash != parent["assessment_hash"] or hidden_by_decision(
        notice
    ):
        raise ConflictError("原建议已变化或已被处置，请重新选择", code="SOURCE_STALE")
    if parent.get("direction_id") in declined_direction_ids(candidate, notice):
        raise ConflictError("该方向已被暂缓，请重新选择", code="SOURCE_STALE")
    if "direction_id" not in parent and declined_direction_ids(candidate, notice):
        raise ConflictError("旧预览未绑定具体方向，请重新准备", code="SOURCE_STALE")


async def receipt(db, novel_id, run):
    if not run.request_json.get("forecast_parent"):
        raise NotFoundError("预览记录不存在")
    batch = await db.scalar(
        select(AssistantActionBatch).where(
            AssistantActionBatch.novel_id == UUID(novel_id),
            AssistantActionBatch.run_id == run.id,
        )
    )
    try:
        await require_parent(db, novel_id, run)
        status = "preview_ready" if batch else "failed"
    except ConflictError:
        status = "stale"
    return PreparationReceipt(
        operation_id=run.operation_id,
        draft_id=run.request_json.get("context", {}).get("draft_id"),
        source_hash=run.request_json.get("context", {}).get("source_hash"),
        run_id=run.id,
        parent_forecast_run_id=run.request_json["forecast_parent"]["run_id"],
        batch_id=batch.id if batch else None,
        batch_fingerprint=batch.fingerprint if batch else None,
        status=status,
    )


async def prepare(db, novel_id, candidate_id, data):
    from modules.assistant.forecast.runtime import enabled
    from modules.assistant.forecast.service import (
        require_candidate,
        require_current_notice,
    )

    await authorize(db, novel_id)
    request_hash = content_hash([str(candidate_id), data.model_dump(mode="json")])
    existing = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.novel_id == UUID(novel_id),
            AssistantRun.operation_id == data.operation_id,
        )
    )
    if existing:
        if existing.request_hash != request_hash:
            raise ConflictError("操作标识已用于另一份选择", code="OPERATION_MISMATCH")
        return await receipt(db, novel_id, existing)
    enabled()
    candidate, ctx = await require_candidate(
        db, novel_id, candidate_id, focus=data.context
    )
    notice = await require_current_notice(db, candidate)
    if candidate.assessment_hash != data.expected_assessment_hash or hidden_by_decision(
        notice
    ):
        raise ConflictError("所选建议已变化或已处置", code="ASSESSMENT_CHANGED")
    action = next(
        (
            action
            for action in candidate.payload_json.get("actions", [])
            if action["action_id"] == data.action_id
        ),
        None,
    )
    if action is None or not action["available"]:
        raise ValidationError(
            "该选择没有可用的原领域预览", code="ACTION_UNAVAILABLE", status_code=503
        )
    proposal = candidate.payload_json["proposal"]
    direction = next(
        (
            item
            for item in proposal.get("directions", [])
            if data.action_id.endswith("." + item["direction_id"])
        ),
        None,
    )
    if direction and direction["direction_id"] in declined_direction_ids(
        candidate, notice
    ):
        raise ConflictError("该方向已被暂缓，请重新选择", code="ASSESSMENT_CHANGED")
    original = next(
        (
            value
            for value in candidate.payload_json.get("preparations", [])
            if value["action_id"] == data.action_id
        ),
        None,
    )
    if original:
        supported = {"imports.resolve_review", "imports.accept_review", "imports.resume"}
        if original["capability"] not in supported or not any(
            original in fact.preparations for fact, _ in ctx.facts
        ):
            raise ConflictError("原领域的范围或可用动作已经变化", code="SOURCE_STALE")
        capability, arguments = original["capability"], original["arguments"]
    elif data.action_id.startswith("writing.prepare_candidate.") and direction:
        if ctx.focus.task_hint in {"polish", "revise"}:
            raise ConflictError(
                "修改与润色须先准备精确替换，不能转为续写", code="ACTION_UNAVAILABLE"
            )
        capability = "writing.generate_candidate"
        arguments = {
            "chapter_index": ctx.chapter_index,
            "generation_mode": "continue",
            "instruction": "作者选择的局部方向（新创意，未发生）："
            + direction["proposal"]
            + "\n保留要求："
            + ctx.focus.explicit_instruction,
        }
    elif data.action_id.startswith("story.prepare_information_plan.") and direction:
        capability = "story.create_information_plan"
        arguments = {
            "name": proposal["title"],
            "summary": direction["proposal"],
            "surface_meaning": direction["condition"],
        }
    elif direction and data.action_id.split(".")[:2] in [
        ["world", "prepare_direction"],
        ["evidence", "prepare_direction"],
    ]:
        domain = data.action_id.split(".")[0]
        capability, arguments = await get("assistant.forecast.choices")[domain](
            db, novel_id, ctx, direction
        )
    elif data.action_id == "project.prepare_task":
        capability = "project.add_task"
        arguments = {"title": proposal["title"], "note": proposal["why_now"]}
    else:
        raise ValidationError(
            "此预览动作未注册", code="ACTION_UNAVAILABLE", status_code=503
        )
    parent = {
        "candidate_id": str(candidate.id),
        "assessment_hash": candidate.assessment_hash,
        "run_id": str(candidate.run_id),
        "direction_id": direction["direction_id"] if direction else None,
    }
    work = await work_context(db, novel_id, ctx)
    run = AssistantRun(
        id=data.operation_id,
        novel_id=UUID(novel_id),
        owner_id=ctx.scope.owner_id,
        operation_id=data.operation_id,
        status="waiting_approval",
        request_hash=request_hash,
        request_json={
            "runtime_version": "3",
            "protocol": "forecast_prepare_v1",
            "operations": {capability: operation_manifest()[capability]},
            "context": work.model_dump(mode="json"),
            "forecast_parent": parent,
        },
        budget_json=AgentRunBudget().model_dump(mode="json"),
    )
    actions = await prepare_actions(
        db,
        novel_id,
        [
            ProposedAction(
                key="selected",
                capability=capability,
                title=action["label"],
                arguments=arguments,
            )
        ],
        context=AssistantOperationContext(
            str(run.id), str(run.owner_id), work, operation_id=str(run.id)
        ),
    )
    try:
        async with db.begin_nested():
            db.add(run)
            await db.flush()
            batch = AssistantActionBatch(
                novel_id=run.novel_id,
                run_id=run.id,
                fingerprint=content_hash(actions),
                actions_json=actions,
            )
            db.add(batch)
            await db.flush()
            run.result_json = {
                "answer": "已准备这一项选择，请核对后确认。",
                "actions": actions,
                "batch_id": str(batch.id),
                "batch_fingerprint": batch.fingerprint,
            }
            await db.flush()
    except IntegrityError:
        existing = await db.scalar(
            select(AssistantRun).where(
                AssistantRun.novel_id == UUID(novel_id),
                AssistantRun.operation_id == data.operation_id,
            )
        )
        if existing is None or existing.request_hash != request_hash:
            raise ConflictError(
                "操作标识已用于不同预览", code="OPERATION_MISMATCH"
            ) from None
        return await receipt(db, novel_id, existing)
    return await receipt(db, novel_id, run)
