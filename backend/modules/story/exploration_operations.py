"""Pure operation catalog entries for author-authorized multi-scale exploration.

OPERATIONS_SPEC（op_version "1"）：预览、比较、历史和移交是 R0 只读，
目标资料确认 R1；start/detail/revise 是 R2、possible_model_charge、multi_stage。
read 类操作必须是 R0 且 apply=None；非 read 必须有 apply（装配件校验）。
history/compare 操作不挂执行 gate（关闭后仍可读）；其余 prepare/apply 挂 gate。

M4-B goal runs 接入：start/detail/revise 声明 read_result 并支持受控内联
执行（goal 冻结的稳定 operation_id + 父任务绑定）。实际 task 类型在 apply
时按尺度（start）或父结果所在链（detail/revise）决定；goal_runs 侧映射只
声明候选集合（progression/scene 两个任务同注册根能力 story.exploration）。
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select

from core.errors import ValidationError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.facade import get_completed_task_payload
from infrastructure.tasks.models import AsyncTask
from modules.evidence import facade as evidence_facade
from modules.project.facade import require_active_project
from modules.story import exploration_api
from modules.story.exploration_api import ExplorationStartApiRequest
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_feature import require_story_exploration_enabled
from modules.story.exploration_recommend import recommend_exploration_scale
from modules.story.exploration_schemas import (
    ExplorationBudgetPreview,
    ExplorationCompareRequest,
    ExplorationConfirmationPreviewRequest,
    ExplorationConfirmationRequest,
    ExplorationDetailOperationRequest,
    ExplorationHandoffOperationRequest,
    ExplorationHistoryOperationRequest,
    ExplorationPreviewOperationRequest,
    ExplorationReviseOperationRequest,
    ExplorationStartOperationRequest,
    check_revision_target,
    validate_start_dump,
)
from modules.story.exploration_service import unpack_exploration_output
from modules.story.models import StorySceneDirectorRoot
from modules.story.outline_state.models import Scene
from modules.story.world_progression_models import StoryWorldProgressionRoot

EXPLORATION_TARGET_TYPE = "story_exploration"
AUTHOR_EDIT_KIND = "story.exploration.author_edit"

# 目标运行（goal runs）接入：start/detail/revise 的实际 task 类型在 apply 时
# 按尺度或父结果所在链决定（沙盘/事件 → progression 任务；一句对白 → scene
# 任务）。goal_runs 侧的映射只声明候选集合，实际绑定以 apply 返回的领域回执
# 为准；此处保持与 exploration_api 的派生一致。
_PROGRESSION_TASK = "story_exploration_progression_task"
_SCENE_TASK = "story_exploration_scene_task"
_TASK_TYPE_BY_SCALE = {
    "sandbox": _PROGRESSION_TASK,
    "event": _PROGRESSION_TASK,
    "scene_line": _SCENE_TASK,
}


def _trace(model: type) -> dict:
    return {
        "parameter_fields": tuple(model.model_fields),
        "mode": "per_call",
        "parameter_policy": "schema_safe",
    }


def _goal_execution(context) -> bool:
    """该次 apply 是否运行在目标运行的受控内联执行中。"""
    internal = getattr(context, "internal_meta", None) or {}
    return (
        internal.get("_execution_mode") == "inline_only"
        and bool(getattr(context, "operation_id", None))
        and bool(internal.get("_parent_task_id"))
    )


def _task_type_for_scale(scale: str) -> str:
    task_type = _TASK_TYPE_BY_SCALE.get(str(scale or ""))
    if task_type is None:
        raise ValueError(f"不支持的探索尺度：{scale}")
    return task_type


async def _task_type_for_result(db, novel_id: str, result_id: str) -> str:
    _row, chain, _root = await exploration_api._locate_exploration_result(
        db, novel_id=novel_id, result_id=str(result_id)
    )
    return _PROGRESSION_TASK if chain == "progression" else _SCENE_TASK


def _goal_receipt(context, receipt: dict, *, task_type: str) -> dict:
    """目标运行冻结的稳定任务回执：task_id 即目标冻结的稳定操作标识。"""
    return {
        "task_id": str(receipt.get("task_id")),
        "task_type": task_type,
        "status": str(receipt.get("status") or "pending"),
        "operation_id": str(context.operation_id),
        "root_id": str(receipt.get("root_id") or ""),
        "branch_id": str(receipt.get("branch_id") or ""),
    }


def _metadata(
    *,
    description: str,
    risk: str,
    fee: str,
    produces: tuple[str, ...],
    preconditions: tuple[str, ...],
    transaction: str = "single_transaction",
    reversibility: str = "history_restore",
):
    return {
        "op_version": "1",
        "description": description,
        "risk_level": risk,
        "fee_category": fee,
        "reversibility": reversibility,
        "preconditions": preconditions,
        "produces": produces,
        "target_type": EXPLORATION_TARGET_TYPE,
        "ai_available": True,
        "transaction_mode": transaction,
    }


def _require_project(novel_id: str, args) -> None:
    if str(args.novel_id) != str(novel_id):
        raise PermissionError("操作作品与当前作者工作范围不一致")


def _require_gate() -> None:
    require_story_exploration_enabled()


# ---------------------------------------------------------------------------
# prepare / apply
# ---------------------------------------------------------------------------


def _advisory_budget_payload(
    *,
    novel_id: str,
    scale: str,
    focus: str,
    multi_targets: list[str] | None = None,
) -> dict:
    """未冻结起点时的名义预算（请求次数为硬约定，Token 按焦点长度粗估）。"""
    chars = len(focus)
    request_count = len(multi_targets) if multi_targets else 1
    tokens_min = max(1, chars // 4) + 100 * request_count
    tokens_max = max(tokens_min, chars // 2 + 400 * request_count)
    identity: dict = {
        "novel_id": str(novel_id),
        "scale": scale,
        "focus_chars": chars,
    }
    if multi_targets:
        identity["multi_targets"] = [str(item) for item in multi_targets]
    return ExplorationBudgetPreview(
        requests_min=request_count * 3,
        requests_max=request_count * 5,
        follow_up_max_requests=5,
        tokens_min=tokens_min * 3,
        tokens_max=(tokens_max + 4000) * 5,
        preview_hash=content_hash(identity),
    ).model_dump(mode="json")


async def _prepare_preview(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    project_has_content = (
        await db.scalar(select(Scene.id).where(Scene.novel_id == UUID(novel_id)).limit(1))
        is not None
    )
    recommended, reason = recommend_exploration_scale(
        args.question or "",
        args.task_hint or "",
        has_selection=bool(args.has_selection),
        project_has_content=project_has_content,
    )
    effective_scale = args.scale or recommended
    reason = reason if args.scale is None else "按你指定的尺度预览"
    if (args.multi_targets or args.diagnostic) and effective_scale != "scene_line":
        raise ValueError("multi_targets/diagnostic 仅支持场景一句对白尺度")
    return {
        "recommended_scale": effective_scale,
        "recommendation_reason": reason,
        "focus_hint": args.focus,
        "budget": _advisory_budget_payload(
            novel_id=novel_id,
            scale=effective_scale,
            focus=args.focus,
            multi_targets=args.multi_targets,
        ),
        "requires_confirmation": True,
        "confirmation_summary": (
            "开始前需要确认本次资料范围；临时起点允许空资料集确认。"
        ),
        "recommendation": {
            "type": "story_exploration_recommendation",
            "scale": effective_scale,
            "reason": reason,
            "focus_hint": args.focus,
            "question": args.question,
        },
    }


async def _prepare_start(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    try:
        start = validate_start_dump(dict(args.start))
        exploration_api._resolve_scene_target(args, start=start)
    except ValueError as error:
        raise ValidationError(str(error)) from error
    intent = getattr(getattr(context, "work", None), "exploration_intent", None)
    if intent is not None and (
        args.scale != intent.scale
        or args.focus != intent.focus
        or (intent.question and getattr(start, "question", "") != intent.question)
    ):
        raise ValidationError(
            "探索参数与作者在推荐卡中选择的任务不一致，请沿用指定问题、尺度和焦点"
        )
    confirmation = await evidence_facade.require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=args.action,
        confirmation_id=args.context_confirmation_id,
    )
    options = dict(confirmation.compile_options or {})
    consistent = (
        options.get("exploration_start") == start.model_dump(mode="json")
        and str(options.get("exploration_scale") or "") == args.scale
        and str(options.get("exploration_focus") or "") == str(args.focus or "")
    )
    if not consistent:
        raise ValidationError("资料确认的探索起点、尺度或焦点不一致，请重新确认")
    budget = preview_exploration_budget(
        novel_id=novel_id,
        scale=args.scale,
        start=start,
        focus=args.focus,
        event_mode_hint=args.event_mode_hint,
        multi_targets=args.multi_targets,
        diagnostic_question=(
            args.diagnostic.question if args.diagnostic is not None else None
        ),
        full_rehearsal=args.full_rehearsal,
    )
    if budget.preview_hash != args.budget_preview_hash:
        raise ValidationError("起点或焦点已变化，请重新预览预算")
    return {
        "confirmed": consistent,
        "preview_hash": budget.preview_hash,
        "preview_hash_matches": budget.preview_hash == args.budget_preview_hash,
        "requests_max": budget.requests_max,
        "tokens_max": budget.tokens_max,
        "effect": "发起一次有界独立探索任务；结果只进探索历史，不改正史",
    }


async def _apply_start(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)

    goal_mode = _goal_execution(context)
    payload = {
        "novel_id": args.novel_id,
        "scale": args.scale,
        "start": args.start,
        "focus": args.focus,
        "action": args.action,
        "context_confirmation_id": args.context_confirmation_id,
        "budget_preview_hash": args.budget_preview_hash,
        "operation_id": str(
            context.operation_id if goal_mode else UUID(str(args.operation_id))
        ),
        "time_budget_seconds": args.time_budget_seconds,
    }
    if args.target_ref:
        payload["target_ref"] = args.target_ref
    if args.event_mode_hint:
        payload["event_mode_hint"] = args.event_mode_hint
    if args.multi_targets:
        payload["multi_targets"] = args.multi_targets
    if args.diagnostic is not None:
        payload["diagnostic"] = args.diagnostic.model_dump(mode="json")
    if args.full_rehearsal is not None:
        payload["full_rehearsal"] = args.full_rehearsal.model_dump(mode="json")
    receipt = await exploration_api.start_exploration_task(
        db,
        data=ExplorationStartApiRequest.model_validate(payload),
        **({"internal_meta": context.internal_meta} if goal_mode else {}),
    )
    if not goal_mode:
        return {
            **receipt,
            "task_type": _task_type_for_scale(args.scale),
            "target_type": EXPLORATION_TARGET_TYPE,
            "scale": args.scale,
        }
    task_type = _task_type_for_scale(args.scale)
    bound = _goal_receipt(context, receipt, task_type=task_type)
    return bound


async def _prepare_detail(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    row, _chain, _root = await exploration_api._locate_exploration_result(
        db, novel_id=novel_id, result_id=str(args.result_id)
    )
    return {
        "result_id": str(row.id),
        "effect": (
            "对当前结果做一次“说详细点”，"
            "同根按生成条目追加最多 5 次模型请求（含导演与审查）"
        ),
    }


async def _apply_detail(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    goal_mode = _goal_execution(context)
    receipt = await exploration_api.submit_exploration_follow_up(
        db,
        novel_id=novel_id,
        result_id=str(args.result_id),
        mode="detail",
        operation_id=str(
            context.operation_id if goal_mode else UUID(str(args.operation_id))
        ),
        focus=args.focus,
        **({"internal_meta": context.internal_meta} if goal_mode else {}),
    )
    if not goal_mode:
        return {
            **receipt,
            "task_type": await _task_type_for_result(db, novel_id, str(args.result_id)),
            "target_type": EXPLORATION_TARGET_TYPE,
        }
    task_type = await _task_type_for_result(db, novel_id, str(args.result_id))
    bound = _goal_receipt(context, receipt, task_type=task_type)
    return bound


async def _prepare_revise(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    row, _chain, _root = await exploration_api._locate_exploration_result(
        db, novel_id=novel_id, result_id=str(args.result_id)
    )
    envelope = unpack_exploration_output(row)
    if envelope is None:
        raise ValueError("所选记录不是探索结果")
    if envelope.output_kind == AUTHOR_EDIT_KIND:
        from modules.story.exploration_schemas import ExplorationOutputEnvelope

        envelope = ExplorationOutputEnvelope(
            output_kind=envelope.payload.base_output_kind,
            payload=envelope.payload.edited_payload,
        )
    try:
        check_revision_target(
            envelope.payload.model_dump(mode="json"),
            args.item_path,
            args.item_text,
            envelope.output_kind,
        )
    except ValueError as error:
        raise ValueError(str(error)) from error
    return {
        "result_id": str(row.id),
        "locked_item_path": args.item_path,
        "effect": "只重生成选中条目，其余内容服务端原样保留；同根追加最多 5 次模型请求",
    }


async def _apply_revise(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    goal_mode = _goal_execution(context)
    receipt = await exploration_api.submit_exploration_follow_up(
        db,
        novel_id=novel_id,
        result_id=str(args.result_id),
        mode="revise",
        operation_id=str(
            context.operation_id if goal_mode else UUID(str(args.operation_id))
        ),
        instruction=args.instruction,
        item_path=args.item_path,
        item_text=args.item_text,
        bridge_target=args.bridge_target,
        **({"internal_meta": context.internal_meta} if goal_mode else {}),
    )
    if not goal_mode:
        return {
            **receipt,
            "task_type": await _task_type_for_result(db, novel_id, str(args.result_id)),
            "target_type": EXPLORATION_TARGET_TYPE,
        }
    task_type = await _task_type_for_result(db, novel_id, str(args.result_id))
    bound = _goal_receipt(context, receipt, task_type=task_type)
    return bound


# ---------------------------------------------------------------------------
# goal runs 回执读取：完成=applied；失败且根已失败=not_applied；其余未知
# ---------------------------------------------------------------------------


async def _cancelled_before_first_claim(
    db, *, novel_id: str, task_id: str, task_type: str
) -> bool:
    """任务在首次领取前已取消：服务端确认没有执行任何领域操作。"""
    try:
        task_uuid = UUID(task_id)
    except (TypeError, ValueError):
        return False
    task = await db.scalar(
        select(AsyncTask).where(
            AsyncTask.id == task_uuid,
            AsyncTask.task_type == task_type,
            AsyncTask.novel_id == UUID(novel_id),
        )
    )
    return bool(
        task is not None
        and task.status == "cancelled"
        and type(task.attempt) is int
        and task.attempt == 0
        and task.started_at is None
        and task.result in (None, {})
        and task.error_message is None
    )


async def _exploration_failed_without_result(db, novel_id: str, root_id: str) -> bool:
    """任务失败且探索根已按失败收尾：本操作没有写出任何新结果。

    worker 的失败路径先提交 root/branch 的 failed 状态再抛出；结果行只在成功
    尾部写入。因此 root.status == "failed" 证明本次操作没有产生新探索结果。
    """
    from sqlalchemy import select

    try:
        root_uuid = UUID(root_id)
    except (TypeError, ValueError):
        return False
    progression_root = await db.scalar(
        select(StoryWorldProgressionRoot).where(
            StoryWorldProgressionRoot.novel_id == UUID(novel_id),
            StoryWorldProgressionRoot.id == root_uuid,
        )
    )
    if progression_root is not None:
        return str(progression_root.status or "") == "failed"
    scene_root = await db.scalar(
        select(StorySceneDirectorRoot).where(
            StorySceneDirectorRoot.novel_id == UUID(novel_id),
            StorySceneDirectorRoot.id == root_uuid,
        )
    )
    if scene_root is not None:
        return str(scene_root.status or "") == "failed"
    return False


async def _read_exploration_task_result(db, novel_id, reference):

    task_type = str(reference.get("task_type") or "")
    root_id = str(reference.get("root_id") or "")
    task = await get_completed_task_payload(
        db,
        novel_id=novel_id,
        task_id=str(reference.get("task_id")),
        task_type=task_type,
        include_cancelled=True,
    )

    if task is None:
        cancelled_proof = await _cancelled_before_first_claim(
            db,
            novel_id=novel_id,
            task_id=str(reference.get("task_id")),
            task_type=task_type,
        )
        if cancelled_proof:
            return {
                "status": "not_applied",
                "task_type": task_type,
                "root_id": root_id,
                "proof": {"kind": "task_cancelled_before_first_claim"},
            }
        if root_id and await _exploration_failed_without_result(db, novel_id, root_id):
            return {
                "status": "not_applied",
                "task_type": task_type,
                "root_id": root_id,
                "proof": {"kind": "exploration_root_failed_without_result"},
            }
        return {
            "status": "incomplete",
            "task_type": task_type,
            "omissions": ["探索任务尚未完成；请查看原任务进度"],
        }
    result = dict(task.result or {})
    status = str(result.get("status") or "")
    if status == "completed":
        return {
            "status": "completed",
            "task_type": task_type,
            "root_id": str(result.get("root_id") or root_id),
            "branch_id": str(result.get("branch_id") or ""),
            "result_id": str(result.get("result_id") or ""),
            "output_kind": str(result.get("output_kind") or ""),
            "payload": result.get("payload"),
            "domain_reference": {
                "type": "story_exploration_result",
                "task_id": str(reference.get("task_id")),
                "root_id": str(result.get("root_id") or root_id),
                "branch_id": str(result.get("branch_id") or ""),
                "result_id": str(result.get("result_id") or ""),
                "output_kind": str(result.get("output_kind") or ""),
                "scale": {
                    "story.exploration.sandbox": "sandbox",
                    "story.exploration.event": "event",
                }.get(result.get("output_kind"), "scene_line"),
                "payload": result.get("payload"),
            },
        }
    if status in {"paused_budget", "paused_unknown"}:
        return {
            "status": "incomplete",
            "task_type": task_type,
            "root_id": str(result.get("root_id") or root_id),
            "budget_stop": str(result.get("budget_stop") or status),
            "needs_author_resume": True,
            "omissions": [
                "探索任务在预算或未知结果处暂停；请先在原工作台核对，目标不会重发任务"
            ],
        }
    return {
        "status": "incomplete",
        "task_type": task_type,
        "root_id": root_id,
        "omissions": ["原领域回执没有明确证明已完成或未应用"],
    }


async def _read_start_result(db, novel_id, reference):
    return await _read_exploration_task_result(db, novel_id, reference)


async def _read_detail_result(db, novel_id, reference):
    return await _read_exploration_task_result(db, novel_id, reference)


async def _read_revise_result(db, novel_id, reference):
    return await _read_exploration_task_result(db, novel_id, reference)


async def _prepare_compare(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)

    return await exploration_api.compare_exploration(
        db,
        data=ExplorationCompareRequest.model_validate(args.model_dump(mode="json")),
    )


async def _prepare_history(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)

    return await exploration_api.exploration_history(
        db,
        novel_id=novel_id,
        root_id=args.root_id,
        scale=args.scale,
        limit=args.limit,
        offset=args.offset,
    )


async def _prepare_handoff(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    return await exploration_api.handoff_exploration_result(
        db,
        result_id=args.result_id,
        data=exploration_api.ExplorationHandoffApiRequest(
            **args.model_dump(exclude={"result_id"}),
            selector="assistant",
            operation_id=uuid4(),
        ),
    )


async def _prepare_confirmation_preview(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    preview = await exploration_api.preview_confirmation(db, args)
    start = await exploration_api._effective_request_start(db, args)
    budget = preview_exploration_budget(
        novel_id=novel_id,
        scale=args.scale,
        start=start,
        focus=args.focus,
        event_mode_hint=args.event_mode_hint,
        multi_targets=args.multi_targets,
        diagnostic_question=args.diagnostic.question if args.diagnostic else None,
        full_rehearsal=args.full_rehearsal,
    )
    return {**preview, "budget": budget.model_dump(mode="json")}


async def _prepare_confirmation(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    preview = await exploration_api.preview_confirmation(db, args)
    if preview["context_fingerprint"] != args.expected_context_fingerprint:
        raise ValueError("目标资料预览已变化，请重新查证后确认")
    return preview


async def _apply_confirmation(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    return await exploration_api.confirm_exploration(db, args)


OPERATIONS_SPEC = {
    "story.exploration.handoff": {
        "label": "按所选结果派生跨尺度起点",
        "schema": ExplorationHandoffOperationRequest,
        "prepare": _prepare_handoff,
        "apply": None,
        "permission": "read",
        **_metadata(
            description=(
                "只读取所选条目并保留条件、未知和知识边界；必须记录移交理由。"
                "返回 derived_start（对象），后续目标尺度 confirmation_preview、confirm、"
                "start 的 start 均引用此字段，不是 start 字段；新尺度必须重新确认资料。"
                "result_id 引用已完成 start/detail/revise 的顶层 result_id。"
            ),
            risk="R0",
            fee="free",
            produces=("exploration_derived_start",),
            preconditions=("当前作者拥有来源探索",),
            reversibility="read_only",
        ),
        "trace_rule": _trace(ExplorationHandoffOperationRequest),
    },
    "story.exploration.confirmation_preview": {
        "label": "预览目标探索资料",
        "schema": ExplorationConfirmationPreviewRequest,
        "prepare": _prepare_confirmation_preview,
        "apply": None,
        "permission": "read",
        **_metadata(
            description=(
                "读取目标起点、尺度与焦点绑定的资料指纹；不调用模型。"
                "返回 context_fingerprint（字符串）及 budget.preview_hash（字符串）；"
                "confirm.expected_context_fingerprint 引用前者，start.budget_preview_ha"
                "sh 引用后者。"
                "同次 preview、confirm、start 的 novel_id/scale/start/focus/action 必须"
                "一致；"
                "首次 start 按本操作的起点 schema 构造，"
                "跨尺度 start 引用 handoff.derived_start。"
            ),
            risk="R0",
            fee="free",
            produces=("exploration_context_preview",),
            preconditions=("当前作者可访问目标作品",),
            reversibility="read_only",
        ),
        "trace_rule": _trace(ExplorationConfirmationPreviewRequest),
    },
    "story.exploration.confirm": {
        "label": "确认目标探索资料",
        "schema": ExplorationConfirmationRequest,
        "prepare": _prepare_confirmation,
        "apply": _apply_confirmation,
        "permission": "confirm",
        **_metadata(
            description=(
                "重验目标资料预览后冻结确认；目标运行仅在作者批准的计划与范围内执行。"
                "expected_context_fingerprint 引用 confirmation_preview 的 context_fing"
                "erprint，"
                "novel_id/scale/start/focus/action 原样复用同次预览。"
                "返回 confirmation_id（字符串），供 start.context_confirmation_id 引用；"
                "不是 context_confirmation_id 字段。"
            ),
            risk="R1",
            fee="free",
            produces=("exploration_context_confirmation",),
            preconditions=("目标预览指纹仍匹配",),
            reversibility="discard_preview",
        ),
        "trace_rule": _trace(ExplorationConfirmationRequest),
    },
    "story.exploration.preview": {
        "label": "预览独立探索推荐与预算",
        "schema": ExplorationPreviewOperationRequest,
        "prepare": _prepare_preview,
        "apply": None,
        "permission": "read",
        **_metadata(
            description=(
                "按作者问题确定性推荐观察尺度（沙盘/事件/场景对白），给出请求"
                "与 Token 预算区间和所需确认范围；不请求模型。"
                "返回 recommended_scale、recommendation 与 budget；这里不接收起点，"
                "budget.preview_hash 仅为名义预算，不可传给 start。"
                "要启动须按输入 schema 构造起点，再调用 confirmation_preview 获取绑定预"
                "算。"
            ),
            risk="R0",
            fee="free",
            produces=("story_exploration_recommendation",),
            preconditions=("当前作者可访问所选作品",),
            reversibility="discard_preview",
        ),
        "trace_rule": _trace(ExplorationPreviewOperationRequest),
    },
    "story.exploration.start": {
        "label": "发起独立探索任务",
        "schema": ExplorationStartOperationRequest,
        "prepare": _prepare_start,
        "apply": _apply_start,
        "read_result": _read_start_result,
        "permission": "confirm",
        **_metadata(
            description=(
                "在已确认资料范围内发起一次有界探索任务：沙盘影响链、事件诊断/"
                "补桥、一句场景对白，或对临时起点显式展开的完整排演"
                "（full_rehearsal，按 (目标数+1)×轮次 分开计量）；结果只进探索"
                "历史，不写正史。"
                "场景单目标对白 target_ref 在多个候选时必须显式选择，"
                "scene_anchor 必须填正式角色 entity_id；唯一候选可自动确定。"
                "target_ref 与 multi_targets、diagnostic、full_rehearsal 互斥；"
                "其他尺度不得填写，准备阶段即校验目标。"
                "novel_id/scale/start/focus/action 复用同次 confirmation_preview/confir"
                "m，"
                "context_confirmation_id 引用 confirm.confirmation_id，"
                "budget_preview_hash 引用 confirmation_preview.budget.preview_hash。"
                "Goal 完成步骤的结果来自 read_result，顶层返回 result_id、root_id、bran"
                "ch_id、"
                "output_kind、payload；后续引用 result_id，不要嵌套 result 或 task。"
                "参数 operation_id 是非空调用标记；Goal 实际执行 ID 由服务端按 run、步"
                "骤、"
                "参数指纹生成 UUID5，无需模型生成 UUID；步骤 operation_id 仍须为目录操"
                "作 ID。"
            ),
            risk="R2",
            fee="possible_model_charge",
            produces=("story_exploration_task",),
            preconditions=(
                "作者确认本次探索资料范围（临时起点允许空资料集）",
                "预算预览指纹仍匹配",
            ),
            transaction="multi_stage",
            reversibility="history_restore",
        ),
        "trace_rule": _trace(ExplorationStartOperationRequest),
    },
    "story.exploration.detail": {
        "label": "对探索结果说详细点",
        "schema": ExplorationDetailOperationRequest,
        "prepare": _prepare_detail,
        "apply": _apply_detail,
        "read_result": _read_detail_result,
        "permission": "confirm",
        **_metadata(
            description=(
                "绑定当前探索结果追加一次有界生成；不扩大尺度、资料或联网范围，"
                "同根按生成条目追加最多 5 次模型请求（含导演与审查）。"
                "result_id 引用前序 start/detail/revise 完成结果的顶层 result_id；"
                "本步骤完成同样返回顶层 result_id、root_id、branch_id、output_kind、pay"
                "load。"
                "参数 operation_id 是非空调用标记，Goal 实际执行 ID 由服务端生成 UUID5。"
            ),
            risk="R2",
            fee="possible_model_charge",
            produces=("story_exploration_task",),
            preconditions=(
                "所选结果是分支最新探索结果",
                "根账本可恢复且无未知用量",
            ),
            transaction="multi_stage",
            reversibility="history_restore",
        ),
        "trace_rule": _trace(ExplorationDetailOperationRequest),
    },
    "story.exploration.revise": {
        "label": "局部修订探索结果",
        "schema": ExplorationReviseOperationRequest,
        "prepare": _prepare_revise,
        "apply": _apply_revise,
        "read_result": _read_revise_result,
        "permission": "confirm",
        **_metadata(
            description=(
                "按条目路径选择父结果中的一个条目（含多目标、空间与排演）"
                "重生成，item_text 与父内容比对防漂移；其余内容服务端原样保留，"
                "新结果行指向父行。"
                "result_id 引用前序 start/detail/revise 完成结果的顶层 result_id；"
                "本步骤完成同样返回顶层 result_id、root_id、branch_id、output_kind、pay"
                "load。"
                "参数 operation_id 是非空调用标记，Goal 实际执行 ID 由服务端生成 UUID5。"
            ),
            risk="R2",
            fee="possible_model_charge",
            produces=("story_exploration_task",),
            preconditions=(
                "item_path 在父结果可修订条目中且 item_text 与其内容一致",
                "所选结果是分支最新探索结果",
            ),
            transaction="multi_stage",
            reversibility="history_restore",
        ),
        "trace_rule": _trace(ExplorationReviseOperationRequest),
    },
    "story.exploration.compare": {
        "label": "比较同起点探索结果",
        "schema": ExplorationCompareRequest,
        "prepare": _prepare_compare,
        "apply": None,
        "permission": "read",
        **_metadata(
            description="读取同一探索起点的两个结果做并排比较；起点不同失败关闭。",
            risk="R0",
            fee="free",
            produces=("story_exploration_compare",),
            preconditions=("两个结果属于当前作品且起点指纹一致",),
            reversibility="read_only",
        ),
        "trace_rule": _trace(ExplorationCompareRequest),
    },
    "story.exploration.history": {
        "label": "查看独立探索历史",
        "schema": ExplorationHistoryOperationRequest,
        "prepare": _prepare_history,
        "apply": None,
        "permission": "read",
        **_metadata(
            description=(
                "按作品列出探索结果（含临时起点与场景锚点）；gate 关闭后仍可读。"
            ),
            risk="R0",
            fee="free",
            produces=("story_exploration_history",),
            preconditions=("当前作者可访问所选作品",),
            reversibility="read_only",
        ),
        "trace_rule": _trace(ExplorationHistoryOperationRequest),
    },
}
