"""Pure operation catalog entries for author-authorized multi-scale exploration.

P0 §6：六项 OPERATIONS_SPEC（op_version "1"）。preview/compare/history 是
R0 只读；start/detail/revise 是 confirm R2、possible_model_charge、multi_stage。
read 类操作必须是 R0 且 apply=None；非 read 必须有 apply（装配件校验）。
history/compare 操作不挂执行 gate（关闭后仍可读）；其余 prepare/apply 挂 gate。
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from modules.project.facade import require_active_project
from modules.story.exploration_recommend import recommend_exploration_scale
from modules.story.exploration_schemas import (
    EVENT_HINT_LITERAL,
    MULTI_TARGETS_MAX,
    MULTI_TARGETS_MIN,
    ExplorationCompareRequest,
    ExplorationScale,
    FullRehearsalRequest,
    SceneSpatialDiagnosticRequest,
)

EXPLORATION_TARGET_TYPE = "story_exploration"
AUTHOR_EDIT_KIND = "story.exploration.author_edit"


def _trace(model: type) -> dict:
    return {
        "parameter_fields": tuple(model.model_fields),
        "mode": "per_call",
        "parameter_policy": "schema_safe",
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
    from modules.story.exploration_feature import require_story_exploration_enabled

    require_story_exploration_enabled()


class ExplorationPreviewOperationRequest(BaseModel):
    """确定性推荐 + 预算/确认范围预览；无模型调用。

    ``multi_targets``（M2 场景多目标）仅场景尺度接受：名义预算 = 目标数。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    question: str | None = Field(default=None, max_length=4000)
    scale: ExplorationScale | None = None
    focus: str = Field(default="", max_length=2000)
    task_hint: str | None = Field(default=None, max_length=120)
    has_selection: bool = False
    multi_targets: list[str] | None = Field(
        default=None,
        min_length=MULTI_TARGETS_MIN,
        max_length=MULTI_TARGETS_MAX,
    )
    diagnostic: SceneSpatialDiagnosticRequest | None = None


class ExplorationStartOperationRequest(BaseModel):
    """发起探索任务；与 REST /start 同一执行路径（幂等 operation_id）。

    ``event_mode_hint``（M2）仅事件尺度接受：info_gap → 信息差诊断，
    goal → 导向路径；与 action 的配对校验由 apply 侧契约模型完成。
    ``multi_targets`` / ``diagnostic``（M2）仅场景尺度接受，二者互斥。
    ``full_rehearsal``（M3-B）仅临时起点 + 场景尺度接受，与前两者互斥；
    资格校验（404/409）由 apply 侧 start 执行路径完成。
    """

    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scale: ExplorationScale
    start: dict
    focus: str = Field(default="", max_length=2000)
    action: str = Field(min_length=1, max_length=128)
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    budget_preview_hash: str = Field(pattern="^[a-f0-9]{64}$")
    operation_id: str = Field(min_length=1, max_length=64)
    time_budget_seconds: int = Field(default=3600, ge=1, le=6 * 3600)
    target_ref: str | None = Field(default=None, min_length=1, max_length=64)
    event_mode_hint: EVENT_HINT_LITERAL | None = None
    multi_targets: list[str] | None = Field(
        default=None,
        min_length=MULTI_TARGETS_MIN,
        max_length=MULTI_TARGETS_MAX,
    )
    diagnostic: SceneSpatialDiagnosticRequest | None = None
    full_rehearsal: FullRehearsalRequest | None = None


class ExplorationDetailOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    result_id: str
    focus: str = Field(default="", max_length=2000)
    operation_id: str = Field(min_length=1, max_length=64)


class ExplorationReviseOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    result_id: str
    item_path: str = Field(min_length=1, max_length=120)
    item_text: str | None = Field(default=None, max_length=4000)
    instruction: str = Field(min_length=1, max_length=2000)
    bridge_target: str | None = Field(default=None, max_length=500)
    operation_id: str = Field(min_length=1, max_length=64)


class ExplorationHistoryOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    root_id: str | None = Field(default=None, max_length=64)
    scale: ExplorationScale | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


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
    from infrastructure.llm.collaboration import content_hash
    from modules.story.exploration_schemas import ExplorationBudgetPreview

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
        requests_min=request_count,
        requests_max=request_count,
        follow_up_max_requests=1,
        tokens_min=tokens_min,
        tokens_max=tokens_max,
        preview_hash=content_hash(identity),
    ).model_dump(mode="json")


