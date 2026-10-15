"""Concrete preview/confirm/apply with domain atomic groups and replay protection."""

from __future__ import annotations

import json
import re
import uuid
from copy import copy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError as SchemaValidationError
from pydantic import create_model, field_validator
from pydantic_ai import ModelRetry, RunContext, Tool
from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from core.service_keys import (
    ASSISTANT_OPERATIONS,
)
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
    return get(ASSISTANT_OPERATIONS)


def _catalog_metadata(operation: AssistantOperation) -> dict:
    return {
        "op_id": operation.op_id,
        "op_version": operation.op_version,
        "label": operation.label,
        "permission": operation.permission,
        "description": operation.description,
        "risk_level": operation.risk_level,
        "fee_category": operation.fee_category,
        "reversibility": operation.reversibility,
        "preconditions": operation.preconditions,
        "produces": operation.produces,
        "target_type": operation.target_type,
        "ai_available": operation.ai_available,
        "transaction_mode": operation.transaction_mode,
        "trace_rule": asdict(operation.trace_rule),
    }


def operation_manifest(*, legacy: bool = False) -> dict:
    """Return a v7+ frozen directory or the exact pre-v7 two-field shape."""
    result = {}
    for name, operation in catalog().items():
        entry = {
            "schema_hash": fingerprint(operation.schema.model_json_schema()),
            "revision": operation.revision,
        }
        if not legacy:
            metadata = _catalog_metadata(operation)
            entry.update(
                {
                    "op_version": operation.op_version,
                    "metadata_hash": fingerprint(metadata),
                    "metadata": metadata,
                    "schema": operation.schema.model_json_schema(),
                }
            )
        result[name] = entry
    return result


def runtime_protocol(payload: dict) -> dict:
    if payload.get("runtime_version") in {
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
        "10",
        "11",
    }:
        return payload
    if payload.get("runtime_version") == "1":
        frozen = json.loads(Path(__file__).with_name("runtime_v1.json").read_text())
        if payload.get("tools_hash") == frozen["tools_hash"]:
            return frozen
    raise ConflictError(
        "助手执行协议不可用，请重新提交", code="assistant_runtime_changed"
    )


def resolve_operations(
    manifest: dict, *, allow_stale: bool = False
) -> dict[str, AssistantOperation]:
    current = operation_manifest()
    # MapNodeCreate only widened: "interior" was added to level, then two
    # optional pinned type-reference fields. Legacy inputs remain valid; pin
    # the exact hash pairs so any other schema change still fails closed.
    map_node_hashes = (
        "afb6aa06a68c39a27026fc50565cdc87d72e266e569b362d95fdd23a428c2bc8",
        "061686f1c3f683f833a391f1515de6fea596a0403a38f357390d53b5bc54e5e7",
        "657072d928d4057f92652ede400155475a7f913444bb6aebcc71b2f6a334b051",
    )
    compatible_map_node = [
        (
            {"schema_hash": map_node_hashes[0], "revision": "1"},
            {"schema_hash": map_node_hashes[1], "revision": "1"},
        ),
        (
            {"schema_hash": map_node_hashes[1], "revision": "1"},
            {"schema_hash": map_node_hashes[2], "revision": "1"},
        ),
        (
            {"schema_hash": map_node_hashes[0], "revision": "1"},
            {"schema_hash": map_node_hashes[2], "revision": "1"},
        ),
    ]
    stale = []
    resolved = {}
    for name, frozen in manifest.items():
        if not isinstance(frozen, dict) or frozenset(frozen) not in {
            frozenset({"schema_hash", "revision"}),
            frozenset(
                {
                    "schema_hash",
                    "revision",
                    "op_version",
                    "metadata_hash",
                    "metadata",
                    "schema",
                }
            ),
        }:
            stale.append(name)
            continue
        current_entry = current.get(name)
        frozen_legacy = set(frozen) == {"schema_hash", "revision"}
        if current_entry is None:
            stale.append(name)
            continue
        matches = all(
            (
                fingerprint(current_entry.get(key)) == fingerprint(value)
                if key in {"metadata", "schema"}
                else current_entry.get(key) == value
            )
            for key, value in frozen.items()
        )
        map_node_compatible = (
            name == "map.create_node"
            and frozen_legacy
            and any(
                (
                    frozen,
                    {key: current_entry[key] for key in ("schema_hash", "revision")},
                )
                == pair
                for pair in compatible_map_node
            )
        )
        if not matches and not map_node_compatible:
            stale.append(name)
            continue
        operation = catalog()[name]
        if frozen_legacy and name == "map.prepare_tray_placement":
            # The pre-v7 catalog exposed this navigation helper as a confirm
            # action. Preserve that behavior for frozen legacy runs while v7
            # can invoke it through the dedicated R0 read tool.
            operation = replace(operation, permission="confirm")
        resolved[name] = operation
    if stale and not allow_stale:
        raise ConflictError(
            "本次运行需要的工具版本不可用，请重新提交", code="assistant_runtime_changed"
        )
    if "map.create_node" in resolved and manifest["map.create_node"].get(
        "schema_hash"
    ) != current["map.create_node"].get("schema_hash"):
        operation = resolved["map.create_node"]
        fields = {
            name: (field.annotation, copy(field))
            for name, field in operation.schema.model_fields.items()
            if name not in {"level_type_ref", "level_type_revision_id"}
        }
        if manifest["map.create_node"]["schema_hash"] == map_node_hashes[0]:
            fields["level"] = (
                Literal["region", "city", "district", "street"],
                fields["level"][1],
            )
        frozen_schema = create_model(
            "MapNodeCreate",
            __config__=operation.schema.model_config,
            __validators__={
                "readable_title": field_validator("title")(
                    operation.schema.readable_title.__func__
                )
            },
            **fields,
        )

        async def prepare(db, novel_id, args, *, context=None):
            return await operation.prepare(
                db,
                novel_id,
                operation.schema.model_validate(args.model_dump()),
                context=context,
            )

        async def apply(db, novel_id, args, preview, *, context=None):
            return await operation.apply(
                db,
                novel_id,
                operation.schema.model_validate(args.model_dump()),
                preview,
                context=context,
            )

        resolved["map.create_node"] = replace(
            operation, schema=frozen_schema, prepare=prepare, apply=apply
        )
    return resolved


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


