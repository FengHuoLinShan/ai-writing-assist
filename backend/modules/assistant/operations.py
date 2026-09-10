"""Concrete preview/confirm/apply with domain atomic groups and replay protection."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError as SchemaValidationError
from pydantic_ai import ModelRetry, RunContext, Tool
from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.workflow_budget import budgeted_tool, workflow_budget
from infrastructure.tasks.facade import list_task_lifecycle_contracts, run_task_inline
from modules.assistant.contracts import AssistantOperation, AssistantOperationContext
from modules.assistant.evidence_tools import AssistantToolContext, fingerprint
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.schemas import (
    AssistantAnswer,
    BatchDecision,
    ProposedAction,
    WorkContext,
)
from modules.project.facade import require_active_project


def catalog() -> dict[str, AssistantOperation]:
    return get("assistant.operations")


def operation_manifest() -> dict:
    return {
        name: {
            "schema_hash": fingerprint(operation.schema.model_json_schema()),
            "revision": operation.revision,
        }
        for name, operation in catalog().items()
    }


def runtime_protocol(payload: dict) -> dict:
    if payload.get("runtime_version") in {"2", "3"}:
        return payload
    if payload.get("runtime_version") == "1":
        frozen = json.loads(Path(__file__).with_name("runtime_v1.json").read_text())
        if payload.get("tools_hash") == frozen["tools_hash"]:
            return frozen
    raise ConflictError(
        "助手执行协议不可用，请重新提交", code="assistant_runtime_changed"
    )


def resolve_operations(manifest: dict) -> dict[str, AssistantOperation]:
    current = operation_manifest()
    if any(current.get(name) != value for name, value in manifest.items()):
        raise ConflictError(
            "本次运行需要的工具版本不可用，请重新提交", code="assistant_runtime_changed"
        )
    return {name: catalog()[name] for name in manifest}


def _run_operations(ctx: RunContext[AssistantToolContext]):
    return catalog() if ctx.deps.operations is None else ctx.deps.operations


async def available_operations(ctx: RunContext[AssistantToolContext]) -> dict:
    """列出操作；人工正文设定核对使用 review_world_constraints。"""
    return {
        name: {
            "label": operation.label,
            "permission": operation.permission,
            "arguments": operation.schema.model_json_schema(),
        }
        for name, operation in _run_operations(ctx).items()
    }


def operation_tool() -> Tool:
    return Tool(available_operations, sequential=True)


def validate_agent_answer(
    ctx: RunContext[AssistantToolContext], answer: AssistantAnswer
) -> AssistantAnswer:
    refs = set(answer.evidence_ids) | {
        key for finding in answer.findings for key in finding.evidence_ids
    }
    if not refs.issubset(ctx.deps.evidence_refs):
        raise ModelRetry(
            "只能引用本轮实际读到的 evidence_id；无法证明的判断请放入遗漏说明"
        )
    if any(
        ctx.deps.evidence_refs[key].get("coverage") == "search_snippet" for key in refs
    ):
        raise ModelRetry("搜索摘要尚未核实；请读取网页后引用，无法读取则列入遗漏说明")
    for finding in answer.findings:
        if finding.kind != "issue":
            continue
        domain_ids = {
            str(item.get("finding_id") or item.get("id"))
            for key in finding.evidence_ids
            for item in ctx.deps.evidence_refs[key]
            .get("review_result", {})
            .get("findings", [])
            if ctx.deps.evidence_refs[key].get("domain_reference")
        }
        if not finding.domain_finding_id or finding.domain_finding_id not in domain_ids:
            raise ModelRetry(
                "已验证问题必须引用领域复核的 finding_id 与对应 evidence_id；"
                "未完成复核的讨论设想只能列为建议"
            )
    for action in answer.actions:
        operation = _run_operations(ctx).get(action.capability)
        if operation is None:
            raise ModelRetry("请先查 available_operations，只能提出已经提供的业务操作")
        if operation.permission != "confirm":
            raise ModelRetry(
                "查证和建议生成请直接调用相应工具；只有具体资料修改放入确认方案"
            )
        try:
            operation.schema.model_validate(action.arguments)
        except SchemaValidationError as error:
            details = error.errors(include_input=False, include_url=False)
            raise ModelRetry(f"请修正 {action.capability} 的参数：{details}") from None
    try:
        _ordered([action.model_dump() for action in answer.actions])
    except ValidationError as error:
        raise ModelRetry(str(error)) from None
    return answer


async def review_world_constraints(
    ctx: RunContext[AssistantToolContext], draft_ids: list[str]
) -> dict:
    """核对人工正文与世界设定，只使用当前授权内的资料，不签署人物知识边界。"""
    return await review_assets(ctx, "writing.review_world", {"draft_ids": draft_ids})


async def review_assets(
    ctx: RunContext[AssistantToolContext],
    capability: Literal["world.review", "writing.review"],
    arguments: dict,
) -> dict:
    """直接复核，不改写业务。

    world.review 参数为 root_type/root_id；writing.review 为 draft_ids。
    """
    return await execute_suggestion(ctx, capability, arguments)


async def generate_structure(
    ctx: RunContext[AssistantToolContext], arguments: dict
) -> dict:
    """按 available_operations 中 story.plan_structure 的参数准备结构提案，尚不采用。"""
    return await execute_suggestion(ctx, "story.plan_structure", arguments)


async def scan_duplicates(ctx: RunContext[AssistantToolContext], arguments: dict) -> dict:
    """在作者已选择的整个作品范围查找相似资料，合并等操作留在原比较工作台确认。"""
    return await execute_suggestion(ctx, "project.scan_duplicates", arguments)


async def generate_candidate(
    ctx: RunContext[AssistantToolContext], arguments: dict
) -> dict:
    """按 writing.generate_candidate 参数生成/续写候选，保存原参考资料，不直接采用。"""
    return await execute_suggestion(ctx, "writing.generate_candidate", arguments)


async def revise_candidate(
    ctx: RunContext[AssistantToolContext], arguments: dict
) -> dict:
    """按 writing.targeted_revision 参数，从原审稿的 finding 生成返修候选，不直接采用。"""
    return await execute_suggestion(ctx, "writing.targeted_revision", arguments)


@budgeted_tool
async def execute_suggestion(ctx, capability, arguments):
    deps = ctx.deps
    await deps.guard()
    if not deps.run_id or not deps.task_id or not deps.llm_snapshot:
        raise ModelRetry("复核需要当前助手的持久化执行范围")
    operation = _run_operations(ctx).get(capability)
    if operation is None or operation.permission != "suggest":
        raise ModelRetry("本次运行没有授权此建议工具")
    try:
        args = operation.schema.model_validate(arguments)
    except SchemaValidationError as error:
        raise ModelRetry(
            f"复核参数不正确：{error.errors(include_input=False, include_url=False)}"
        ) from None
    context = AssistantOperationContext(deps.run_id, deps.owner_id, deps.work)
    preview = await operation.prepare(deps.db, deps.novel_id, args, context=context)
    operation_id = str(
        uuid.uuid5(
            uuid.UUID(deps.run_id),
            capability + fingerprint([args.model_dump(mode="json"), preview]),
        )
    )
    context = AssistantOperationContext(
        deps.run_id,
        deps.owner_id,
        deps.work,
        operation_id=operation_id,
        llm_snapshot=deps.llm_snapshot,
        internal_meta={"_execution_mode": "inline_only", "_parent_task_id": deps.task_id},
    )
    reference = await operation.apply(
        deps.db, deps.novel_id, args, preview, context=context
    )
    if not reference.get("task_type") or not operation.read_result:
        raise ValidationError("复核没有稳定结果接口")
    target = reference.get("target") or {}
    record = {
        "title": operation.label,
        "domain_reference": reference,
        "source_guard": {
            "capability": capability,
            "arguments": args.model_dump(mode="json"),
            "baseline_hash": fingerprint(preview),
        },
        "target_ref": {"target_type": target.get("type"), "target_id": target.get("id")}
        if target.get("id")
        else None,
    }
    deps.remember({**record, "snippet": "本次复核的过程回执；尚未形成完整结论"})
    await deps.checkpoint(deps.budget.model_dump(mode="json"))
    life = (
        await list_task_lifecycle_contracts(
            deps.db,
            task_ids=[reference["task_id"]],
            novel_id=deps.novel_id,
            max_heartbeat_gap=0,
        )
    ).get(reference["task_id"])
    await deps.db.commit()
    if life is None:
        raise NotFoundError("复核任务回执不存在")
    if life.status == "pending":
        with workflow_budget(
            deps.budget, deps.checkpoint, future_requests=deps.final_requests
        ):
            try:
                await run_task_inline(
                    deps.db,
                    task_id=reference["task_id"],
                    expected_task_type=reference["task_type"],
                )
            except Exception:
                # Domain workflows keep their own partial receipts. Never hide a
                # cancellation or spend a second independent work budget here.
                await deps.db.rollback()
                await deps.guard()
    result = await operation.read_result(deps.db, deps.novel_id, reference)
    snippets = [
        str(item.get("message") or item.get("summary") or item.get("title") or "")
        for item in result.get("findings", [])[:10]
    ]
    saved = deps.remember(
        {
            **record,
            **(
                {"review_result": result}
                if capability
                in {"world.review", "writing.review", "writing.review_world"}
                else {"domain_result": result}
            ),
            "snippet": "\n".join(snippets)
            or "已保存领域复核回执，请结合实际覆盖范围判断",
        }
    )
    await deps.checkpoint(deps.budget.model_dump(mode="json"))
    return saved or {"omission": "当前范围已排除该资料"}


def _ordered(actions: list[dict]) -> list[dict]:
    by_key = {item["key"]: item for item in actions}
    if len(by_key) != len(actions):
        raise ValidationError("操作标识重复")
    remaining = list(actions)
    ordered: list[dict] = []
    done: set[str] = set()
    while remaining:
        ready = [item for item in remaining if set(item["depends_on"]).issubset(done)]
        if not ready:
            raise ValidationError("操作依赖缺失或存在循环")
        for item in ready:
            remaining.remove(item)
            ordered.append(item)
            done.add(item["key"])
    return ordered


async def prepare_actions(
    db,
    novel_id: str,
    proposals: list[ProposedAction],
    *,
    context: AssistantOperationContext,
) -> list[dict]:
    prepared = []
    targets: set[str] = set()
    for proposal in proposals:
        operation = catalog().get(proposal.capability)
        if operation is None:
            raise ValidationError("提案包含当前未提供的操作")
        args = operation.schema.model_validate(proposal.arguments)
        preview = await operation.prepare(db, novel_id, args, context=context)
        target = preview.get("target_key")
        if target and target in targets:
            raise ValidationError("同一资产的修改请合并为一个操作")
        if target:
            targets.add(target)
        prepared.append(
            {
                **proposal.model_dump(mode="json"),
                "arguments": args.model_dump(mode="json"),
                "preview": preview,
                "baseline_hash": fingerprint(preview),
                "operation_manifest": operation_manifest()[proposal.capability],
            }
        )
    return _ordered(prepared)


async def decide_batch(db, batch_id: str, decision: BatchDecision, owner_id: str) -> dict:
    novel_id = str(decision.novel_id)
    await require_active_project(db, novel_id)
    batch = await db.scalar(
        select(AssistantActionBatch)
        .where(
            AssistantActionBatch.id == uuid.UUID(batch_id),
            AssistantActionBatch.novel_id == decision.novel_id,
        )
        .with_for_update()
    )
    if batch is None:
        raise NotFoundError("修改方案不存在")
    run = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.id == batch.run_id, AssistantRun.novel_id == decision.novel_id
        )
    )
    if run is None or str(run.owner_id) != owner_id:
        raise NotFoundError("修改方案不存在")
    if batch.fingerprint != decision.fingerprint:
        raise ConflictError("修改方案已变化", code="assistant_batch_stale")
    keys = set(decision.selected)
    selected = [item for item in batch.actions_json if item["key"] in keys]
    if len(keys) != len(decision.selected) or len(selected) != len(keys):
        raise ValidationError("所选操作不属于当前方案")
    if batch.authorization_json:
        if set(batch.authorization_json.get("selected", [])) != keys:
            raise ConflictError(
                "该方案已有不同的确认决定", code="assistant_batch_decided"
            )
        retry_id = str(decision.retry_operation_id or "")
        if not retry_id or retry_id in batch.authorization_json.get("retries", []):
            return {"status": batch.status, "results": batch.results_json}
        if batch.status != "partial":
            raise ConflictError("只有未完成的操作可重试")
    elif decision.retry_operation_id:
        raise ValidationError("请先确认方案，再重试未完成的操作")
    completed = {
        item["key"]: item for item in batch.results_json if item["status"] == "completed"
    }
    available = (
        resolve_operations(runtime_protocol(run.request_json)["operations"])
        if run.request_json.get("runtime_version")
        else catalog()
    )

    async def unused_checkpoint(_value):
        raise RuntimeError("Confirmation preflight cannot execute the model")

    context = AssistantToolContext(
        db,
        novel_id,
        owner_id,
        WorkContext.model_validate(run.request_json.get("context", {})),
        None,
        AgentRunBudget.model_validate(run.budget_json or {}),
        unused_checkpoint,
        evidence_refs=dict((run.checkpoint_json or {}).get("evidence_refs") or {}),
    )
    postconditions = (batch.authorization_json or {}).get("postconditions") or {}
    if completed and postconditions:
        context.work = WorkContext.model_validate(postconditions["work"])
        context.evidence_refs.update(postconditions["evidence_refs"])
    await context.revalidate(
        list(context.evidence_refs)
        if selected
        else list(
            dict.fromkeys(
                run.result_json.get("evidence_ids", [])
                + [
                    key
                    for finding in run.result_json.get("findings", [])
                    for key in finding.get("evidence_ids", [])
                ]
            )
        )
    )
    operation_context = AssistantOperationContext(str(run.id), owner_id, context.work)
    for item in selected:
        if item["key"] in completed:
            continue
        if item.get("operation_manifest"):
            resolve_operations({item["capability"]: item["operation_manifest"]})
        if not set(item["depends_on"]).issubset(keys):
            raise ValidationError("请一并选择依赖操作")
        operation = available.get(item["capability"])
        if operation is None:
            raise ConflictError("操作不在本次运行的工具范围内")
        preview = await operation.prepare(
            db,
            novel_id,
            operation.schema.model_validate(item["arguments"]),
            context=operation_context,
        )
        if fingerprint(preview) != item["baseline_hash"]:
            raise ConflictError(
                "待修改的资料已变化，请重新生成方案", code="assistant_source_stale"
            )
    batch.authorization_json = batch.authorization_json or {
        "owner_id": owner_id,
        "selected": decision.selected,
        "confirmed_at": datetime.now(UTC).isoformat(),
        "fingerprint": batch.fingerprint,
    }
    if decision.retry_operation_id:
        batch.authorization_json = {
            **batch.authorization_json,
            "retries": [
                *batch.authorization_json.get("retries", []),
                str(decision.retry_operation_id),
            ],
        }
    results = []
    failed: set[str] = set()
    for item in selected:
        key = item["key"]
        if key in completed:
            results.append(completed[key])
            continue
        if set(item["depends_on"]).intersection(failed):
            failed.add(key)
            results.append({"key": key, "status": "blocked", "message": "前置操作未成功"})
            continue
        previous_work, previous_refs = context.work, dict(context.evidence_refs)
        try:
            async with db.begin_nested():
                operation = catalog()[item["capability"]]
                result = await operation.apply(
                    db,
                    novel_id,
                    operation.schema.model_validate(item["arguments"]),
                    item["preview"],
                    context=operation_context,
                )
                await db.flush()
                await context.record_confirmed_write(result)
        except DomainError:
            context.work, context.evidence_refs = previous_work, previous_refs
            failed.add(key)
            results.append(
                {
                    "key": key,
                    "status": "failed",
                    "message": "资料或操作条件已变化，请到来源位置核对",
                }
            )
        else:
            results.append({"key": key, "status": "completed", "result": result})
    batch.authorization_json = {
        **batch.authorization_json,
        "postconditions": {
            "work": context.work.model_dump(mode="json"),
            "evidence_refs": {
                key: value
                for key, value in context.evidence_refs.items()
                if value != (run.checkpoint_json or {}).get("evidence_refs", {}).get(key)
            },
        },
    }
    batch.results_json = results
    batch.status = "partial" if failed else "completed" if selected else "declined"
    run.status = "completed"
    if run.session_id:
        from modules.assistant.sessions import AssistantSessionService

        sessions = AssistantSessionService()
        session = await sessions._require_session(db, novel_id, str(run.session_id))
        titles = "、".join(item["title"] for item in selected) or "本次暂不采用"
        await sessions.append_message(
            db,
            session,
            role="author",
            kind="decision",
            task_id=str(run.task_id) if run.task_id else None,
            context_confirmation_id=(
                str(context.work.context_confirmation_id)
                if context.work.context_confirmation_id
                else None
            ),
            content=("重试未完成操作：" if decision.retry_operation_id else "已确认：")
            + titles
            + ("。部分操作尚未完成。" if failed else "。"),
        )
    await db.flush()
    return {"status": batch.status, "results": results}
