"""Author-facing API for isolated Scene Director runs and their history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
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
from modules.evidence.facade import (
    attach_result_ref,
    prepare_confirmed_ai_action,
    require_fresh_confirmation,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story.director_budget import (
    budget_stop_reason,
    director_pending_checkpoint_hash,
    preview_director_budget,
    preview_director_continuation,
    preview_director_resume,
)
from modules.story.director_candidate_transfer import transfer_director_candidate
from modules.story.director_context import (
    director_confirmation_scope,
    read_director_source,
    require_director_confirmation_scope,
    scope_director_source,
)
from modules.story.director_feature import require_scene_director_enabled
from modules.story.director_schemas import (
    DirectorAdvanceRequest,
    DirectorBudgetPreviewRequest,
    DirectorCandidateTransferReceipt,
    DirectorCandidateTransferRequest,
    DirectorContinueBudgetPreviewRequest,
    DirectorContinueRequest,
    DirectorDeleteBranchRequest,
    DirectorDeleteUnstarredRequest,
    DirectorMutationRequest,
    DirectorPreferenceUpdate,
    DirectorReferenceUpdate,
    DirectorSaveReferenceRequest,
    DirectorStartRequest,
    DirectorTaskAccepted,
    DirectorUpdateMetadata,
)
from modules.story.director_service import (
    delete_director_branch,
    delete_director_reference,
    delete_unstarred_director_branches,
    get_director_branch,
    get_director_preferences,
    get_director_root,
    get_director_round,
    read_director_history_view,
    recheck_director_round_consistency,
    restore_director_branch,
    restore_director_reference,
    save_director_reference,
    save_round_metadata,
    set_director_preferences,
    update_reference_metadata,
)
from modules.story.director_tasks import STORY_SCENE_DIRECTOR_TASK
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)

router = APIRouter(
    prefix="/api/story",
    tags=["story-scene-director"],
    dependencies=[Depends(require_scene_director_enabled)],
)
DIRECTOR_CAPABILITY = "story.scene_director"


def _trace_fields(schema: type) -> dict[str, str]:
    return {field: f"data.{field}" for field in schema.model_fields}


def _raise_http(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, (ConflictError,)):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="场景导演暂时无法完成该操作，请稍后重试。",
    )


def _preview_request(
    *,
    scene_id: str,
    character_ids: list[str],
    related_object_ids: list[str],
    primary_character_ids: list[str],
    rounds: int,
    instructions: str = "",
    intervention: str = "",
    public_stimulus: str = "",
    selected_alternative: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        scene_id=scene_id,
        character_ids=character_ids,
        related_object_ids=related_object_ids,
        primary_character_ids=primary_character_ids,
        rounds=rounds,
        instructions=instructions,
        intervention=intervention,
        public_stimulus=public_stimulus,
        selected_alternative=selected_alternative,
    )


async def _source_for_start(db, data: DirectorBudgetPreviewRequest) -> dict:
    return await read_director_source(
        db,
        novel_id=data.novel_id,
        scene_id=data.scene_id,
        character_ids=data.character_ids,
        related_object_ids=data.related_object_ids,
    )


def _validate_confirmation_scope(options: dict, data) -> None:
    if str(options.get("scene_id") or "") != str(data.scene_id):
        raise ConflictError("资料确认的 Scene 与当前导演场景不一致")
    confirmed_characters = options.get("character_ids")
    if not isinstance(confirmed_characters, list) or set(
        map(str, confirmed_characters)
    ) != set(data.character_ids):
        raise ConflictError("请在资料确认中重新选择本轮参与人物")
    confirmed_entities = options.get("entity_ids")
    if data.related_object_ids and (
        not isinstance(confirmed_entities, list)
        or not set(data.related_object_ids) <= set(map(str, confirmed_entities))
    ):
        raise ConflictError("相关对象不在已确认的资料范围内，请重新整理资料")


def _response_for_task(task_id: str, status: str, root_id: str) -> DirectorTaskAccepted:
    return DirectorTaskAccepted(
        task_id=UUID(str(task_id)),
        status=status,
        run_id=UUID(str(root_id)),
        root_id=UUID(str(root_id)),
    )


async def _existing_director_task(
    db, *, novel_id: str, operation_id: str, task_type: str, payload: dict
):
    return await get_operation_task(
        db,
        operation_id=operation_id,
        task_type=task_type,
        novel_id=novel_id,
        request_payload=payload,
    )


async def submit_director_start(db, data: DirectorStartRequest) -> DirectorTaskAccepted:
    """Create one frozen root and enqueue its first isolated branch."""
    require_scene_director_enabled()
    novel_id = data.novel_id
    request_payload = {"mode": "start", **data.model_dump(mode="json")}
    fingerprint_payload = {
        key: value for key, value in request_payload.items() if key != "operation_id"
    }
    existing = await _existing_director_task(
        db,
        novel_id=novel_id,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        payload=fingerprint_payload,
    )
    if existing is not None:
        row = await db.get(AsyncTask, UUID(str(existing.task_id)))
        root_id = str((row.meta or {}).get("director_root_id") or "") if row else ""
        if not root_id:
            raise ConflictError("相同操作已被接受，但导演运行根不可恢复")
        return _response_for_task(existing.task_id, existing.status, root_id)

    source = await _source_for_start(db, data)
    preview = preview_director_budget(data, source)
    if preview["preview_hash"] != data.budget_preview_hash:
        raise ConflictError("场景、人物或档案资料已变化，请重新预览预算")
    confirmation = await require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=data.context_confirmation_id,
    )
    _validate_confirmation_scope(confirmation.compile_options, data)

    root_id, branch_id = uuid4(), uuid4()
    started_at = datetime.now(UTC)
    deadline_at = started_at + timedelta(seconds=data.time_budget_seconds)
    envelope = new_ai_run_envelope(
        operation_id=str(data.operation_id),
        run_id=str(root_id),
        root_capability_id=DIRECTOR_CAPABILITY,
        novel_id=novel_id,
        request_limit=data.request_limit,
        budget_mode="bounded",
        token_limit=data.token_limit,
        deadline_at=deadline_at,
        started_at=started_at,
    )
    execution_snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    root = StorySceneDirectorRoot(
        id=root_id,
        novel_id=UUID(novel_id),
        scene_id=UUID(data.scene_id),
        source_hash=source["source_hash"],
        request_json=data.model_dump(mode="json"),
        llm_execution_snapshot_json=execution_snapshot,
        run_envelope_json=envelope.snapshot().model_dump(mode="json"),
        status="queued",
    )
    branch = StorySceneDirectorBranch(
        id=branch_id,
        novel_id=UUID(novel_id),
        root_id=root_id,
        parent_round_id=None,
        branch_kind="start",
        source_hash=source["source_hash"],
        request_json=request_payload,
        pending_round_json={},
        status="queued",
    )
    db.add(root)
    await db.flush()
    db.add(branch)
    await db.flush()
    meta = {
        "meta_version": 1,
        "request": request_payload,
        "action": STORY_ONE_CLICK_ACTION,
        "director_root_id": str(root_id),
        "director_branch_id": str(branch_id),
        "director_authorized_requests": data.request_limit,
        "director_authorized_tokens": data.token_limit,
        "director_deadline_seconds": data.time_budget_seconds,
        "director_acknowledged_unknown_requests": 0,
        "director_baseline_requests_started": 0,
        "director_baseline_recent_attempts_overflow": 0,
        "llm_execution_snapshot": execution_snapshot,
        AI_RUN_ENVELOPE_KEY: envelope.snapshot().model_dump(mode="json"),
    }
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        novel_id=novel_id,
        request_payload=fingerprint_payload,
        meta=meta,
    )
    if receipt.reused:
        existing_task = await db.get(AsyncTask, UUID(str(receipt.task_id)))
        existing_root_id = (
            str((existing_task.meta or {}).get("director_root_id") or "")
            if existing_task
            else ""
        )
        if not existing_root_id:
            raise ConflictError("相同操作已被接受，但导演运行根不可恢复")
        await db.delete(branch)
        await db.delete(root)
        await db.flush()
        return _response_for_task(receipt.task_id, receipt.status, existing_root_id)
    root.current_task_id = UUID(str(receipt.task_id))
    branch.current_task_id = UUID(str(receipt.task_id))
    await attach_result_ref(
        db,
        novel_id=novel_id,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=receipt.task_id,
        status="running",
    )
    await db.flush()
    return _response_for_task(receipt.task_id, receipt.status, str(root_id))


async def _require_root_idle(db, root: StorySceneDirectorRoot) -> None:
    if root.current_task_id is None:
        return
    task = await db.scalar(
        select(AsyncTask)
        .where(
            AsyncTask.id == root.current_task_id,
            AsyncTask.novel_id == root.novel_id,
        )
        .with_for_update()
    )
    if task is not None and task.status in {"pending", "running"}:
        raise ConflictError("该导演运行仍在执行，请等待当前回合结束")
    root.current_task_id = None


async def continue_director_root(
    db,
    *,
    root_id: str,
    data: DirectorContinueRequest,
) -> DirectorTaskAccepted:
    if data.resume_branch_id is not None:
        return await resume_director_branch(db, root_id=root_id, data=data)
    require_scene_director_enabled()
    novel_id = data.novel_id
    request_payload = {"mode": "continue", **data.model_dump(mode="json")}
    fingerprint_payload = {
        key: value for key, value in request_payload.items() if key != "operation_id"
    }
    existing = await _existing_director_task(
        db,
        novel_id=novel_id,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        payload=fingerprint_payload,
    )
    if existing is not None:
        existing_task = await db.get(AsyncTask, UUID(str(existing.task_id)))
        existing_root_id = (
            str((existing_task.meta or {}).get("director_root_id") or "")
            if existing_task
            else ""
        )
        if existing_root_id != root_id:
            raise ConflictError("相同操作 ID 对应另一个导演运行")
        return _response_for_task(existing.task_id, existing.status, root_id)

    root = await get_director_root(db, novel_id, root_id, lock=True)
    await _require_root_idle(db, root)
    existing = await _existing_director_task(
        db,
        novel_id=novel_id,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        payload=fingerprint_payload,
    )
    if existing is not None:
        existing_task = await db.get(AsyncTask, UUID(str(existing.task_id)))
        existing_root_id = (
            str((existing_task.meta or {}).get("director_root_id") or "")
            if existing_task
            else ""
        )
        if existing_root_id != root_id:
            raise ConflictError("相同操作 ID 对应另一个导演运行")
        return _response_for_task(existing.task_id, existing.status, root_id)
    from modules.story.exploration_service import require_legacy_director_round

    previous_envelope = root.run_envelope_json
    previous_status = root.status
    parent_round, _ = await get_director_round(db, novel_id, str(data.parent_round_id))
    if str(parent_round.root_id) != root_id:
        raise ValueError("所选回合不属于这个导演运行")
    require_legacy_director_round(parent_round)
    from modules.story.director_operations import _continuation_preview

    _root, _parent, current_preview = await _continuation_preview(db, novel_id, data)
    if current_preview["preview_hash"] != data.budget_preview_hash:
        raise ConflictError("场景、人物或档案依据已有变化，请重新预览预算")
    if data.branch_kind == "rewrite_character":
        if not data.rewrite_character_id or data.rounds != 1:
            raise ValueError("单人物重写必须选一名本轮人物，并且只产生一个版本")
    elif data.rewrite_character_id:
        raise ValueError("只有单人物重写可以指定人物")

    confirmation = await require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=data.context_confirmation_id,
    )
    root_request = root.request_json or {}
    _validate_confirmation_scope(
        confirmation.compile_options,
        SimpleNamespace(
            scene_id=str(root.scene_id),
            character_ids=list(root_request.get("character_ids") or []),
            related_object_ids=list(root_request.get("related_object_ids") or []),
        ),
    )
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=data.context_confirmation_id,
    )
    require_director_confirmation_scope(
        (parent_round.input_json or {}).get("source_snapshot") or {},
        director_confirmation_scope(confirmed),
    )
    raw = read_ai_run_envelope(root.run_envelope_json)
    if (
        raw is None
        or raw.run_id != root_id
        or raw.root_capability_id != DIRECTOR_CAPABILITY
    ):
        raise ConflictError("累计预算账本不可恢复，已停止续算")
    if raw.requests_unknown and not data.allow_possible_duplicate_charge:
        raise ConflictError("之前的请求结果未知；继续前需明确确认可能重复计费")
    envelope = AIRunEnvelope(raw)
    if data.additional_requests or data.additional_tokens:
        await envelope.authorize_additional_requests(
            data.additional_requests,
            reason=(
                AIRunAuthorizationReason.duplicate_charge_confirmed
                if raw.requests_unknown and data.allow_possible_duplicate_charge
                else AIRunAuthorizationReason.author_resume
            ),
            additional_tokens=data.additional_tokens,
        )
    elif data.allow_possible_duplicate_charge or budget_stop_reason(envelope):
        raise ConflictError("原运行预算已暂停；请明确追加授权后再继续")
    updated_snapshot = envelope.snapshot()

    branch_id = uuid4()
    branch = StorySceneDirectorBranch(
        id=branch_id,
        novel_id=UUID(novel_id),
        root_id=UUID(root_id),
        parent_round_id=parent_round.id,
        branch_kind=data.branch_kind,
        source_hash=parent_round.source_hash,
        request_json=request_payload,
        pending_round_json={},
        status="queued",
    )
    db.add(branch)
    root.run_envelope_json = updated_snapshot.model_dump(mode="json")
    root.status = "queued"
    await db.flush()
    meta = {
        "meta_version": 1,
        "request": request_payload,
        "action": STORY_ONE_CLICK_ACTION,
        "director_root_id": root_id,
        "director_branch_id": str(branch_id),
        "director_authorized_requests": data.additional_requests,
        "director_authorized_tokens": data.additional_tokens,
        "director_deadline_seconds": max(
            1,
            int(
                (
                    updated_snapshot.deadline_at - updated_snapshot.started_at
                ).total_seconds()
            )
            if updated_snapshot.deadline_at
            else 3600,
        ),
        "director_acknowledged_unknown_requests": updated_snapshot.requests_unknown,
        "director_baseline_requests_started": updated_snapshot.requests_started,
        "director_baseline_recent_attempts_overflow": (
            updated_snapshot.recent_attempts_overflow
        ),
        "llm_execution_snapshot": root.llm_execution_snapshot_json,
        AI_RUN_ENVELOPE_KEY: updated_snapshot.model_dump(mode="json"),
    }
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        novel_id=novel_id,
        request_payload=fingerprint_payload,
        meta=meta,
    )
    if receipt.reused:
        existing_task = await db.get(AsyncTask, UUID(str(receipt.task_id)))
        existing_root_id = (
            str((existing_task.meta or {}).get("director_root_id") or "")
            if existing_task
            else ""
        )
        if existing_root_id != root_id:
            raise ConflictError("相同操作已被接受，但导演运行根不匹配")
        await db.delete(branch)
        root.run_envelope_json = previous_envelope
        root.status = previous_status
        await db.flush()
        return _response_for_task(receipt.task_id, receipt.status, root_id)
    root.current_task_id = UUID(str(receipt.task_id))
    branch.current_task_id = UUID(str(receipt.task_id))
    await attach_result_ref(
        db,
        novel_id=novel_id,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=receipt.task_id,
        status="running",
    )
    await db.flush()
    return _response_for_task(receipt.task_id, receipt.status, root_id)


async def resume_director_branch(
    db,
    *,
    root_id: str,
    data: DirectorContinueRequest,
) -> DirectorTaskAccepted:
    """Resume a paused branch in place, retaining its durable round checkpoint."""
    require_scene_director_enabled()
    novel_id = data.novel_id
    request_payload = {"mode": "resume", **data.model_dump(mode="json")}
    fingerprint_payload = {
        key: value for key, value in request_payload.items() if key != "operation_id"
    }
    existing = await _existing_director_task(
        db,
        novel_id=novel_id,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        payload=fingerprint_payload,
    )
    if existing is not None:
        task = await db.get(AsyncTask, UUID(str(existing.task_id)))
        if str((task.meta or {}).get("director_root_id") or "") != root_id:
            raise ConflictError("相同操作 ID 对应另一个导演运行")
        return _response_for_task(existing.task_id, existing.status, root_id)

    root = await get_director_root(db, novel_id, root_id, lock=True)
    existing = await _existing_director_task(
        db,
        novel_id=novel_id,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        payload=fingerprint_payload,
    )
    if existing is not None:
        task = await db.get(AsyncTask, UUID(str(existing.task_id)))
        if str((task.meta or {}).get("director_root_id") or "") != root_id:
            raise ConflictError("相同操作 ID 对应另一个导演运行")
        return _response_for_task(existing.task_id, existing.status, root_id)
    await _require_root_idle(db, root)
    branch = await get_director_branch(
        db, novel_id, str(data.resume_branch_id), lock=True
    )
    if str(branch.root_id) != root_id:
        raise ValueError("待恢复分支不属于这个导演运行")
    if branch.status not in {"paused_budget", "paused_unknown"}:
        raise ConflictError("只有预算或未知用量暂停的分支可以恢复")
    from modules.story.exploration_service import require_legacy_director_round

    exploration_source = await db.scalar(
        select(StorySceneDirectorRound)
        .where(
            StorySceneDirectorRound.novel_id == UUID(novel_id),
            StorySceneDirectorRound.branch_id == branch.id,
        )
        .order_by(StorySceneDirectorRound.round_number.desc())
        .limit(1)
    )
    if exploration_source is not None:
        require_legacy_director_round(exploration_source)

    raw = read_ai_run_envelope(root.run_envelope_json)
    if (
        raw is None
        or raw.run_id != root_id
        or raw.root_capability_id != DIRECTOR_CAPABILITY
    ):
        raise ConflictError("累计预算账本不可恢复，已停止续算")
    envelope = AIRunEnvelope(raw)
    preview = preview_director_resume(root_id, branch, envelope)
    if preview["preview_hash"] != data.budget_preview_hash:
        raise ConflictError("待恢复检查点或累计账本已变化，请重新预览预算")
    if not (data.additional_requests or data.additional_tokens):
        raise ConflictError("恢复前请明确追加请求或 Token 额度")
    if raw.requests_unknown and not data.allow_possible_duplicate_charge:
        raise ConflictError("之前的请求结果未知；恢复前需明确确认可能重复计费")
    if raw.requests_unknown and data.additional_requests < 1:
        raise ConflictError("结果未知的请求可能需要重试；请追加请求额度")

    confirmation = await require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=data.context_confirmation_id,
    )
    root_request = root.request_json or {}
    confirmation_scope_request = SimpleNamespace(
        scene_id=str(root.scene_id),
        character_ids=list(root_request.get("character_ids") or []),
        related_object_ids=list(root_request.get("related_object_ids") or []),
    )
    _validate_confirmation_scope(confirmation.compile_options, confirmation_scope_request)
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=data.context_confirmation_id,
    )
    pending = branch.pending_round_json or {}
    frozen_source = pending.get("source_snapshot")
    if not isinstance(frozen_source, dict):
        latest = await db.scalar(
            select(StorySceneDirectorRound)
            .where(
                StorySceneDirectorRound.novel_id == UUID(novel_id),
                StorySceneDirectorRound.branch_id == branch.id,
            )
            .order_by(StorySceneDirectorRound.round_number.desc())
            .limit(1)
        )
        frozen_source = (
            (latest.input_json or {}).get("source_snapshot") if latest else None
        )
    if not isinstance(frozen_source, dict):
        raise ConflictError("暂停分支缺少可恢复的来源快照，请重新开始排演")
    require_director_confirmation_scope(
        frozen_source, director_confirmation_scope(confirmed)
    )
    current_source = await read_director_source(
        db,
        novel_id=novel_id,
        scene_id=str(root.scene_id),
        character_ids=confirmation_scope_request.character_ids,
        related_object_ids=confirmation_scope_request.related_object_ids,
    )
    current_source = await scope_director_source(db, current_source, confirmed)
    if current_source["source_hash"] != frozen_source.get("source_hash"):
        raise ConflictError("场景或已确认资料在暂停后发生变化，请重新开始排演")

    reason = (
        AIRunAuthorizationReason.duplicate_charge_confirmed
        if raw.requests_unknown
        else AIRunAuthorizationReason.author_resume
    )
    await envelope.authorize_additional_requests(
        data.additional_requests,
        reason=reason,
        additional_tokens=data.additional_tokens,
    )
    updated_snapshot = envelope.snapshot()
    previous_envelope, previous_root_status = root.run_envelope_json, root.status
    previous_branch_status = branch.status
    root.run_envelope_json = updated_snapshot.model_dump(mode="json")
    root.status = "queued"
    branch.status = "queued"
    await db.flush()
    meta = {
        "meta_version": 1,
        "request": request_payload,
        "action": STORY_ONE_CLICK_ACTION,
        "director_root_id": root_id,
        "director_branch_id": str(branch.id),
        "director_resume_pending_hash": director_pending_checkpoint_hash(branch),
        "director_authorized_requests": data.additional_requests,
        "director_authorized_tokens": data.additional_tokens,
        "director_deadline_seconds": max(
            1,
            int(
                (
                    updated_snapshot.deadline_at - updated_snapshot.started_at
                ).total_seconds()
            )
            if updated_snapshot.deadline_at
            else 3600,
        ),
        "director_acknowledged_unknown_requests": updated_snapshot.requests_unknown,
        "director_baseline_requests_started": updated_snapshot.requests_started,
        "director_baseline_recent_attempts_overflow": (
            updated_snapshot.recent_attempts_overflow
        ),
        "llm_execution_snapshot": root.llm_execution_snapshot_json,
        AI_RUN_ENVELOPE_KEY: updated_snapshot.model_dump(mode="json"),
    }
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=str(data.operation_id),
        task_type=STORY_SCENE_DIRECTOR_TASK,
        novel_id=novel_id,
        request_payload=fingerprint_payload,
        meta=meta,
    )
    if receipt.reused:
        root.run_envelope_json = previous_envelope
        root.status = previous_root_status
        branch.status = previous_branch_status
        await db.flush()
        return _response_for_task(receipt.task_id, receipt.status, root_id)
    root.current_task_id = UUID(str(receipt.task_id))
    branch.current_task_id = UUID(str(receipt.task_id))
    await attach_result_ref(
        db,
        novel_id=novel_id,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=receipt.task_id,
        status="running",
    )
    await db.flush()
    return _response_for_task(receipt.task_id, receipt.status, root_id)


@router.post(
    "/scenes/director/budget-preview",
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.preview",
        "x-novelcraft-operation-trace-fields": _trace_fields(
            DirectorBudgetPreviewRequest
        ),
    },
)
async def api_director_budget_preview(data: DirectorBudgetPreviewRequest, db: DbSession):
    await require_active_project(db, data.novel_id)
    try:
        source = await _source_for_start(db, data)
        return preview_director_budget(data, source)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/scenes/{scene_id}/director",
    response_model=DirectorTaskAccepted,
    status_code=http_status.HTTP_202_ACCEPTED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.start",
        "x-novelcraft-operation-trace-fields": _trace_fields(DirectorStartRequest),
    },
)
async def api_start_director(scene_id: str, data: DirectorStartRequest, db: DbSession):
    await require_active_project(db, data.novel_id)
    if scene_id != data.scene_id:
        raise HTTPException(status_code=400, detail="Scene 路径与请求不一致")
    try:
        return await submit_director_start(db, data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/roots/{root_id}/budget-preview",
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.continue_preview",
        "x-novelcraft-operation-trace-fields": _trace_fields(
            DirectorContinueBudgetPreviewRequest
        ),
    },
)
async def api_director_continue_preview(
    root_id: str,
    data: DirectorContinueBudgetPreviewRequest,
    db: DbSession,
):
    await require_active_project(db, data.novel_id)
    try:
        if data.resume_branch_id is not None:
            from modules.story.director_operations import _continuation_preview

            _root, _parent, preview = await _continuation_preview(db, data.novel_id, data)
            if str(_root.id) != root_id:
                raise ValueError("待恢复分支不属于这个导演运行")
            return preview
        root = await get_director_root(db, data.novel_id, root_id)
        parent, _ = await get_director_round(db, data.novel_id, str(data.parent_round_id))
        if str(parent.root_id) != str(root.id):
            raise ValueError("所选回合不属于这个导演运行")
        request_json = root.request_json or {}
        current_source = await read_director_source(
            db,
            novel_id=data.novel_id,
            scene_id=str(root.scene_id),
            character_ids=list(request_json.get("character_ids") or []),
            related_object_ids=list(request_json.get("related_object_ids") or []),
        )
        frozen_source = (parent.input_json or {}).get("source_snapshot")
        if not isinstance(frozen_source, dict):
            raise ValueError("所选回合缺少可恢复的来源快照")
        source = current_source if data.basis_choice == "current" else frozen_source
        if data.branch_kind == "rewrite_character":
            performances = (parent.output_json or {}).get("performances") or []
            if data.rewrite_character_id not in {
                item.get("character_id") for item in performances
            }:
                raise ValueError("单人物重写对象不在所选回合")
        effective_intervention = data.intervention
        if data.selected_alternative:
            selected_alternative = next(
                (
                    item
                    for item in (parent.output_json or {}).get("alternatives", [])
                    if item.get("alternative_id") == data.selected_alternative
                ),
                None,
            )
            if selected_alternative is None:
                raise ValueError("所选分支方案不属于这个回合")
            effective_intervention = "\n\n".join(
                item
                for item in (
                    effective_intervention.strip(),
                    str(selected_alternative.get("branch_instruction") or "").strip(),
                )
                if item
            )
        if data.branch_kind == "intervene" and not effective_intervention.strip():
            raise ValueError("介入分支请先写明本次调整")
        request = _preview_request(
            scene_id=str(root.scene_id),
            character_ids=list(request_json.get("character_ids") or []),
            related_object_ids=list(request_json.get("related_object_ids") or []),
            primary_character_ids=list(request_json.get("primary_character_ids") or []),
            rounds=data.rounds,
            instructions=data.instructions,
            intervention=effective_intervention,
            public_stimulus=data.public_stimulus,
            selected_alternative=data.selected_alternative,
        )
        preview = preview_director_continuation(
            SimpleNamespace(
                **request.__dict__,
                branch_kind=data.branch_kind,
                basis_choice=data.basis_choice,
                rewrite_character_id=data.rewrite_character_id,
            ),
            source,
            parent_round_id=str(parent.id),
        )
        envelope = read_ai_run_envelope(root.run_envelope_json)
        snapshot = envelope.model_dump(mode="json") if envelope is not None else {}
        preview["current_budget"] = {
            "requests_used": int(snapshot.get("requests_started") or 0),
            "requests_authorized": snapshot.get("request_limit"),
            "tokens_used": int((snapshot.get("usage") or {}).get("total_tokens") or 0),
            "tokens_authorized": snapshot.get("token_limit"),
            "unknown_requests": int(snapshot.get("requests_unknown") or 0),
            "started_at": snapshot.get("started_at"),
            "deadline_at": snapshot.get("deadline_at"),
        }
        return preview
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/roots/{root_id}/advance",
    response_model=DirectorTaskAccepted,
    status_code=http_status.HTTP_202_ACCEPTED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.advance",
        "x-novelcraft-operation-trace-fields": _trace_fields(DirectorAdvanceRequest),
    },
)
async def api_advance_director(
    root_id: str,
    data: DirectorAdvanceRequest,
    db: DbSession,
):
    await require_active_project(db, data.novel_id)
    try:
        return await continue_director_root(db, root_id=root_id, data=data)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/roots/{root_id}/branches",
    response_model=DirectorTaskAccepted,
    status_code=http_status.HTTP_202_ACCEPTED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.continue",
        "x-novelcraft-operation-trace-fields": _trace_fields(DirectorContinueRequest),
    },
)
async def api_continue_director(
    root_id: str,
    data: DirectorContinueRequest,
    db: DbSession,
):
    await require_active_project(db, data.novel_id)
    if (
        data.resume_branch_id is None
        and not (data.additional_requests or data.additional_tokens)
        and data.rounds == 1
    ):
        raise HTTPException(
            status_code=400, detail="单轮且不追加额度请使用原预算推进入口"
        )
    try:
        return await continue_director_root(db, root_id=root_id, data=data)
    except Exception as error:
        raise _raise_http(error) from error


@router.get(
    "/scenes/{scene_id}/director/history",
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.history",
        "x-novelcraft-operation-trace-fields": {
            "novel_id": "novel_id",
            "scene_id": "scene_id",
        },
    },
)
async def api_director_history(
    scene_id: str, db: DbSession, *, novel_id: str = Query(...)
):
    await require_active_project(db, novel_id)
    try:
        return await read_director_history_view(db, novel_id, scene_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.get(
    "/director/rounds/{round_id}/consistency",
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.check_consistency",
        "x-novelcraft-operation-trace-fields": {
            "novel_id": "novel_id",
            "round_id": "round_id",
        },
    },
)
async def api_director_consistency(
    round_id: str, db: DbSession, *, novel_id: str = Query(...)
):
    await require_active_project(db, novel_id)
    try:
        return await recheck_director_round_consistency(db, novel_id, round_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.patch(
    "/director/rounds/{round_id}",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only history labels, notes and star state for the Scene Director; "
            "this UI mutation does not invoke an assistant operation."
        )
    },
)
async def api_update_director_round(
    round_id: str, data: DirectorUpdateMetadata, db: DbSession
):
    await require_active_project(db, data.novel_id)
    try:
        return await save_round_metadata(
            db, data.novel_id, round_id, data.model_dump(exclude={"novel_id"})
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.patch(
    "/director/branches/{branch_id}",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only history labels, notes and star state for the Scene Director; "
            "this UI mutation does not invoke an assistant operation."
        )
    },
)
async def api_update_director_branch(
    branch_id: str, data: DirectorUpdateMetadata, db: DbSession
):
    await require_active_project(db, data.novel_id)
    try:
        branch = await get_director_branch(db, data.novel_id, branch_id, lock=True)
        changes = data.model_dump(exclude={"novel_id"})
        if changes.get("starred") is not None:
            branch.starred = changes["starred"]
        if changes.get("name") is not None:
            branch.name = changes["name"].strip() or None
        if changes.get("note") is not None:
            branch.note = changes["note"]
        await db.flush()
        return {
            "id": str(branch.id),
            "starred": branch.starred,
            "name": branch.name,
            "note": branch.note,
        }
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/branches/{branch_id}/delete",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Explicit author UI deletion of one Scene Director history branch with "
            "a 30-day restore window; AI operations cannot delete history."
        )
    },
)
async def api_delete_director_branch(
    branch_id: str, data: DirectorDeleteBranchRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    if not data.confirm:
        raise HTTPException(status_code=400, detail="请先确认将删除此分支及其历史引用")
    try:
        branch = await get_director_branch(db, data.novel_id, branch_id)
        root = await get_director_root(db, data.novel_id, str(branch.root_id), lock=True)
        branch = await get_director_branch(db, data.novel_id, branch_id, lock=True)
        await _require_root_idle(db, root)
        return await delete_director_branch(db, data.novel_id, branch_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/branches/{branch_id}/restore",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Explicit author UI restoration of a deleted Scene Director branch "
            "during its 30-day recovery window."
        )
    },
)
async def api_restore_director_branch(
    branch_id: str, data: DirectorMutationRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    try:
        return await restore_director_branch(db, data.novel_id, branch_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/scenes/{scene_id}/director/delete-unstarred",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Explicit author UI batch deletion of unstarred Scene Director branches "
            "with recovery; AI operations cannot delete history."
        )
    },
)
async def api_delete_unstarred_director_branches(
    scene_id: str,
    data: DirectorDeleteUnstarredRequest,
    db: DbSession,
):
    await require_active_project(db, data.novel_id)
    if scene_id != data.scene_id:
        raise HTTPException(status_code=400, detail="Scene 路径与请求不一致")
    if not data.confirm:
        raise HTTPException(
            status_code=400, detail="请先确认将删除本场所有未星标导演分支"
        )
    try:
        roots = list(
            (
                await db.scalars(
                    select(StorySceneDirectorRoot)
                    .where(
                        StorySceneDirectorRoot.novel_id == UUID(data.novel_id),
                        StorySceneDirectorRoot.scene_id == UUID(data.scene_id),
                    )
                    .with_for_update()
                )
            ).all()
        )
        for root in roots:
            await _require_root_idle(db, root)
        return await delete_unstarred_director_branches(db, data.novel_id, data.scene_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/rounds/{round_id}/references",
    status_code=http_status.HTTP_201_CREATED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.save_reference",
        "x-novelcraft-operation-trace-fields": _trace_fields(
            DirectorSaveReferenceRequest
        ),
    },
)
async def api_save_director_reference(
    round_id: str, data: DirectorSaveReferenceRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    if str(data.source_round_id) != round_id:
        raise HTTPException(status_code=400, detail="来源回合路径与请求不一致")
    try:
        row, _branch = await get_director_round(db, data.novel_id, round_id)
        return await save_director_reference(db, data.novel_id, data)
    except Exception as error:
        raise _raise_http(error) from error


@router.patch(
    "/director/references/{reference_id}",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only edits to the name and handwritten annotation of a copied "
            "Scene Director reference."
        )
    },
)
async def api_update_director_reference(
    reference_id: str, data: DirectorReferenceUpdate, db: DbSession
):
    await require_active_project(db, data.novel_id)
    try:
        return await update_reference_metadata(
            db,
            data.novel_id,
            reference_id,
            annotation=data.annotation,
            name=data.name,
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/references/{reference_id}/delete",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Explicit author UI soft-deletion of a copied Scene Director reference "
            "with a 30-day restore window."
        )
    },
)
async def api_delete_director_reference(
    reference_id: str, data: DirectorMutationRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    try:
        return await delete_director_reference(db, data.novel_id, reference_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/references/{reference_id}/restore",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Explicit author UI restoration of a deleted Scene Director reference "
            "during its 30-day recovery window."
        )
    },
)
async def api_restore_director_reference(
    reference_id: str,
    data: DirectorMutationRequest,
    db: DbSession,
):
    await require_active_project(db, data.novel_id)
    try:
        return await restore_director_reference(db, data.novel_id, reference_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.get(
    "/director/preferences",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only read of the project-local Scene Director phrase-list preference."
        )
    },
)
async def api_get_director_preferences(db: DbSession, *, novel_id: str = Query(...)):
    await require_active_project(db, novel_id)
    return await get_director_preferences(db, novel_id)


@router.put(
    "/director/preferences",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only project preference update for the Scene Director's "
            "editable phrase list."
        )
    },
)
async def api_set_director_preferences(data: DirectorPreferenceUpdate, db: DbSession):
    await require_active_project(db, data.novel_id)
    try:
        return await set_director_preferences(db, data.novel_id, data.cliche_phrases)
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/director/rounds/{round_id}/world-candidates",
    response_model=DirectorCandidateTransferReceipt,
    status_code=http_status.HTTP_201_CREATED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.scene_director.transfer_world_candidate",
        "x-novelcraft-operation-phase": "execute",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            **_trace_fields(DirectorCandidateTransferRequest),
            "round_id": "round_id",
        },
    },
)
async def api_transfer_director_candidate(
    round_id: str, data: DirectorCandidateTransferRequest, db: DbSession
):
    await require_active_project(db, data.novel_id, allow_demo_readonly=False)
    try:
        return await transfer_director_candidate(db, round_id, data)
    except Exception as error:
        raise _raise_http(error) from error