MAX_OPERATION_SEARCH_RESULTS = 8


def _run_catalog_snapshot(ctx: RunContext[AssistantToolContext]) -> dict | None:
    return getattr(ctx.deps, "operation_catalog_snapshot", None)


def _metadata_result(operation: AssistantOperation) -> dict:
    return _catalog_metadata(operation)


async def find_operations(
    ctx: RunContext[AssistantToolContext],
    query: str = "",
    module: str | None = None,
    target_type: str | None = None,
) -> dict:
    """Find a few frozen operations by words, module, or target kind."""
    query = query.strip()[:160].casefold()
    module = module.strip().casefold() if module else None
    target_type = target_type.strip().casefold() if target_type else None
    terms = [term for term in re.findall(r"[\w.]+", query) if term]
    operations = _run_operations(ctx)
    manifest = _run_catalog_snapshot(ctx)
    matches = []
    for op_id, operation in operations.items():
        if not operation.ai_available:
            continue
        if module and op_id.split(".", 1)[0].casefold() != module:
            continue
        if target_type and operation.target_type.casefold() != target_type:
            continue
        haystack = " ".join(
            (op_id, operation.label, operation.description, operation.target_type)
        ).casefold()
        if terms and not any(term in haystack for term in terms):
            continue
        frozen = manifest.get(op_id) if manifest else None
        if frozen and (
            frozen.get("metadata_hash") != fingerprint(frozen.get("metadata"))
            or frozen.get("schema_hash")
            != fingerprint(operation.schema.model_json_schema())
        ):
            continue
        score = sum(1 for term in terms if term in haystack)
        matches.append((score, op_id, operation))
    matches.sort(key=lambda item: (-item[0], item[1]))
    return {
        "operations": [
            {
                "op_id": operation.op_id,
                "label": operation.label,
                "summary": operation.description[:240],
                "risk_level": operation.risk_level,
                "fee_category": operation.fee_category,
            }
            for _score, _op_id, operation in matches[:MAX_OPERATION_SEARCH_RESULTS]
        ],
        "truncated": len(matches) > MAX_OPERATION_SEARCH_RESULTS,
    }