async def _prepare_preview(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    from modules.story.outline_state.models import Scene

    project_has_content = (
        await db.scalar(
            select(Scene.id).where(Scene.novel_id == UUID(novel_id)).limit(1)
        )
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
        },
    }


async def _prepare_start(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    from modules.evidence.facade import require_fresh_confirmation
    from modules.story.exploration_api import validate_start_dump
    from modules.story.exploration_budget import preview_exploration_budget

    start = validate_start_dump(dict(args.start))
    confirmation = await require_fresh_confirmation(
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
    from modules.story.exploration_api import (
        ExplorationStartApiRequest,
        start_exploration_task,
    )

    payload = {
        "novel_id": args.novel_id,
        "scale": args.scale,
        "start": args.start,
        "focus": args.focus,
        "action": args.action,
        "context_confirmation_id": args.context_confirmation_id,
        "budget_preview_hash": args.budget_preview_hash,
        "operation_id": str(UUID(str(args.operation_id))),
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
    return await start_exploration_task(
        db, data=ExplorationStartApiRequest.model_validate(payload)
    )


async def _prepare_detail(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    from modules.story.exploration_api import _locate_exploration_result

    row, _chain, _root = await _locate_exploration_result(
        db, novel_id=novel_id, result_id=str(args.result_id)
    )
    return {
        "result_id": str(row.id),
        "effect": "对当前结果做一次“说详细点”，同根追加授权 1 次模型请求",
    }


async def _apply_detail(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    from modules.story.exploration_api import submit_exploration_follow_up

    return await submit_exploration_follow_up(
        db,
        novel_id=novel_id,
        result_id=str(args.result_id),
        mode="detail",
        operation_id=str(args.operation_id),
        focus=args.focus,
    )


async def _prepare_revise(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    from modules.story.exploration_api import _locate_exploration_result
    from modules.story.exploration_service import unpack_exploration_output
    from modules.story.exploration_tasks import check_revision_target

    row, _chain, _root = await _locate_exploration_result(
        db, novel_id=novel_id, result_id=str(args.result_id)
    )
    envelope = unpack_exploration_output(row)
    if envelope is None or envelope.output_kind == AUTHOR_EDIT_KIND:
        raise ValueError("作者编辑版本不能继续修订；请回到原始 AI 结果")
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
        "effect": "只重生成选中条目，其余内容服务端原样保留；同根追加授权 1 次",
    }


async def _apply_revise(db, novel_id, args, preview, *, context=None):
    _require_project(novel_id, args)
    _require_gate()
    await require_active_project(db, novel_id)
    from modules.story.exploration_api import submit_exploration_follow_up

    return await submit_exploration_follow_up(
        db,
        novel_id=novel_id,
        result_id=str(args.result_id),
        mode="revise",
        operation_id=str(args.operation_id),
        instruction=args.instruction,
        item_path=args.item_path,
        item_text=args.item_text,
        bridge_target=args.bridge_target,
    )


async def _prepare_compare(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    from modules.story.exploration_api import compare_exploration

    return await compare_exploration(
        db,
        data=ExplorationCompareRequest.model_validate(args.model_dump(mode="json")),
    )


async def _prepare_history(db, novel_id, args, *, context=None):
    _require_project(novel_id, args)
    await require_active_project(db, novel_id)
    from modules.story.exploration_api import exploration_history

    return await exploration_history(
        db,
        novel_id=novel_id,
        root_id=args.root_id,
        scale=args.scale,
        limit=args.limit,
        offset=args.offset,
    )


OPERATIONS_SPEC = {
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
        "permission": "confirm",
        **_metadata(
            description=(
                "在已确认资料范围内发起一次有界探索任务：沙盘影响链、事件诊断/"
                "补桥、一句场景对白，或对临时起点显式展开的完整排演"
                "（full_rehearsal，按 (目标数+1)×轮次 分开计量）；结果只进探索"
                "历史，不写正史。"
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
        "permission": "confirm",
        **_metadata(
            description=(
                "绑定当前探索结果追加一次有界生成；不扩大尺度、资料或联网范围，"
                "同根追加授权 1 次模型请求。"
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
        "permission": "confirm",
        **_metadata(
            description=(
                "按条目路径（chain:N/gap:N/bridge:N/line）锁定父结果中的一个条目"
                "重生成，item_text 与父内容比对防漂移；其余内容服务端原样保留，"
                "新结果行指向父行。"
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
