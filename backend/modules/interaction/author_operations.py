"""Author-safe operations over RP journeys explicitly sourced from one project.

The current author project, the RP consumer project, and the frozen source
revision are deliberately resolved and checked as separate objects here.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.capabilities import capability_from_execution_snapshot
from infrastructure.tasks.facade import (
    enqueue_operation_task,
    get_operation_task,
    list_task_lifecycle_contracts,
)
from infrastructure.tasks.registry import TaskRegistry
from modules.account.facade import current_account_id, is_demo_readonly_principal
from modules.interaction.generation import InteractionGenerationWorkflow
from modules.interaction.models import InteractionJourney, InteractionSourceRevision
from modules.interaction.services import InteractionService, path_hash
from modules.interaction.source_service import InteractionSourceService
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    get_any_project_context,
    get_archived_interaction_project_ref,
)

SUMMARY_TASK_TYPE = "interaction_summary_refresh"
SUMMARY_ROOT_CAPABILITY = "interaction.summary_refresh"
_service = InteractionService()
_sources = InteractionSourceService()


class StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListAuthorJourneysArgs(StrictArgs):
    author_project_id: UUID
    status: Literal["active", "archived"] = "active"


class UpdateJourneySettingsArgs(StrictArgs):
    author_project_id: UUID
    journey_id: UUID
    expected_selection_epoch: int = Field(ge=0)
    expected_action_options_enabled: bool
    action_options_enabled: bool
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class RenameJourneyArgs(StrictArgs):
    author_project_id: UUID
    journey_id: UUID
    expected_title: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class JourneyStateArgs(StrictArgs):
    author_project_id: UUID
    journey_id: UUID
    expected_status: Literal["active", "archived"]
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


class SummaryRefreshArgs(StrictArgs):
    author_project_id: UUID
    journey_id: UUID
    operation_id: UUID | None = None
    expected_preview_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    confirmed: bool = False


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def _bound_journey(
    db, novel_id: str, args, *, status=None, require_active_consumer=True
):
    """Resolve all three project identities and fail closed on any mismatch."""
    author_project_id = str(args.author_project_id)
    if author_project_id != str(novel_id):
        raise NotFoundError("作品项目不存在")
    if is_demo_readonly_principal():
        raise NotFoundError("作品项目不存在")
    author_project = await _sources.require_author_project(db, author_project_id)
    journey = await _service._owned_journey(
        db,
        str(args.journey_id),
        status=status,
        for_update=False,
        require_project=(status != "archived" and require_active_consumer),
    )
    if journey.source_revision_id is None:
        raise NotFoundError("该旅程未关联当前作品资料")
    revision = await _sources._owned_revision(db, str(journey.source_revision_id))
    owner_id = str(current_account_id())
    if (
        str(revision.owner_id) != owner_id
        or str(revision.source_novel_id) != author_project_id
        or str(journey.owner_id) != owner_id
    ):
        raise NotFoundError("旅程不属于当前作品")
    consumer_project = await get_any_project_context(db, str(journey.novel_id))
    if consumer_project is None and (status == "archived" or not require_active_consumer):
        consumer_project = await get_archived_interaction_project_ref(
            db, str(journey.novel_id), owner_id=owner_id
        )
    if (
        consumer_project is None
        or str(consumer_project.owner_id) != owner_id
        or (
            getattr(consumer_project, "project_kind", "interaction")
            != "interaction"
        )
    ):
        raise NotFoundError("旅程不存在")
    return author_project, consumer_project, journey, revision


def _journey_card(author_project, consumer_project, journey, revision):
    return {
        "id": str(journey.id),
        "title": journey.title,
        "title_source": journey.title_source,
        "status": journey.status,
        "action_options_enabled": journey.action_options_enabled,
        "selection_epoch": journey.selection_epoch,
        "overview_epoch": journey.overview_epoch,
        "latest_activity_at": journey.latest_activity_at.isoformat()
        if journey.latest_activity_at
        else None,
        "source": {
            "author_project_id": str(author_project.novel_id),
            "revision_id": str(revision.id),
            "fingerprint": revision.fingerprint,
            "version_number": revision.version_number,
            "stale": revision.status != "ready",
        },
        # Expose a distinct consumer identity for author confirmation and audits.
        "consumer_project_id": str(consumer_project.novel_id),
    }


async def _list_journeys(db, novel_id, args, *, context=None):
    if is_demo_readonly_principal():
        raise NotFoundError("作品项目不存在")
    author_project_id = str(args.author_project_id)
    if author_project_id != str(novel_id):
        raise NotFoundError("作品项目不存在")
    author_project = await _sources.require_author_project(db, author_project_id)
    rows = await db.scalars(
        select(InteractionJourney)
        .join(
            InteractionSourceRevision,
            InteractionJourney.source_revision_id == InteractionSourceRevision.id,
        )
        .where(
            InteractionJourney.owner_id == current_account_id(),
            InteractionJourney.status == args.status,
            InteractionSourceRevision.owner_id == current_account_id(),
            InteractionSourceRevision.source_novel_id == author_project.novel_id,
        )
        .order_by(
            InteractionJourney.latest_activity_at.desc(), InteractionJourney.id.desc()
        )
        .limit(50)
    )
    items = []
    latest_revision = await _sources._repo.latest_source_revision(
        db,
        source_novel_id=UUID(str(author_project.novel_id)),
        owner_id=current_account_id(),
    )
    for row in rows:
        try:
            _author, consumer, journey, revision = await _bound_journey(
                db,
                novel_id,
                args.model_copy(update={"journey_id": row.id}),
                status=args.status,
            )
        except NotFoundError:
            # A stale or malformed cross-project reference is never projected.
            continue
        item = _journey_card(author_project, consumer, journey, revision)
        item["source"]["latest_revision_id"] = (
            str(latest_revision.id) if latest_revision is not None else None
        )
        item["source"]["stale"] = (
            revision.status != "ready"
            or latest_revision is None
            or latest_revision.id != revision.id
        )
        items.append(item)
    return {"items": items, "total": len(items), "limit": 50}


async def _journey_list_prepare(db, novel_id, args, *, context=None):
    return await _list_journeys(db, novel_id, args, context=context)


async def _settings_prepare(db, novel_id, args, *, context=None):
    _author, _consumer, journey, _revision = await _bound_journey(
        db, novel_id, args, status="active"
    )
    if journey.selection_epoch != args.expected_selection_epoch:
        raise ConflictError("旅程已变化，请重新读取", code="JOURNEY_CHANGED")
    if journey.action_options_enabled != args.expected_action_options_enabled:
        raise ConflictError("旅程设置已变化，请重新读取", code="JOURNEY_CHANGED")
    return {
        "journey_id": str(journey.id),
        "author_project_id": str(args.author_project_id),
        "consumer_project_id": str(journey.novel_id),
        "selection_epoch": journey.selection_epoch,
        "before": {"action_options_enabled": journey.action_options_enabled},
        "after": {"action_options_enabled": args.action_options_enabled},
        "effect": "只改变 RP 回复是否显示可选行动；不会启用后台续写、联网或团队能力。",
    }


async def _settings_apply(db, novel_id, args, preview, *, context=None):
    if context is None and not args.confirmed:
        raise ConflictError("请确认这项旅程设置", code="CONFIRMATION_REQUIRED")
    current = await _settings_prepare(db, novel_id, args, context=context)
    if current != preview or (
        args.expected_preview_hash is not None
        and args.expected_preview_hash != _fingerprint(current)
    ):
        raise ConflictError("旅程设置已变化，请重新准备", code="JOURNEY_CHANGED")
    await _service.update_author_display_settings(
        db,
        journey_id=str(args.journey_id),
        action_options_enabled=args.action_options_enabled,
        expected_selection_epoch=args.expected_selection_epoch,
        expected_action_options_enabled=args.expected_action_options_enabled,
    )
    return {
        "type": "interaction_journey",
        "id": str(args.journey_id),
        "label": "旅程设置已更新",
    }


async def _rename_prepare(db, novel_id, args, *, context=None):
    _author, _consumer, journey, _revision = await _bound_journey(
        db, novel_id, args, status="active"
    )
    if journey.title != args.expected_title:
        raise ConflictError("旅程标题已变化，请重新读取", code="JOURNEY_CHANGED")
    if args.title.strip() == journey.title:
        raise ConflictError("新标题与当前标题相同", code="NO_CHANGE")
    return {
        "journey_id": str(journey.id),
        "author_project_id": str(args.author_project_id),
        "consumer_project_id": str(journey.novel_id),
        "before": {"title": journey.title},
        "after": {"title": args.title.strip()},
        "effect": "重命名该旅程，不改动作品资料或 RP 历史。",
    }


async def _rename_apply(db, novel_id, args, preview, *, context=None):
    if context is None and not args.confirmed:
        raise ConflictError("请确认新标题", code="CONFIRMATION_REQUIRED")
    current = await _rename_prepare(db, novel_id, args, context=context)
    if current != preview or (
        args.expected_preview_hash is not None
        and args.expected_preview_hash != _fingerprint(current)
    ):
        raise ConflictError("旅程标题已变化，请重新准备", code="JOURNEY_CHANGED")
    await _service.update_title(
        db,
        journey_id=str(args.journey_id),
        title=args.title.strip(),
        expected_title=args.expected_title,
    )
    return {
        "type": "interaction_journey",
        "id": str(args.journey_id),
        "label": "旅程已重命名",
    }


async def _state_prepare(db, novel_id, args, *, context=None):
    _author, consumer, journey, revision = await _bound_journey(
        db, novel_id, args, status=args.expected_status
    )
    return {
        "journey_id": str(journey.id),
        "author_project_id": str(args.author_project_id),
        "consumer_project_id": str(consumer.novel_id),
        "source_revision_id": str(revision.id),
        "source_fingerprint": revision.fingerprint,
        "status": journey.status,
        "title": journey.title,
        "updated_at": journey.updated_at.isoformat() if journey.updated_at else None,
        "effect": (
            "归档可从历史旅程恢复；不会删除旅程、会话或作品资料。"
            if args.expected_status == "active"
            else "恢复归档旅程，不改变其历史或来源修订。"
        ),
    }


async def _archive_apply(db, novel_id, args, preview, *, context=None):
    if context is None and not args.confirmed:
        raise ConflictError("请确认归档这段旅程", code="CONFIRMATION_REQUIRED")
    current = await _state_prepare(db, novel_id, args, context=context)
    if current != preview or (
        args.expected_preview_hash is not None
        and args.expected_preview_hash != _fingerprint(current)
    ):
        raise ConflictError("旅程或来源已变化，请重新准备", code="JOURNEY_CHANGED")
    await _service.archive_journey(db, journey_id=str(args.journey_id), confirmed=True)
    return {
        "type": "interaction_journey",
        "id": str(args.journey_id),
        "label": "旅程已归档",
    }


async def _restore_apply(db, novel_id, args, preview, *, context=None):
    if context is None and not args.confirmed:
        raise ConflictError("请确认恢复这段旅程", code="CONFIRMATION_REQUIRED")
    current = await _state_prepare(db, novel_id, args, context=context)
    if current != preview or (
        args.expected_preview_hash is not None
        and args.expected_preview_hash != _fingerprint(current)
    ):
        raise ConflictError("旅程或来源已变化，请重新准备", code="JOURNEY_CHANGED")
    await _service.restore_journey(db, journey_id=str(args.journey_id))
    return {
        "type": "interaction_journey",
        "id": str(args.journey_id),
        "label": "旅程已恢复",
    }


async def _summary_preview(db, novel_id, args, *, context=None):
    if str(args.author_project_id) != str(novel_id):
        raise NotFoundError("作品项目不存在")
    _author, consumer, journey, revision = await _bound_journey(
        db, novel_id, args, status="active"
    )
    if not revision.fingerprint:
        raise ConflictError("当前旅程的作品资料尚未完成整理", code="SOURCE_NOT_READY")
    path = await _service._repo.get_selected_path(db, journey=journey)
    if not _service._story_started(path):
        raise ConflictError("故事开始后才会形成回顾", code="SUMMARY_NOT_READY")
    selected_hash = path_hash(path)
    latest_revision = await _sources._repo.latest_source_revision(
        db,
        source_novel_id=UUID(str(args.author_project_id)),
        owner_id=current_account_id(),
    )
    source_stale = (
        revision.status != "ready"
        or latest_revision is None
        or latest_revision.id != revision.id
    )
    snapshot = await build_project_llm_execution_snapshot(db, str(journey.novel_id))
    prepared = await InteractionGenerationWorkflow()._prepare_summary_generation(
        db,
        journey=journey,
        current_path=path,
        expected_path_hash=selected_hash,
        started_epoch=journey.overview_epoch,
        snapshot=snapshot,
    )
    if prepared is None:
        raise ConflictError(
            "当前资料已经整理完成，或没有可安全压缩的旧段", code="SUMMARY_NOT_DUE"
        )
    task_definition = TaskRegistry().get_definition(SUMMARY_TASK_TYPE)
    root = TaskRegistry().get_root_capability(SUMMARY_TASK_TYPE)
    author_task = SimpleNamespace(meta={"author_project_id": str(args.author_project_id)})
    author_deadline = TaskRegistry().resolve_run_deadline_seconds(
        SUMMARY_TASK_TYPE, author_task
    )
    unknown_policy = TaskRegistry().resolve_unknown_charge_policy(
        SUMMARY_TASK_TYPE, author_task
    )
    eighty_percent_stop = TaskRegistry().resolve_run_eighty_percent_stop(
        SUMMARY_TASK_TYPE, author_task
    )
    if (
        task_definition is None
        or root != SUMMARY_ROOT_CAPABILITY
        or task_definition.recovery_policy != "auto_requeue"
        or task_definition.max_attempts != 2
        or task_definition.run_request_limit != 8
        or author_deadline != 1800
        or unknown_policy != "stop_before_replay"
        or not eighty_percent_stop
    ):
        raise ConflictError(
            "摘要刷新预算或恢复契约不可用", code="SUMMARY_TASK_CONTRACT_UNAVAILABLE"
        )
    safe = {
        "author_project_id": str(args.author_project_id),
        "consumer_project_id": str(consumer.novel_id),
        "journey_id": str(journey.id),
        "source_revision_id": str(revision.id),
        "source_fingerprint": revision.fingerprint,
        "latest_source_revision_id": str(latest_revision.id) if latest_revision else None,
        "source_stale": source_stale,
        "selected_path_hash": selected_hash,
        "selected_leaf_node_id": str(path[-1].id),
        "overview_epoch": journey.overview_epoch,
        "segment_node_count": len(prepared.segment_node_ids),
        "protected_tail_node_count": len(prepared.protected_node_ids),
        "estimated_input_tokens": prepared.estimated_input_tokens,
        "request_limit": 8,
        "max_attempts": task_definition.max_attempts,
        "recovery_policy": task_definition.recovery_policy,
        "retry_transient_llm_errors": task_definition.retry_transient_llm_errors,
        "fix_attempts_per_request": 1,
        "max_provider_requests_per_run": 8,
        "eighty_percent_stop_after_requests": 7,
        "root_capability_id": root,
        "envelope_version": 2,
        "started_at_semantics": (
            "首次worker领取时冻结；同一Task的attempt与恢复沿用原起点和累计用量。"
        ),
        "deadline_seconds": author_deadline,
        "token_limit": task_definition.run_token_limit,
        "input_ceiling_tokens": capability_from_execution_snapshot(
            snapshot
        ).summary_input_ceiling_tokens,
        "output_limit_tokens": capability_from_execution_snapshot(
            snapshot
        ).summary_output_tokens,
        "provider_timeout_seconds": capability_from_execution_snapshot(
            snapshot
        ).interaction_timeout_seconds,
        "provider": (snapshot.get("profile") or {}).get("provider_id"),
        "model": (snapshot.get("profile") or {}).get("model"),
        "possible_charge": True,
        "execution_block_reason": None,
        "scope_note": (
            "只整理当前选定路径中已覆盖范围之后的旧故事段；"
            "新近尾段会保留。不会重读作品正文。"
        ),
        "snapshot_fingerprint": _fingerprint(snapshot),
    }
    safe["unknown_charge_policy"] = unknown_policy
    safe["unknown_charge_stop_available"] = unknown_policy == "stop_before_replay"
    safe["execution_ready"] = safe["unknown_charge_stop_available"]
    if safe["execution_ready"]:
        safe["execution_block_reason"] = None
    safe["preview_hash"] = _fingerprint(safe)
    return safe


def _summary_task_payload(args, preview):
    return {
        "author_project_id": str(args.author_project_id),
        "journey_id": str(args.journey_id),
        "preview_hash": preview["preview_hash"],
    }


async def _submit_summary_task(db, args, preview, *, operation_id: str):
    payload = _summary_task_payload(
        args.model_copy(update={"operation_id": operation_id}), preview
    )
    existing = await get_operation_task(
        db,
        operation_id=operation_id,
        task_type=SUMMARY_TASK_TYPE,
        novel_id=preview["consumer_project_id"],
        request_payload=payload,
    )
    if existing is not None:
        return {
            "type": "interaction_summary_refresh",
            "task_id": existing.task_id,
            "status": existing.status,
            "replayed": True,
            "root_capability_id": SUMMARY_ROOT_CAPABILITY,
            "recovery_policy": "auto_requeue",
            "request_limit": 8,
        }
    _author, consumer, journey, _revision = await _bound_journey(
        db, str(args.author_project_id), args, status="active"
    )
    if journey.summary_refresh_task_id:
        active = await list_task_lifecycle_contracts(
            db,
            task_ids=[str(journey.summary_refresh_task_id)],
            novel_id=str(consumer.novel_id),
            max_heartbeat_gap=0,
        )
        contract = active.get(str(journey.summary_refresh_task_id))
        if contract and contract.status in {"pending", "running"}:
            raise ConflictError("已有摘要整理正在进行", code="SUMMARY_REFRESH_ACTIVE")
    snapshot = await build_project_llm_execution_snapshot(db, str(consumer.novel_id))
    if _fingerprint(snapshot) != preview["snapshot_fingerprint"]:
        raise ConflictError(
            "模型或费用配置已变化，请重新准备", code="SUMMARY_PREVIEW_STALE"
        )
    task = await enqueue_operation_task(
        db,
        operation_id=operation_id,
        task_type=SUMMARY_TASK_TYPE,
        novel_id=str(consumer.novel_id),
        request_payload=payload,
        meta={
            "novel_id": str(consumer.novel_id),
            "journey_id": str(journey.id),
            "path_hash": preview["selected_path_hash"],
            "selected_leaf_node_id": preview["selected_leaf_node_id"],
            "started_overview_epoch": preview["overview_epoch"],
            "author_project_id": str(args.author_project_id),
            "source_revision_id": preview["source_revision_id"],
            "source_fingerprint": preview["source_fingerprint"],
            "llm_execution_snapshot": snapshot,
        },
    )
    journey.summary_refresh_task_id = UUID(task.task_id)
    return {
        "type": "interaction_summary_refresh",
        "task_id": task.task_id,
        "status": task.status,
        "replayed": task.reused,
        "root_capability_id": SUMMARY_ROOT_CAPABILITY,
        "recovery_policy": "auto_requeue",
        "request_limit": 8,
    }


async def _summary_apply(db, novel_id, args, preview, *, context=None):
    if context is not None:
        raise ConflictError(
            (
                "摘要刷新仍使用 Interaction 自有预算根；"
                "请在旅程工作台单独核对资料与预算并确认。"
            ),
            code="ROOT_BUDGET_ADAPTER_UNAVAILABLE",
        )
    if not args.confirmed or not args.expected_preview_hash:
        raise ConflictError(
            "请单独确认这次可能计费的摘要整理", code="CONFIRMATION_REQUIRED"
        )
    operation_id = getattr(context, "operation_id", None) if context is not None else None
    operation_id = operation_id or args.operation_id
    if operation_id is not None:
        _author, consumer, _journey, _revision = await _bound_journey(
            db,
            novel_id,
            args,
            status=None,
            require_active_consumer=False,
        )
        request = _summary_task_payload(
            args.model_copy(update={"operation_id": str(operation_id)}),
            {"preview_hash": args.expected_preview_hash},
        )
        existing = await get_operation_task(
            db,
            operation_id=str(operation_id),
            task_type=SUMMARY_TASK_TYPE,
            novel_id=str(consumer.novel_id),
            request_payload=request,
        )
        if existing is not None:
            return {
                "type": "interaction_summary_refresh",
                "task_id": existing.task_id,
                "status": existing.status,
                "replayed": True,
                "root_capability_id": SUMMARY_ROOT_CAPABILITY,
                "recovery_policy": "auto_requeue",
                "request_limit": 8,
            }
    await _service._owned_journey(
        db,
        str(args.journey_id),
        status="active",
        for_update=True,
    )
    current = await _summary_preview(db, novel_id, args, context=context)
    if (preview is not None and current != preview) or (
        current["preview_hash"] != args.expected_preview_hash
    ):
        raise ConflictError(
            "路径、来源或模型快照已变化，请重新准备", code="SUMMARY_PREVIEW_STALE"
        )
    if not current["unknown_charge_stop_available"]:
        raise ConflictError(
            (
                "预算与资料已核对，但当前摘要运行根尚未提供 unknown charge 后的"
                "作者核对停点；本次没有排队。"
            ),
            code="ROOT_BUDGET_ADAPTER_UNAVAILABLE",
        )
    if operation_id is None:
        raise ConflictError(
            "缺少摘要刷新确认标识，请重新准备", code="OPERATION_ID_REQUIRED"
        )
    return await _submit_summary_task(db, args, current, operation_id=str(operation_id))


async def _summary_read_result(db, novel_id, args, *, context=None):
    operation_id = getattr(context, "operation_id", None) if context is not None else None
    operation_id = operation_id or args.operation_id
    if operation_id is None or not args.expected_preview_hash:
        raise ConflictError("缺少摘要刷新标识", code="OPERATION_ID_REQUIRED")
    _author, consumer, journey, _revision = await _bound_journey(
        db, novel_id, args, status=None, require_active_consumer=False
    )
    payload = _summary_task_payload(
        args.model_copy(update={"operation_id": operation_id}),
        {"preview_hash": args.expected_preview_hash},
    )
    task = await get_operation_task(
        db,
        operation_id=str(operation_id),
        task_type=SUMMARY_TASK_TYPE,
        novel_id=str(consumer.novel_id),
        request_payload=payload,
    )
    if task is None:
        return {"status": "not_submitted", "preview_only": True}
    lifecycle = (
        await list_task_lifecycle_contracts(
            db,
            task_ids=[task.task_id],
            novel_id=str(consumer.novel_id),
            max_heartbeat_gap=0,
        )
    ).get(task.task_id)
    return {
        "status": lifecycle.status if lifecycle else task.status,
        "task_id": task.task_id,
        "recovery_policy": lifecycle.recovery_policy if lifecycle else "auto_requeue",
        "available_actions": lifecycle.available_actions if lifecycle else [],
        "possible_charge": lifecycle.operation.possible_charge if lifecycle else True,
    }


def _meta(
    *,
    description,
    risk,
    fee,
    reversible,
    preconditions,
    produces,
    target,
    fields,
    transaction="single_transaction",
):
    return {
        "op_version": "1",
        "description": description,
        "risk_level": risk,
        "fee_category": fee,
        "reversibility": reversible,
        "preconditions": preconditions,
        "produces": produces,
        "target_type": target,
        "ai_available": True,
        "transaction_mode": transaction,
        "trace_rule": {
            "parameter_fields": fields,
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
        "permission": "read" if risk == "R0" else "confirm",
    }


OPERATIONS_SPEC = {
    "interaction.author.journeys.list": {
        "label": "读取本作品关联的 RP 旅程",
        "schema": ListAuthorJourneysArgs,
        "prepare": _journey_list_prepare,
        **_meta(
            description=(
                "只读取当前作者作品明确关联的 RP 旅程；不会把 RP 消费项目当作作者项目。"
            ),
            risk="R0",
            fee="free",
            reversible="read_only",
            preconditions=("当前账户拥有作者作品", "旅程来源修订显式指向当前作品"),
            produces=("interaction_journey_list",),
            target="interaction_journey_list",
            fields=("author_project_id", "status"),
        ),
    },
    "interaction.author.journey.settings": {
        "label": "调整 RP 旅程显示设置",
        "schema": UpdateJourneySettingsArgs,
        "prepare": _settings_prepare,
        "apply": _settings_apply,
        **_meta(
            description="只调整可选行动提示；不更改持续续写、联网、凭据或角色团队能力。",
            risk="R2",
            fee="free",
            reversible="journey_settings_reeditable",
            preconditions=(
                "当前账户拥有当前作者作品",
                "旅程来源修订指向当前作品",
                "选择版本未变化",
            ),
            produces=("interaction_journey_settings",),
            target="interaction_journey",
            fields=(
                "author_project_id",
                "journey_id",
                "expected_selection_epoch",
                "expected_action_options_enabled",
                "action_options_enabled",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "interaction.author.journey.rename": {
        "label": "重命名 RP 旅程",
        "schema": RenameJourneyArgs,
        "prepare": _rename_prepare,
        "apply": _rename_apply,
        **_meta(
            description=(
                "重命名当前作品资料所关联的 RP 旅程；不改动来源、历史或故事内容。"
            ),
            risk="R2",
            fee="free",
            reversible="journey_title_reeditable",
            preconditions=(
                "当前账户拥有当前作者作品",
                "旅程来源修订指向当前作品",
                "当前标题与预览一致",
            ),
            produces=("interaction_journey_title",),
            target="interaction_journey",
            fields=(
                "author_project_id",
                "journey_id",
                "expected_title",
                "title",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "interaction.author.journey.archive": {
        "label": "归档 RP 旅程",
        "schema": JourneyStateArgs,
        "prepare": _state_prepare,
        "apply": _archive_apply,
        **_meta(
            description="归档当前作品关联旅程，可从历史旅程恢复；不删除长期历史。",
            risk="R2",
            fee="free",
            reversible="interaction_journey_restore",
            preconditions=("旅程当前为 active", "旅程来源修订指向当前作品"),
            produces=("interaction_journey_archive",),
            target="interaction_journey",
            fields=(
                "author_project_id",
                "journey_id",
                "expected_status",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "interaction.author.journey.restore": {
        "label": "恢复归档 RP 旅程",
        "schema": JourneyStateArgs,
        "prepare": _state_prepare,
        "apply": _restore_apply,
        **_meta(
            description="恢复当前作品关联的归档旅程，不改写历史或来源修订。",
            risk="R2",
            fee="free",
            reversible="journey_rearchivable",
            preconditions=("旅程当前为 archived", "旅程来源修订指向当前作品"),
            produces=("interaction_journey_restore",),
            target="interaction_journey",
            fields=(
                "author_project_id",
                "journey_id",
                "expected_status",
                "expected_preview_hash",
                "confirmed",
            ),
        ),
    },
    "interaction.summary.refresh": {
        "label": "整理 RP 旅程摘要",
        "schema": SummaryRefreshArgs,
        "prepare": _summary_preview,
        "apply": _summary_apply,
        "read_result": _summary_read_result,
        **_meta(
            description=(
                "对当前选定 RP 路径中的可压缩旧段进行模型整理；"
                "单独确认后按 Interaction 根预算入队。"
            ),
            risk="R4",
            fee="possible_model_charge",
            reversible="derived_summary_revision_history",
            preconditions=(
                "来源修订指向当前作者作品",
                "当前路径和来源指纹未变化",
                "Interaction 摘要 TaskRegistry 根可用",
                "作者单独确认",
            ),
            produces=(
                "interaction_summary_task_receipt",
                "interaction_overview_revision",
            ),
            target="interaction_journey",
            fields=(
                "author_project_id",
                "journey_id",
                "operation_id",
                "expected_preview_hash",
                "confirmed",
            ),
            transaction="multi_stage",
        ),
    },
}