async def describe_operation(ctx: RunContext[AssistantToolContext], op_id: str) -> dict:
    """Describe one frozen operation, including whether this run can execute it."""
    manifest = _run_catalog_snapshot(ctx)
    frozen = manifest.get(op_id) if manifest else None
    operation = _run_operations(ctx).get(op_id)
    if frozen is not None:
        current = operation_manifest().get(op_id)
        executable = bool(
            operation
            and current
            and frozen.get("metadata_hash") == fingerprint(frozen.get("metadata"))
            and current.get("metadata_hash") == frozen.get("metadata_hash")
            and current.get("schema_hash") == frozen.get("schema_hash")
        )
        metadata = frozen.get("metadata") or (
            _catalog_metadata(operation) if operation else {}
        )
        label = metadata.get("label") or (operation.label if operation else op_id)
        return {
            **metadata,
            "label": label,
            "schema": frozen.get("schema")
            or (operation.schema.model_json_schema() if operation else {}),
            "executable": executable,
            **({"unavailable_reason": "操作已下线或已变更"} if not executable else {}),
        }
    if operation is None:
        raise ValidationError("操作不在本次运行的冻结目录中")
    return {
        **_metadata_result(operation),
        "schema": operation.schema.model_json_schema(),
        "executable": True,
    }


async def read_operation(
    ctx: RunContext[AssistantToolContext], op_id: str, arguments: dict
) -> dict:
    """Execute only a registered R0 read projection; never call its apply handler."""
    deps = ctx.deps
    await deps.guard()
    operation = _run_operations(ctx).get(op_id)
    if operation is None:
        frozen = (_run_catalog_snapshot(ctx) or {}).get(op_id)
        if frozen:
            raise ConflictError("操作已下线或已变更", code="assistant_operation_changed")
        raise ModelRetry("请先查找并说明本次运行提供的只读操作")
    if operation.permission != "read" or operation.risk_level != "R0":
        raise ModelRetry("只读工具只能调用风险等级 R0 的目录操作")
    try:
        args = operation.schema.model_validate(arguments)
    except SchemaValidationError as error:
        raise ModelRetry(
            f"只读操作参数不正确：{error.errors(include_input=False, include_url=False)}"
        ) from None
    context = AssistantOperationContext(
        deps.run_id or "",
        deps.owner_id,
        deps.work,
        trace_enabled=deps.operation_trace_enabled,
        trace_session_id=deps.session_id,
    )
    return await operation.prepare(deps.db, deps.novel_id, args, context=context)


def operation_discovery_tools(
    *, legacy: bool, operations: dict[str, AssistantOperation]
) -> list[Tool]:
    if legacy:
        return [operation_tool()]
    tools = [
        Tool(find_operations, sequential=True),
        Tool(describe_operation, sequential=True),
    ]
    if any(operation.permission == "read" for operation in operations.values()):
        tools.append(Tool(read_operation, sequential=True))
    return tools


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
            frozen = (_run_catalog_snapshot(ctx) or {}).get(action.capability)
            if frozen:
                raise ModelRetry("操作已下线或已变更，请停止该步骤并请作者重新规划")
            raise ModelRetry("请先查找并说明本次运行提供的操作")
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
    context = AssistantOperationContext(
        deps.run_id,
        deps.owner_id,
        deps.work,
        trace_enabled=deps.operation_trace_enabled,
        trace_session_id=deps.session_id,
    )
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
        trace_enabled=deps.operation_trace_enabled,
        trace_session_id=deps.session_id,
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
                in {
                    "world.review",
                    "writing.review",
                    "writing.review_world",
                    "writing.review_team",
                }
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


async def _record_batch_event(db, run, item, operation, event_type, *, error_code=None):
    if not run.request_json.get("operation_trace_enabled"):
        return
    from core.container import get
    from core.service_keys import ASSISTANT_OPERATION_TRACE

    context = {
        "trace_call_id": str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{run.id}:action:{item['key']}")
        ),
        "trace_parent_call_id": str(run.id),
    }
    saved = await get(ASSISTANT_OPERATION_TRACE)(
        db,
        enabled=True,
        novel_id=str(run.novel_id),
        owner_id=str(run.owner_id),
        operation=operation,
        event_type=event_type,
        arguments=item.get("arguments"),
        preview=item.get("preview"),
        error_code=error_code,
        actor_type="ui",
        entrypoint="assistant.batch.confirm",
        run_id=str(run.id),
        session_id=str(run.session_id) if run.session_id else None,
        call_id=context["trace_call_id"],
        parent_call_id=context["trace_parent_call_id"],
    )
    if saved is False:
        checkpoint = dict(run.checkpoint_json or {})
        checkpoint["operation_trace_incomplete_count"] = (
            int(checkpoint.get("operation_trace_incomplete_count") or 0) + 1
        )
        checkpoint["operation_trace_incomplete"] = True
        run.checkpoint_json = checkpoint


