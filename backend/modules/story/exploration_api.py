"""Author routes for multi-scale independent exploration (P0 §8).

router prefix ``/api/story/exploration``；全部端点显式校验 account principal
与项目 owner（复用 ``require_active_project`` + 服务层 owner 校验）。执行类
端点挂 ``require_story_exploration_enabled``；history/compare 读取不挂 gate
（关闭后仍可读）。路由只做适配：推荐、确认、入队与读取都委托 evidence
facade 与 story 服务层。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.dependencies import DbSession
from core.errors import ConflictError, NotFoundError
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    AIRunAuthorizationReason,
    read_ai_run_envelope,
)
from infrastructure.llm.workflow_budget import AIRunEnvelope, new_ai_run_envelope
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from infrastructure.tasks.models import AsyncTask
from modules.evidence.contracts import (
    Assumption,
    ExplorationContextRequest,
    ExplorationStart,
)
from modules.evidence.facade import (
    attach_result_ref,
    preview_exploration_context,
    require_fresh_confirmation,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story import exploration_service
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_feature import require_story_exploration_enabled
from modules.story.exploration_recommend import recommend_exploration_scale
from modules.story.exploration_schemas import (
    AUTHOR_EDIT_OUTPUT_KIND,
    EVENT_HINT_LITERAL,
    EVENT_OUTPUT_KIND,
    PAYLOAD_MODELS_BY_BASE_KIND,
    SANDBOX_OUTPUT_KIND,
    EventOutputV1,
    ExplorationBudgetPreview,
    ExplorationCompareRequest,
    ExplorationConfirmationPreviewRequest,
    ExplorationConfirmationRequest,
    ExplorationScale,
    ExplorationStartTaskRequest,
    SandboxOutputV1,
    SceneLineOutputV1,
    validate_counterfactual_pair,
)

router = APIRouter(prefix="/api/story/exploration", tags=["story-exploration"])

EXPLORATION_CAPABILITY = "story.exploration"

SANDBOX_ACTION = "story.exploration.sandbox.generate"
EVENT_DIAGNOSE_ACTION = "story.exploration.event.diagnose"
EVENT_BRIDGE_ACTION = "story.exploration.event.bridge"
SCENE_LINE_ACTION = "story.exploration.scene_line.generate"

ACTION_BY_SCALE = {
    "sandbox": SANDBOX_ACTION,
    "event": EVENT_DIAGNOSE_ACTION,
    "scene_line": SCENE_LINE_ACTION,
}

TASK_TYPE_BY_CHAIN = {
    "progression": "story_exploration_progression_task",
    "scene": "story_exploration_scene_task",
}


def _raise_http(error: Exception) -> HTTPException:
    from core.errors import DomainError

    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, DomainError):
        return HTTPException(
            status_code=getattr(error, "status_code", None) or 400,
            detail=str(error),
        )
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="独立探索暂时无法完成该操作，请稍后重试。",
    )


# ---------------------------------------------------------------------------
# 端点请求模型（执行路径沿用 P1 契约模型）
# ---------------------------------------------------------------------------


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplorationPreviewApiRequest(_ApiModel):
    """推荐 + 预算预览：确定性，无模型调用；start 缺省时只做推荐与名义预算。

    反事实对照（M2）：提供 ``counterfactual_of_result_id`` + ``changed_assumptions``
    时由服务端从基线结果克隆起点，响应带 ``derived_start`` 与含基线身份的预算。
    事件模式提示（M2）：``event_mode_hint`` 仅在显式指定事件尺度时接受。
    """

    novel_id: str
    scale: ExplorationScale | None = None
    focus: str = Field(default="", max_length=2000)
    question: str | None = Field(default=None, max_length=4000)
    start: Annotated[ExplorationStart | None, Field(discriminator="kind")] = None
    task_hint: str | None = Field(default=None, max_length=120)
    counterfactual_of_result_id: str | None = Field(default=None, max_length=64)
    changed_assumptions: list[Assumption] | None = Field(
        default=None, min_length=1, max_length=10
    )
    event_mode_hint: EVENT_HINT_LITERAL | None = None

    @model_validator(mode="after")
    def validate_counterfactual(self):
        validate_counterfactual_pair(
            scale=self.scale or "sandbox",
            start=self.start,
            counterfactual_of_result_id=self.counterfactual_of_result_id,
            changed_assumptions=self.changed_assumptions,
        )
        if self.event_mode_hint is not None and self.scale != "event":
            raise ValueError("event_mode_hint 仅支持事件尺度，请显式指定 scale=event")
        return self


class ExplorationDetailApiRequest(_ApiModel):
    novel_id: str
    focus: str = Field(default="", max_length=2000)
    operation_id: UUID


class ExplorationReviseApiRequest(_ApiModel):
    """局部修订/补桥：item_path 定位父条目，item_text 防漂移（P0 §8.1）。"""

    novel_id: str
    operation_id: UUID
    revision_of: str | None = Field(default=None, max_length=64)
    item_path: str = Field(min_length=1, max_length=120)
    item_text: str | None = Field(default=None, max_length=4000)
    instruction: str = Field(min_length=1, max_length=2000)
    bridge_target: str | None = Field(default=None, max_length=500)


class ExplorationSaveEditApiRequest(_ApiModel):
    """作者编辑保存：结果 ID 走路径；base_output_kind 由前端随编辑一起提交。"""

    novel_id: str
    base_output_kind: Literal[
        "story.exploration.sandbox",
        "story.exploration.event",
        "story.exploration.scene_line",
    ]
    edited_payload: SandboxOutputV1 | EventOutputV1 | SceneLineOutputV1
    edit_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_same_shape(self):
        expected = PAYLOAD_MODELS_BY_BASE_KIND[self.base_output_kind]
        if not isinstance(self.edited_payload, expected):
            raise ValueError("edited_payload 必须与基础结果同构")
        return self


class ExplorationStartApiRequest(ExplorationStartTaskRequest):
    """start 端点在 P1 契约之上允许可选指定一句对白的目标角色。"""

    target_ref: str | None = Field(default=None, min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# owner 归属与探索根/分支定位
# ---------------------------------------------------------------------------


async def _project_owner_id(db, novel_id: str) -> str:
    from modules.project import facade as project_facade

    context = await project_facade.get_any_project_context(db, novel_id)
    if context is None or context.owner_id is None:
        raise NotFoundError("项目不存在")
    return str(context.owner_id)


def _is_exploration_root(root) -> bool:
    request_json = getattr(root, "request_json", None) or {}
    return bool(request_json.get("exploration_start_fingerprint"))


def _envelope_capability(root) -> str | None:
    raw = read_ai_run_envelope(getattr(root, "run_envelope_json", None))
    return raw.root_capability_id if raw is not None else None


async def _locate_exploration_result(
    db, *, novel_id: str, result_id: str, lock: bool = False
):
    row, chain = await exploration_service.locate_exploration_result(
        db, novel_id=novel_id, result_id=result_id, lock=lock
    )
    envelope = exploration_service.unpack_exploration_output(row)
    if envelope is None:
        raise ConflictError("所选结果不是探索结果")
    root = await exploration_service.root_for_chain(db, novel_id, row.root_id, chain)
    if (
        not _is_exploration_root(root)
        or _envelope_capability(root) != EXPLORATION_CAPABILITY
    ):
        raise ConflictError("所选结果不属于独立探索运行")
    return row, chain, root


async def _branch_for(db, novel_id: str, chain: str, branch_id, *, lock: bool = False):
    from modules.story.director_service import get_director_branch

    if chain == "scene":
        return await get_director_branch(db, novel_id, str(branch_id), lock=lock)
    from modules.story.world_progression_service import get_progression_branch

    return await get_progression_branch(db, novel_id, str(branch_id), lock=lock)


async def _require_root_idle(db, root, branch) -> None:
    for task_id in {root.current_task_id, branch.current_task_id} - {None}:
        task = await db.get(AsyncTask, task_id)
        if task is not None and task.status in {"pending", "running"}:
            raise ConflictError("该探索运行仍在执行，请等待当前任务结束")
    root.current_task_id = None
    branch.current_task_id = None


def _root_start_dump(root) -> dict:
    return dict((root.request_json or {}).get("exploration_start") or {})


def _root_scale(root) -> str:
    return str((root.request_json or {}).get("exploration_scale") or "")


def _effective_output_kind(envelope) -> str:
    if envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        return envelope.payload.base_output_kind
    return envelope.output_kind


def _generation_action(base_kind: str, payload: dict) -> str:
    if base_kind == SANDBOX_OUTPUT_KIND:
        return SANDBOX_ACTION
    if base_kind == EVENT_OUTPUT_KIND:
        # 诊断与导向走 diagnose/bridge 两动作；goal 与 bridge 共用补桥链路，
        # 导向 prompt 由根冻结的 event_mode_hint 注入。
        if payload.get("mode") == "diagnose":
            return EVENT_DIAGNOSE_ACTION
        return EVENT_BRIDGE_ACTION
    return SCENE_LINE_ACTION


def _branch_confirmation(branch) -> tuple[str, str]:
    """分支上冻结的确认 ID 与确认动作（start 时写入 branch.request_json）。"""
    request_json = getattr(branch, "request_json", None) or {}
    return (
        str(request_json.get("context_confirmation_id") or ""),
        str(request_json.get("confirmation_action") or ""),
    )


def _exploration_meta(
    *,
    request_payload: dict,
    root,
    branch,
    action: str,
    confirmation_action: str,
    confirmation_id: str,
    budget: ExplorationBudgetPreview,
    time_budget_seconds: int,
    execution_snapshot: dict,
    extra: dict | None = None,
) -> dict:
    snapshot = read_ai_run_envelope(root.run_envelope_json)
    return {
        "meta_version": 1,
        "request": request_payload,
        "action": action,
        "confirmation_action": confirmation_action,
        "context_confirmation_id": confirmation_id,
        "exploration_root_id": str(root.id),
        "exploration_branch_id": str(branch.id),
        "exploration_scale": _root_scale(root),
        "exploration_authorized_requests": budget.requests_max,
        "exploration_authorized_tokens": budget.tokens_max,
        "exploration_deadline_seconds": max(1, time_budget_seconds),
        "exploration_acknowledged_unknown_requests": (
            snapshot.requests_unknown if snapshot else 0
        ),
        "exploration_baseline_requests_started": (
            snapshot.requests_started if snapshot else 0
        ),
        "exploration_baseline_recent_attempts_overflow": (
            snapshot.recent_attempts_overflow if snapshot else 0
        ),
        "llm_execution_snapshot": execution_snapshot,
        AI_RUN_ENVELOPE_KEY: root.run_envelope_json,
        **(extra or {}),
    }


# ---------------------------------------------------------------------------
# 推荐 + 预算预览（无模型调用）
# ---------------------------------------------------------------------------


async def build_exploration_preview(db, data: ExplorationPreviewApiRequest) -> dict:
    require_story_exploration_enabled()
    await require_active_project(db, data.novel_id)
    owner_id = await _project_owner_id(db, data.novel_id)
    await exploration_service.require_project_owner(db, data.novel_id, owner_id)
    derived_start: ExplorationStart | None = None
    counterfactual_of: str | None = None
    if data.counterfactual_of_result_id is not None:
        counterfactual_of = data.counterfactual_of_result_id
        derived_start, counterfactual_of = (
            await exploration_service.resolve_counterfactual_start(
                db,
                novel_id=data.novel_id,
                result_id=counterfactual_of,
                scale=data.scale or "sandbox",
                changed_assumptions=list(data.changed_assumptions or []),
            )
        )
    scale = data.scale or ("sandbox" if derived_start is not None else None)
    reason = ""
    if scale is None:
        from modules.story.outline_state.models import Scene

        project_has_content = (
            await db.scalar(
                select(Scene.id)
                .where(Scene.novel_id == UUID(data.novel_id))
                .limit(1)
            )
            is not None
        )
        scale, reason = recommend_exploration_scale(
            data.question or "",
            data.task_hint or "",
            has_selection=False,
            project_has_content=project_has_content,
        )
    if derived_start is not None:
        budget = preview_exploration_budget(
            novel_id=data.novel_id,
            scale=scale,
            start=derived_start,
            focus=data.focus,
            counterfactual_of_result_id=counterfactual_of,
            changed_assumptions=data.changed_assumptions,
        )
    elif data.start is not None:
        budget = preview_exploration_budget(
            novel_id=data.novel_id,
            scale=scale,
            start=data.start,
            focus=data.focus,
            event_mode_hint=data.event_mode_hint,
        )
    else:
        budget = _advisory_budget(
            novel_id=data.novel_id,
            scale=scale,
            focus=data.focus,
            event_mode_hint=data.event_mode_hint,
        )
    response = {
        "recommended_scale": scale,
        "recommendation_reason": reason or "按你指定的尺度预览",
        "focus_hint": data.focus,
        "budget": budget.model_dump(mode="json"),
        "requires_confirmation": True,
        "confirmation_summary": (
            "开始前需要确认本次资料范围；临时起点允许空资料集确认。"
        ),
        "confirmation_scope": (
            "project（临时假设起点）"
            if (derived_start or data.start) is None
            or (derived_start or data.start).kind == "provisional"
            else "scene（场景锚点起点）"
        ),
        "possible_charge": "首次运行预计 1 次模型请求；“说详细点”等每次再授权 +1。",
        "action": ACTION_BY_SCALE[scale],
        "recommendation": {
            "type": "story_exploration_recommendation",
            "scale": scale,
            "reason": reason,
            "focus_hint": data.focus,
        },
    }
    if derived_start is not None:
        response["derived_start"] = derived_start.model_dump(mode="json")
        response["counterfactual_of_result_id"] = counterfactual_of
    return response


def _advisory_budget(
    *, novel_id: str, scale: str, focus: str, event_mode_hint: str | None = None
) -> ExplorationBudgetPreview:
    """未提供起点时的名义预算：请求次数为硬约定，Token 按焦点长度粗估。"""
    from infrastructure.llm.collaboration import content_hash

    chars = len(focus)
    tokens_min = max(1, chars // 4) + 100
    tokens_max = max(tokens_min, chars // 2 + 400)
    identity: dict = {
        "novel_id": str(novel_id),
        "scale": scale,
        "focus_chars": chars,
        "advisory": True,
    }
    if event_mode_hint is not None:
        identity["event_mode_hint"] = str(event_mode_hint)
    return ExplorationBudgetPreview(
        requests_min=1,
        requests_max=1,
        follow_up_max_requests=1,
        tokens_min=tokens_min,
        tokens_max=tokens_max,
        preview_hash=content_hash(identity),
    )


# ---------------------------------------------------------------------------
# 确认入口（经 Evidence facade）
# ---------------------------------------------------------------------------


def _context_request(
    data: ExplorationConfirmationPreviewRequest,
    start: ExplorationStart,
) -> ExplorationContextRequest:
    start_kind = start.kind
    return ExplorationContextRequest(
        novel_id=data.novel_id,
        action=data.action,
        task="导演多尺度独立探索",
        scope="scene" if start_kind == "scene_anchor" else "project",
        scene_id=start.scene_id if start_kind == "scene_anchor" else None,
        reveal_mode="author_safe",
        exploration_scale=data.scale,
        focus=data.focus,
        start=start,
        expected_context_fingerprint=getattr(
            data, "expected_context_fingerprint", None
        ),
    )


async def _effective_request_start(
    db, data: ExplorationConfirmationPreviewRequest
) -> ExplorationStart:
    """普通请求直接用 start；反事实请求从基线结果克隆起点（服务端权威）。"""
    if data.counterfactual_of_result_id is None:
        assert data.start is not None  # 请求模型已校验二选一
        return data.start
    cloned, _baseline_id = await exploration_service.resolve_counterfactual_start(
        db,
        novel_id=data.novel_id,
        result_id=data.counterfactual_of_result_id,
        scale=data.scale,
        changed_assumptions=list(data.changed_assumptions or []),
    )
    return cloned


async def preview_confirmation(
    db, data: ExplorationConfirmationPreviewRequest
) -> dict:
    require_story_exploration_enabled()
    await require_active_project(db, data.novel_id)
    start = await _effective_request_start(db, data)
    material = await preview_exploration_context(db, _context_request(data, start))
    return {
        "context_fingerprint": material["context_fingerprint"],
        "selected_asset_ids": material["selected_asset_ids"],
        "sources": material["sources"],
        "blockers": material["blockers"],
    }


async def confirm_exploration(db, data: ExplorationConfirmationRequest) -> dict:
    """落确认并回投影影；起点/尺度/焦点随确认冻结（P0 §2.4）。"""
    require_story_exploration_enabled()
    await require_active_project(db, data.novel_id)
    from modules.evidence.facade import confirm_exploration_context

    start = await _effective_request_start(db, data)
    record = await confirm_exploration_context(db, _context_request(data, start))
    return {
        "confirmation_id": str(record.id),
        "action": record.action,
        "scope": record.scope,
        "context_fingerprint": record.context_fingerprint,
        "result_status": record.result_status,
        "stale_reasons": list(record.stale_reasons),
        "warnings": list(record.warnings),
    }


# ---------------------------------------------------------------------------
# start：幂等入队（preview hash + 确认一致性 + 根/分支创建）
# ---------------------------------------------------------------------------


def _resolve_scene_target(data: ExplorationStartApiRequest) -> str | None:
    """B3 目标角色解析：显式指定优先；唯一候选/唯一正式角色自动锁定。"""
    if data.scale != "scene_line":
        if data.target_ref:
            raise ValueError("只有场景一句对白需要指定目标角色")
        return None
    start = data.start
    if start.kind != "provisional":
        if not data.target_ref:
            raise ValueError("场景一句对白请指定目标角色（正式角色 entity_id）")
        return data.target_ref
    candidate_ids = [item.ref_id for item in start.candidates]
    if data.target_ref:
        if data.target_ref not in candidate_ids and data.target_ref not in set(
            start.canonical_refs
        ):
            raise ValueError("目标角色不在本次探索的候选或正式角色范围内")
        return data.target_ref
    if len(candidate_ids) == 1:
        return candidate_ids[0]
    if not candidate_ids and len(start.canonical_refs) == 1:
        return start.canonical_refs[0]
    raise ValueError("本次探索有多个可能目标，请明确一句对白的目标角色")


async def start_exploration_task(
    db, *, data: ExplorationStartApiRequest, owner_id: str | None = None
) -> dict:
    require_story_exploration_enabled()
    await require_active_project(db, data.novel_id)
    owner_id = owner_id or await _project_owner_id(db, data.novel_id)
    chain = exploration_service.EXPLORATION_CHAIN_BY_SCALE[data.scale]
    task_type = TASK_TYPE_BY_CHAIN[chain]
    # 反事实对照：起点由基线结果克隆（服务端权威）；普通请求原样使用 start。
    effective_start = await _effective_request_start(db, data)
    counterfactual_of = data.counterfactual_of_result_id
    effective_start_dump = effective_start.model_dump(mode="json")
    request_payload = {
        **data.model_dump(mode="json", exclude={"operation_id", "start"}),
        "start": effective_start_dump,
    }
    fingerprint_payload = {
        key: value
        for key, value in request_payload.items()
        if key != "time_budget_seconds"
    }
    existing = await get_operation_task(
        db,
        operation_id=str(data.operation_id),
        task_type=task_type,
        novel_id=data.novel_id,
        request_payload=fingerprint_payload,
    )
    if existing is not None:
        row = await db.get(AsyncTask, UUID(str(existing.task_id)))
        meta = dict(row.meta or {}) if row else {}
        root_id = str(meta.get("exploration_root_id") or "")
        branch_id = str(meta.get("exploration_branch_id") or "")
        if not root_id or not branch_id:
            raise ConflictError("相同操作已被接受，但探索运行根不可恢复")
        return {
            "task_id": str(existing.task_id),
            "status": existing.status,
            "root_id": root_id,
            "branch_id": branch_id,
        }

    confirmation = await require_fresh_confirmation(
        db,
        novel_id=data.novel_id,
        action=data.action,
        confirmation_id=data.context_confirmation_id,
    )
    options = dict(confirmation.compile_options or {})
    if options.get("exploration_start") != effective_start_dump:
        raise ConflictError("资料确认的探索起点与本次请求不一致，请重新确认")
    if str(options.get("exploration_scale") or "") != data.scale:
        raise ConflictError("资料确认的探索尺度与本次请求不一致")
    if str(options.get("exploration_focus") or "") != str(data.focus or ""):
        raise ConflictError("资料确认的焦点与本次请求不一致，请重新确认")
    budget = preview_exploration_budget(
        novel_id=data.novel_id,
        scale=data.scale,
        start=effective_start,
        focus=data.focus,
        counterfactual_of_result_id=counterfactual_of,
        changed_assumptions=(
            list(data.changed_assumptions) if counterfactual_of else None
        ),
        event_mode_hint=data.event_mode_hint,
    )
    if budget.preview_hash != data.budget_preview_hash:
        raise ConflictError("起点或焦点已变化，请重新预览预算")
    target_ref = _resolve_scene_target(data)
    execution_snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)

    root, branch = await exploration_service.create_exploration_root(
        db,
        novel_id=data.novel_id,
        owner_id=owner_id,
        scale=data.scale,
        start=effective_start,
        scene_id=(
            effective_start.scene_id
            if effective_start.kind == "scene_anchor"
            else None
        ),
        context_confirmation_id=(
            data.context_confirmation_id if chain == "progression" else None
        ),
        llm_execution_snapshot_json=execution_snapshot,
        status="queued",
        branch_request_json={
            "context_confirmation_id": data.context_confirmation_id,
            "confirmation_action": data.action,
        },
        counterfactual_of=counterfactual_of,
        changed_assumptions=(
            list(data.changed_assumptions) if counterfactual_of else None
        ),
        event_mode_hint=data.event_mode_hint,
    )
    started_at = datetime.now(UTC)
    envelope = new_ai_run_envelope(
        operation_id=str(data.operation_id),
        run_id=str(root.id),
        root_capability_id=EXPLORATION_CAPABILITY,
        novel_id=data.novel_id,
        request_limit=budget.requests_max,
        budget_mode="bounded",
        token_limit=budget.tokens_max,
        deadline_at=started_at + timedelta(seconds=data.time_budget_seconds),
        started_at=started_at,
    )
    root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
    meta = _exploration_meta(
        request_payload={**fingerprint_payload, "mode": "start"},
        root=root,
        branch=branch,
        action=data.action,
        confirmation_action=data.action,
        confirmation_id=data.context_confirmation_id,
        budget=budget,
        time_budget_seconds=data.time_budget_seconds,
        execution_snapshot=execution_snapshot,
        extra={
            "budget_preview_hash": data.budget_preview_hash,
            "start": effective_start_dump,
            "focus": data.focus,
            "instruction": "",
            **({"target_ref": target_ref} if target_ref else {}),
        },
    )
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id),
        task_type=task_type,
        novel_id=data.novel_id,
        request_payload=fingerprint_payload,
        meta=meta,
    )
    if receipt.reused:
        row = await db.get(AsyncTask, UUID(str(receipt.task_id)))
        existing_meta = dict(row.meta or {}) if row else {}
        root_id = str(existing_meta.get("exploration_root_id") or "")
        branch_id = str(existing_meta.get("exploration_branch_id") or "")
        if not root_id or not branch_id:
            raise ConflictError("相同操作已被接受，但探索运行根不可恢复")
        await db.delete(branch)
        await db.delete(root)
        await db.flush()
        return {
            "task_id": str(receipt.task_id),
            "status": receipt.status,
            "root_id": root_id,
            "branch_id": branch_id,
        }
    root.current_task_id = UUID(str(receipt.task_id))
    branch.current_task_id = UUID(str(receipt.task_id))
    await attach_result_ref(
        db,
        novel_id=data.novel_id,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=str(receipt.task_id),
        status="running",
    )
    await db.flush()
    return {
        "task_id": str(receipt.task_id),
        "status": receipt.status,
        "root_id": str(root.id),
        "branch_id": str(branch.id),
    }


# ---------------------------------------------------------------------------
# detail / revise：同根追加授权 + 新任务（202）
# ---------------------------------------------------------------------------


async def _branch_tip_id(db, novel_id: str, chain: str, branch) -> str | None:
    if chain == "progression":
        from modules.story.world_progression_models import StoryWorldProgressionStep

        return await db.scalar(
            select(StoryWorldProgressionStep.id)
            .where(
                StoryWorldProgressionStep.novel_id == UUID(novel_id),
                StoryWorldProgressionStep.branch_id == branch.id,
            )
            .order_by(StoryWorldProgressionStep.step_number.desc())
            .limit(1)
        )
    from modules.story.models import StorySceneDirectorRound

    return await db.scalar(
        select(StorySceneDirectorRound.id)
        .where(
            StorySceneDirectorRound.novel_id == UUID(novel_id),
            StorySceneDirectorRound.branch_id == branch.id,
        )
        .order_by(StorySceneDirectorRound.round_number.desc())
        .limit(1)
    )


async def submit_exploration_follow_up(
    db,
    *,
    novel_id: str,
    result_id: str,
    mode: str,
    operation_id: str,
    owner_id: str | None = None,
    focus: str = "",
    instruction: str = "",
    item_path: str = "",
    item_text: str | None = None,
    bridge_target: str | None = None,
    revision_of: str | None = None,
) -> dict:
    require_story_exploration_enabled()
    await require_active_project(db, novel_id)
    owner_id = owner_id or await _project_owner_id(db, novel_id)
    row, chain, root = await _locate_exploration_result(
        db, novel_id=novel_id, result_id=result_id, lock=True
    )
    envelope = exploration_service.unpack_exploration_output(row)
    if envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        raise ConflictError("作者编辑版本不能继续详略或修订；请回到原始 AI 结果")
    base_kind = _effective_output_kind(envelope)
    if mode == "revise":
        # 入队前先按 item_path 定位并做防漂移比对，失败立即 409（worker 内再权威校验）。
        from modules.story.exploration_tasks import check_revision_target

        try:
            check_revision_target(
                envelope.payload.model_dump(mode="json"), item_path, item_text, base_kind
            )
        except ValueError as error:
            raise ConflictError(str(error)) from error
    branch = await _branch_for(db, novel_id, chain, row.branch_id, lock=True)
    confirmation_id, confirmation_action = _branch_confirmation(branch)
    if not confirmation_id or not confirmation_action:
        raise ConflictError("探索分支缺少可复用的资料确认，无法续算")
    latest_id = await _branch_tip_id(db, novel_id, chain, branch)
    if str(row.id) != str(latest_id):
        raise ConflictError("只能对分支最新结果详略或修订；请先回到最新结果")
    if revision_of and str(revision_of) != str(row.id):
        raise ConflictError("修订声明与所选结果不一致")
    await _require_root_idle(db, root, branch)

    raw = read_ai_run_envelope(root.run_envelope_json)
    if (
        raw is None
        or raw.run_id != str(root.id)
        or raw.root_capability_id != EXPLORATION_CAPABILITY
    ):
        raise ConflictError("累计预算账本不可恢复，已停止续算")
    if raw.requests_unknown:
        raise ConflictError("之前的请求结果未知；请先在助手中确认后再续算")
    run_envelope = AIRunEnvelope(raw)
    start = validate_start_dump(_root_start_dump(root))
    scale = _root_scale(root)
    follow_up_budget = preview_exploration_budget(
        novel_id=novel_id,
        scale=scale,
        start=start,
        focus=focus or instruction,
    )
    await run_envelope.authorize_additional_requests(
        1,
        reason=(
            AIRunAuthorizationReason.author_detail_expand
            if mode == "detail"
            else AIRunAuthorizationReason.author_revise
        ),
        additional_tokens=follow_up_budget.tokens_max,
    )
    root.run_envelope_json = run_envelope.snapshot().model_dump(mode="json")
    root.status = "queued"
    branch.status = "queued"
    await db.flush()

    await require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=confirmation_action,
        confirmation_id=confirmation_id,
    )
    action = _generation_action(base_kind, envelope.payload.model_dump(mode="json"))
    if mode == "revise" and base_kind == EVENT_OUTPUT_KIND and bridge_target:
        action = EVENT_BRIDGE_ACTION
    meta = _exploration_meta(
        request_payload={
            "mode": mode,
            "result_id": str(row.id),
            "start": _root_start_dump(root),
            "scale": scale,
            "focus": focus,
            "instruction": instruction,
            **({"item_path": item_path} if mode == "revise" else {}),
            **({"item_text": item_text} if mode == "revise" and item_text else {}),
            **({"bridge_target": bridge_target} if bridge_target else {}),
        },
        root=root,
        branch=branch,
        action=action,
        confirmation_action=confirmation_action,
        confirmation_id=confirmation_id,
        budget=follow_up_budget,
        time_budget_seconds=3600,
        execution_snapshot=dict(root.llm_execution_snapshot_json or {}),
        extra={
            "parent_result_id": str(row.id),
            "start": _root_start_dump(root),
            "focus": focus,
            "instruction": instruction,
            **({"item_path": item_path} if mode == "revise" else {}),
            **({"item_text": item_text} if mode == "revise" and item_text else {}),
            **({"bridge_target": bridge_target} if bridge_target else {}),
            **(
                {"target_ref": _scene_target(envelope)}
                if chain == "scene"
                else {}
            ),
        },
    )
    fingerprint_payload = {
        "mode": mode,
        "result_id": str(row.id),
        "focus": focus,
        "instruction": instruction,
        **({"item_path": item_path} if mode == "revise" else {}),
        **({"item_text": item_text} if mode == "revise" and item_text else {}),
        **({"bridge_target": bridge_target} if bridge_target else {}),
    }
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(operation_id),
        task_type=TASK_TYPE_BY_CHAIN[chain],
        novel_id=novel_id,
        request_payload=fingerprint_payload,
        meta=meta,
    )
    if receipt.reused:
        task = await db.get(AsyncTask, UUID(str(receipt.task_id)))
        existing_meta = dict(task.meta or {}) if task else {}
        return {
            "task_id": str(receipt.task_id),
            "status": receipt.status,
            "root_id": str(
                existing_meta.get("exploration_root_id") or root.id
            ),
            "branch_id": str(
                existing_meta.get("exploration_branch_id") or branch.id
            ),
        }
    root.current_task_id = UUID(str(receipt.task_id))
    branch.current_task_id = UUID(str(receipt.task_id))
    await attach_result_ref(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        result_type="task",
        result_id=str(receipt.task_id),
        status="running",
    )
    await db.flush()
    return {
        "task_id": str(receipt.task_id),
        "status": receipt.status,
        "root_id": str(root.id),
        "branch_id": str(branch.id),
    }


def _scene_target(envelope) -> str:
    payload = envelope.payload
    if envelope.output_kind == AUTHOR_EDIT_OUTPUT_KIND:
        payload = payload.edited_payload
    return str(getattr(payload, "target_ref", "") or "")


def validate_start_dump(start_dump: dict):
    """起点载荷校验的稳定入口（供 operations 复用）。"""
    from modules.evidence.contracts import ProvisionalStart, SceneAnchorStart

    if start_dump.get("kind") == "scene_anchor":
        return SceneAnchorStart.model_validate(start_dump)
    return ProvisionalStart.model_validate(start_dump)


# ---------------------------------------------------------------------------
# 只读与零模型端点：save-edit / compare / history
# ---------------------------------------------------------------------------


async def save_exploration_edit(
    db, *, result_id: str, data: ExplorationSaveEditApiRequest
) -> dict:
    require_story_exploration_enabled()
    await require_active_project(db, data.novel_id)
    row, _chain, _root = await _locate_exploration_result(
        db, novel_id=data.novel_id, result_id=result_id, lock=True
    )
    envelope = exploration_service.unpack_exploration_output(row)
    if _effective_output_kind(envelope) != data.base_output_kind:
        raise ConflictError("base_output_kind 与所选结果不一致，请刷新后重试")
    new_row, new_envelope = await exploration_service.save_exploration_author_edit(
        db,
        novel_id=data.novel_id,
        owner_id=await _project_owner_id(db, data.novel_id),
        base_result_id=str(row.id),
        edited_payload=data.edited_payload,
        edit_note=data.edit_note,
    )
    return {
        "result_id": str(new_row.id),
        "output_kind": new_envelope.output_kind,
        "payload": new_envelope.payload.model_dump(mode="json"),
        "created_at": new_row.created_at.isoformat() if new_row.created_at else None,
    }


async def compare_exploration(db, data: ExplorationCompareRequest) -> dict:
    await require_active_project(db, data.novel_id)
    result = await exploration_service.compare_exploration_results(
        db,
        novel_id=data.novel_id,
        owner_id=await _project_owner_id(db, data.novel_id),
        first_result_id=data.first_result_id,
        second_result_id=data.second_result_id,
        mode=data.mode,
    )

    def _side(side: dict) -> dict:
        envelope = side["envelope"]
        return {
            "result_id": side["result_id"],
            "root_id": side["root_id"],
            "branch_id": side["branch_id"],
            "output_kind": envelope.output_kind,
            "payload": envelope.payload.model_dump(mode="json"),
            "created_at": side["created_at"],
        }

    response = {
        "start_fingerprint": result["start_fingerprint"],
        "first": _side(result["left"]),
        "second": _side(result["right"]),
    }
    if result.get("mode") == "counterfactual":
        response["mode"] = "counterfactual"
        response["changed_conditions"] = result["changed_conditions"]
    return response


async def exploration_history(
    db,
    *,
    novel_id: str,
    root_id: str | None,
    scale: str | None,
    limit: int,
    offset: int,
) -> dict:
    await require_active_project(db, novel_id)
    return await exploration_service.list_exploration_history_results(
        db,
        novel_id=novel_id,
        owner_id=await _project_owner_id(db, novel_id),
        root_id=root_id,
        scale=scale,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("/preview")
async def api_preview(data: ExplorationPreviewApiRequest, db: DbSession):
    try:
        return await build_exploration_preview(db, data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post("/confirmation/preview")
async def api_confirmation_preview(
    data: ExplorationConfirmationPreviewRequest, db: DbSession
):
    try:
        return await preview_confirmation(db, data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post("/confirmation")
async def api_confirmation(data: ExplorationConfirmationRequest, db: DbSession):
    try:
        return await confirm_exploration(db, data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post("/start", status_code=http_status.HTTP_202_ACCEPTED)
async def api_start(data: ExplorationStartApiRequest, db: DbSession):
    try:
        return await start_exploration_task(db, data=data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/results/{result_id}/detail", status_code=http_status.HTTP_202_ACCEPTED
)
async def api_detail(result_id: str, data: ExplorationDetailApiRequest, db: DbSession):
    try:
        return await submit_exploration_follow_up(
            db,
            novel_id=data.novel_id,
            result_id=result_id,
            mode="detail",
            operation_id=str(data.operation_id),
            focus=data.focus,
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/results/{result_id}/revise", status_code=http_status.HTTP_202_ACCEPTED
)
async def api_revise(result_id: str, data: ExplorationReviseApiRequest, db: DbSession):
    try:
        return await submit_exploration_follow_up(
            db,
            novel_id=data.novel_id,
            result_id=result_id,
            mode="revise",
            operation_id=str(data.operation_id),
            instruction=data.instruction,
            item_path=data.item_path,
            item_text=data.item_text,
            bridge_target=data.bridge_target,
            revision_of=data.revision_of,
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post("/results/{result_id}/save-edit")
async def api_save_edit(
    result_id: str, data: ExplorationSaveEditApiRequest, db: DbSession
):
    try:
        return await save_exploration_edit(db, result_id=result_id, data=data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post("/compare")
async def api_compare(data: ExplorationCompareRequest, db: DbSession):
    try:
        return await compare_exploration(db, data)
    except Exception as error:
        raise _raise_http(error) from error


@router.get("/history")
async def api_history(
    db: DbSession,
    *,
    novel_id: str = Query(...),
    root_id: str | None = Query(default=None),
    scale: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        return await exploration_history(
            db,
            novel_id=novel_id,
            root_id=root_id,
            scale=scale,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        raise _raise_http(error) from error