async def prepare_actions(
    db,
    novel_id: str,
    proposals: list[ProposedAction],
    *,
    context: AssistantOperationContext,
    operations: dict[str, AssistantOperation] | None = None,
) -> list[dict]:
    prepared = []
    targets: set[str] = set()
    affected_count = 0
    for proposal in proposals:
        operation = (catalog() if operations is None else operations).get(
            proposal.capability
        )
        if operation is None:
            raise ValidationError("提案包含当前未提供的操作")
        args = operation.schema.model_validate(proposal.arguments)
        action_context = replace(
            context,
            trace_call_id=str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{context.run_id}:action:{proposal.key}")
            ),
        )
        preview = await operation.prepare(db, novel_id, args, context=action_context)
        action_targets = set(
            preview.get("target_keys")
            or ([preview["target_key"]] if preview.get("target_key") else [])
        )
        if targets.intersection(action_targets):
            raise ValidationError("同一资产的修改请合并为一个操作")
        targets.update(action_targets)
        affected_count += preview.get("affected_count", 1)
        if affected_count > 20:
            raise ValidationError("一次确认最多涉及 20 项，请拆分整理方案")
        prepared.append(
            {
                **proposal.model_dump(mode="json"),
                "arguments": args.model_dump(mode="json"),
                "preview": preview,
                "baseline_hash": fingerprint(preview),
                "operation_manifest": {
                    "schema_hash": fingerprint(operation.schema.model_json_schema()),
                    "revision": operation.revision,
                },
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
        if (
            bool(batch.authorization_json.get("review_after", False))
            != decision.review_after
        ):
            raise ConflictError("复核授权与原确认不同，请使用原决定重试")
        if set(batch.authorization_json.get("selected", [])) != keys:
            raise ConflictError(
                "该方案已有不同的确认决定", code="assistant_batch_decided"
            )
        retry_id = str(decision.retry_operation_id or "")
        if not retry_id or retry_id in batch.authorization_json.get("retries", []):
            return {
                "status": batch.status,
                "results": batch.results_json,
                **(
                    {"operation_trace_incomplete": True}
                    if (run.checkpoint_json or {}).get("operation_trace_incomplete")
                    else {}
                ),
            }
        if batch.status != "partial":
            raise ConflictError("只有未完成的操作可重试")
    elif decision.retry_operation_id:
        raise ValidationError("请先确认方案，再重试未完成的操作")
    completed = {
        item["key"]: item for item in batch.results_json if item["status"] == "completed"
    }
    available = (
        resolve_operations(
            runtime_protocol(run.request_json)["operations"],
            allow_stale=run.request_json.get("runtime_version")
            in {"7", "8", "9", "10", "11"},
        )
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
        operation_trace_enabled=bool(run.request_json.get("operation_trace_enabled")),
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
    confirmation_meta = {"confirmation_preflight": True, "confirmed_previews": []}
    trace_status = {"incomplete_count": 0}
    operation_context = AssistantOperationContext(
        str(run.id),
        owner_id,
        context.work,
        internal_meta=confirmation_meta,
        trace_status=trace_status,
    )
    if run.request_json.get("forecast_parent"):
        from modules.assistant.forecast.preparation import require_parent

        await require_parent(db, novel_id, run)
        operation_context = AssistantOperationContext(
            str(run.id),
            owner_id,
            context.work,
            operation_id=str(run.id),
            internal_meta=confirmation_meta,
            trace_status=trace_status,
        )
    if sum(item["preview"].get("affected_count", 1) for item in selected) > 20:
        raise ValidationError("一次确认最多涉及 20 项，请拆分整理方案")
    for item in selected:
        if item["key"] in completed:
            continue
        confirmation_meta["prepared_preview"] = item["preview"]
        if item.get("operation_manifest"):
            resolve_operations({item["capability"]: item["operation_manifest"]})
        if not set(item["depends_on"]).issubset(keys):
            raise ValidationError("请一并选择依赖操作")
        operation = available.get(item["capability"])
        if operation is None:
            raise ConflictError("操作不在本次运行的工具范围内")
        item_context = replace(
            operation_context,
            trace_call_id=str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{run.id}:action:{item['key']}")
            ),
            trace_actor_type="ui",
            trace_entrypoint="assistant.batch.confirm",
            trace_enabled=bool(run.request_json.get("operation_trace_enabled")),
            trace_session_id=str(run.session_id) if run.session_id else None,
        )
        preview = await operation.prepare(
            db,
            novel_id,
            operation.schema.model_validate(item["arguments"]),
            context=item_context,
        )
        if fingerprint(preview) != item["baseline_hash"]:
            raise ConflictError(
                "待修改的资料已变化，请重新生成方案", code="assistant_source_stale"
            )
        confirmation_meta["confirmed_previews"].append(fingerprint(preview))
    for item in batch.actions_json:
        operation = available.get(item["capability"])
        if operation is None:
            continue
        await _record_batch_event(
            db,
            run,
            item,
            operation,
            "confirmed" if item["key"] in keys else "declined",
        )
    batch.authorization_json = batch.authorization_json or {
        "owner_id": owner_id,
        "selected": decision.selected,
        "confirmed_at": datetime.now(UTC).isoformat(),
        "fingerprint": batch.fingerprint,
        "review_after": decision.review_after,
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
    outcome_unknown = False
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
                confirmation_meta["prepared_preview"] = item["preview"]
                operation = available[item["capability"]]
                item_context = replace(
                    operation_context,
                    trace_call_id=str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"{run.id}:action:{item['key']}")
                    ),
                    trace_actor_type="ui",
                    trace_entrypoint="assistant.batch.confirm",
                    trace_enabled=bool(run.request_json.get("operation_trace_enabled")),
                    trace_session_id=str(run.session_id) if run.session_id else None,
                    trace_parent_call_id=str(run.id),
                )
                result = await operation.apply(
                    db,
                    novel_id,
                    operation.schema.model_validate(item["arguments"]),
                    item["preview"],
                    context=item_context,
                )
                await db.flush()
                await context.record_confirmed_write(result)
        except DomainError:
            context.work, context.evidence_refs = previous_work, previous_refs
            failed.add(key)
            operation = available[item["capability"]]
            if operation.transaction_mode == "multi_stage":
                await _record_batch_event(
                    db,
                    run,
                    item,
                    operation,
                    "outcome_unknown",
                    error_code="operation_apply_failed",
                )
                results.append(
                    {"key": key, "status": "outcome_unknown", "message": "请核对领域回执"}
                )
                outcome_unknown = True
                break
            await _record_batch_event(
                db,
                run,
                item,
                operation,
                "failed",
                error_code="operation_apply_failed",
            )
            results.append(
                {
                    "key": key,
                    "status": "failed",
                    "message": "资料或操作条件已变化，请到来源位置核对",
                }
            )
        except Exception:
            context.work, context.evidence_refs = previous_work, previous_refs
            failed.add(key)
            operation = available[item["capability"]]
            if operation.transaction_mode == "multi_stage":
                await _record_batch_event(
                    db,
                    run,
                    item,
                    operation,
                    "outcome_unknown",
                    error_code="operation_apply_failed",
                )
                results.append(
                    {"key": key, "status": "outcome_unknown", "message": "请核对领域回执"}
                )
                outcome_unknown = True
                break
            await _record_batch_event(
                db,
                run,
                item,
                operation,
                "failed",
                error_code="operation_apply_failed",
            )
            raise
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
    if trace_status["incomplete_count"]:
        checkpoint = dict(run.checkpoint_json or {})
        checkpoint["operation_trace_incomplete_count"] = (
            int(checkpoint.get("operation_trace_incomplete_count") or 0)
            + trace_status["incomplete_count"]
        )
        checkpoint["operation_trace_incomplete"] = True
        run.checkpoint_json = checkpoint
    batch.status = (
        "outcome_unknown"
        if outcome_unknown
        else "partial"
        if failed
        else "completed"
        if selected
        else "declined"
    )
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
    return {
        "status": batch.status,
        "results": results,
        **(
            {"operation_trace_incomplete": True}
            if (run.checkpoint_json or {}).get("operation_trace_incomplete")
            else {}
        ),
    }
