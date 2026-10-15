"""Author routes for the isolated candidate world-progression workflow."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.dependencies import DbSession
from core.errors import ConflictError, NotFoundError
from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY, read_ai_run_envelope
from infrastructure.llm.workflow_budget import new_ai_run_envelope
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from infrastructure.tasks.models import AsyncTask
from modules.evidence.facade import (
    attach_result_ref,
    require_fresh_confirmation,
)
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.world_progression_budget import preview_progression_budget
from modules.story.world_progression_context import read_progression_source
from modules.story.world_progression_continuous import (
    read_continuous_authorization,
    set_continuous_authorization,
)
from modules.story.world_progression_hooks import router as _hook_router
from modules.story.world_progression_models import (
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
)
from modules.story.world_progression_schemas import (
    ProgressionAdvanceRequest,
    ProgressionBudgetPreviewRequest,
    ProgressionCompareRequest,
    ProgressionContinuousAuthorizationRequest,
    ProgressionDeleteRequest,
    ProgressionMetadataRequest,
    ProgressionStartRequest,
)
from modules.story.world_progression_service import (
    compare_progression_steps,
    delete_progression_branch,
    get_progression_branch,
    get_progression_root,
    get_progression_step,
    list_root_metrics,
    read_progression_history,
    restore_progression_branch,
    update_branch_metadata,
)
from modules.story.world_progression_tasks import (
    WORLD_PROGRESSION_CAPABILITY,
    WORLD_PROGRESSION_TASK,
)

router = APIRouter(
    prefix="/api/story/world-progression", tags=["story-world-progression"]
)


def feature_enabled() -> bool:
    return os.getenv("STORY_WORLD_PROGRESSION_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _enabled() -> None:
    if not feature_enabled():
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="世界推进尚未开启",
        )


def _trace_fields(schema: type) -> dict[str, str]:
    return {field: f"data.{field}" for field in schema.model_fields}


def _raise_http(error: Exception) -> HTTPException:
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ConflictError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="世界推进暂时无法完成该操作，请稍后重试。",
    )


def _model_name(snapshot: dict) -> str:
    return str((snapshot.get("profile") or {}).get("model") or "unknown")


async def _source_for_request(db, data, *, snapshot=None) -> dict:
    source = await read_progression_source(
        db,
        novel_id=data.novel_id,
        scene_id=data.scene_id,
        participants=data.participants,
        targets=data.targets,
    )
    if snapshot is not None:
        source["llm_execution_snapshot"] = snapshot
    return source


def _validate_confirmation_scope(options: dict, data, scene_id: str) -> None:
    if str(options.get("scene_id") or "") != str(scene_id):
        raise ConflictError("资料确认的 Scene 与世界推进截止点不一致")
    expected_characters = {
        item.id for item in data.participants if item.kind == "character"
    }
    actual_characters = set(map(str, options.get("character_ids") or []))
    if actual_characters != expected_characters:
        raise ConflictError("请在资料确认中重新选择本次参与人物")
    expected_groups = {item.id for item in data.participants if item.kind == "group"}
    actual_entities = set(map(str, options.get("entity_ids") or []))
    if not expected_groups <= actual_entities:
        raise ConflictError("群体身份不在已确认的资料范围内")


def _response(task_id: str, state: str, root_id: str, branch_id: str) -> dict:
    return {
        "task_id": str(task_id),
        "status": state,
        "root_id": str(root_id),
        "branch_id": str(branch_id),
    }


async def _existing_task(db, *, operation_id, novel_id, request_payload):
    return await get_operation_task(
        db,
        operation_id=str(operation_id),
        task_type=WORLD_PROGRESSION_TASK,
        novel_id=novel_id,
        request_payload=request_payload,
    )


def _task_meta(*, request, root_id, branch_id, execution_snapshot, envelope):
    snapshot = envelope.snapshot().model_dump(mode="json")
    return {
        "meta_version": 1,
        "request": request,
        "world_progression_root_id": str(root_id),
        "world_progression_branch_id": str(branch_id),
        "world_progression_authorized_requests": int(snapshot["request_limit"]),
        "world_progression_authorized_tokens": int(snapshot["token_limit"]),
        "world_progression_deadline_seconds": max(
            1,
            int((envelope.deadline_at - envelope.started_at).total_seconds())
            if envelope.deadline_at
            else 3600,
        ),
        "llm_execution_snapshot": execution_snapshot,
        AI_RUN_ENVELOPE_KEY: snapshot,
    }


async def _enqueue_existing_root(
    db,
    *,
    root: StoryWorldProgressionRoot,
    branch: StoryWorldProgressionBranch,
    operation_id: str,
    request_payload: dict,
    meta_request: dict,
    execution_snapshot: dict,
    envelope,
    confirmation_id: str | None,
):
    meta = _task_meta(
        request=meta_request,
        root_id=root.id,
        branch_id=branch.id,
        execution_snapshot=execution_snapshot,
        envelope=envelope,
    )
    receipt = await enqueue_task_with_optional_operation(
        db,
        operation_id=operation_id,
        task_type=WORLD_PROGRESSION_TASK,
        novel_id=str(root.novel_id),
        request_payload=request_payload,
        meta=meta,
    )
    if receipt.reused:
        existing_task = await db.get(AsyncTask, UUID(str(receipt.task_id)))
        existing_meta = dict(existing_task.meta or {}) if existing_task else {}
        existing_root = str(existing_meta.get("world_progression_root_id") or "")
        existing_branch = str(existing_meta.get("world_progression_branch_id") or "")
        if existing_root != str(root.id) or not existing_branch:
            raise ConflictError("相同操作已被接受，但无法恢复其世界推进分支")
        if existing_branch != str(branch.id):
            await db.delete(branch)
        return _response(receipt.task_id, receipt.status, existing_root, existing_branch)
    root.current_task_id = UUID(str(receipt.task_id))
    branch.current_task_id = UUID(str(receipt.task_id))
    root.status = branch.status = "queued"
    if confirmation_id:
        await attach_result_ref(
            db,
            novel_id=str(root.novel_id),
            confirmation_id=confirmation_id,
            result_type="task",
            result_id=str(receipt.task_id),
            status="running",
        )
    await db.flush()
    return _response(receipt.task_id, receipt.status, str(root.id), str(branch.id))


@router.post(
    "/budget-preview",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.preview",
        "x-novelcraft-operation-trace-fields": _trace_fields(
            ProgressionBudgetPreviewRequest
        ),
    },
)
async def api_progression_budget_preview(
    data: ProgressionBudgetPreviewRequest, db: DbSession
):
    _enabled()
    await require_active_project(db, data.novel_id)
    try:
        snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
        source = await _source_for_request(db, data, snapshot=snapshot)
        metrics = await list_root_metrics(db, data.novel_id)
        result = preview_progression_budget(
            data,
            source,
            model_name=_model_name(snapshot),
            metrics=metrics,
        )
        return result
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/roots",
    status_code=http_status.HTTP_202_ACCEPTED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.start",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionStartRequest),
    },
)
async def api_start_progression(data: ProgressionStartRequest, db: DbSession):
    _enabled()
    await require_active_project(db, data.novel_id)
    request_payload = data.model_dump(mode="json", exclude={"operation_id"})
    try:
        existing = await _existing_task(
            db,
            operation_id=data.operation_id,
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            row = await db.get(AsyncTask, UUID(str(existing.task_id)))
            meta = dict(row.meta or {}) if row else {}
            root_id = str(meta.get("world_progression_root_id") or "")
            branch_id = str(meta.get("world_progression_branch_id") or "")
            if not root_id or not branch_id:
                raise ConflictError("相同操作已被接受，但根或分支不可恢复")
            return _response(existing.task_id, existing.status, root_id, branch_id)

        snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
        source = await _source_for_request(db, data, snapshot=snapshot)
        preview = preview_progression_budget(
            data,
            source,
            model_name=_model_name(snapshot),
            metrics=await list_root_metrics(db, data.novel_id),
        )
        if preview["preview_hash"] != data.budget_preview_hash:
            raise ConflictError("世界、参与者或预算选择已变化，请重新预览")
        confirmation = await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=STORY_ONE_CLICK_ACTION,
            confirmation_id=data.context_confirmation_id,
        )
        _validate_confirmation_scope(
            dict(confirmation.compile_options or {}), data, source["scene_id"]
        )
        # Pin the resolved author cutoff, even when the UI requested "latest".
        root_request = data.model_dump(mode="json")
        root_request["scene_id"] = source["scene_id"]
        root_id, branch_id = uuid4(), uuid4()
        started_at = datetime.now(UTC)
        envelope = new_ai_run_envelope(
            operation_id=str(data.operation_id),
            run_id=str(root_id),
            root_capability_id=WORLD_PROGRESSION_CAPABILITY,
            novel_id=data.novel_id,
            request_limit=data.request_limit,
            budget_mode="bounded",
            token_limit=data.token_limit,
            deadline_at=started_at + timedelta(seconds=data.time_budget_seconds),
            started_at=started_at,
        )
        root = StoryWorldProgressionRoot(
            id=root_id,
            novel_id=UUID(data.novel_id),
            scene_id=UUID(source["scene_id"]),
            source_hash=source["source_hash"],
            request_json=root_request,
            source_snapshot_json=source,
            llm_execution_snapshot_json=snapshot,
            run_envelope_json=envelope.snapshot().model_dump(mode="json"),
            context_confirmation_id=data.context_confirmation_id,
            status="queued",
        )
        branch = StoryWorldProgressionBranch(
            id=branch_id,
            novel_id=UUID(data.novel_id),
            root_id=root_id,
            parent_step_id=None,
            branch_kind="start",
            basis_choice="current",
            source_hash=source["source_hash"],
            request_json={},
            source_snapshot_json=source,
            status="queued",
        )
        db.add_all([root, branch])
        await db.flush()
        task_response = await _enqueue_existing_root(
            db,
            root=root,
            branch=branch,
            operation_id=str(data.operation_id),
            request_payload=request_payload,
            meta_request={"context_confirmation_id": data.context_confirmation_id},
            execution_snapshot=snapshot,
            envelope=envelope,
            confirmation_id=data.context_confirmation_id,
        )
        return task_response
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/roots/{root_id}/steps",
    status_code=http_status.HTTP_202_ACCEPTED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.advance",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionAdvanceRequest),
    },
)
async def api_advance_progression(
    root_id: str, data: ProgressionAdvanceRequest, db: DbSession
):
    _enabled()
    await require_active_project(db, data.novel_id)
    fingerprint_request = data.model_dump(mode="json", exclude={"operation_id"})
    try:
        existing = await _existing_task(
            db,
            operation_id=data.operation_id,
            novel_id=data.novel_id,
            request_payload=fingerprint_request,
        )
        if existing is not None:
            row = await db.get(AsyncTask, UUID(str(existing.task_id)))
            meta = dict(row.meta or {}) if row else {}
            branch_id = str(meta.get("world_progression_branch_id") or "")
            if (
                str(meta.get("world_progression_root_id") or "") != root_id
                or not branch_id
            ):
                raise ConflictError("相同操作已被接受，但推进分支不可恢复")
            return _response(existing.task_id, existing.status, root_id, branch_id)

        root = await get_progression_root(db, data.novel_id, root_id, lock=True)
        parent = await get_progression_step(db, data.novel_id, str(data.parent_step_id))
        if str(parent.root_id) != root_id:
            raise ConflictError("所选父步骤不属于该世界推进根")
        if str(parent.branch_id) != str(data.branch_id):
            raise ConflictError("所选父步骤与请求分支身份不一致")
        if root.current_task_id is not None:
            active = await db.get(AsyncTask, root.current_task_id)
            if active is not None and active.status in {"pending", "running"}:
                raise ConflictError("该推进根仍在运行，请等待当前步骤完成")
            root.current_task_id = None
        raw_envelope = read_ai_run_envelope(root.run_envelope_json)
        if (
            raw_envelope is None
            or raw_envelope.run_id != root_id
            or raw_envelope.root_capability_id != WORLD_PROGRESSION_CAPABILITY
        ):
            raise ConflictError("累计预算账本不可恢复，已停止续算")
        if raw_envelope.requests_unknown or not raw_envelope.usage_complete:
            raise ConflictError("此前请求用量未知，不能在未核对账本时继续")
        if raw_envelope.requests_started / max(1, raw_envelope.request_limit) >= 0.8:
            raise ConflictError("原运行已达到 80% 请求额度，不能继续追加步骤")
        if raw_envelope.usage.total_tokens / max(1, raw_envelope.token_limit) >= 0.8:
            raise ConflictError("原运行已达到 80% Token 额度，不能继续追加步骤")

        root_request = dict(root.request_json or {})
        participants = [item for item in root_request.get("participants") or []]
        from modules.story.world_progression_schemas import (
            ProgressionParticipant,
            ProgressionTarget,
        )

        participant_models = [
            ProgressionParticipant.model_validate(item) for item in participants
        ]
        targets = [
            ProgressionTarget.model_validate(item)
            for item in root_request.get("targets") or []
        ]
        current_source = await read_progression_source(
            db,
            novel_id=data.novel_id,
            scene_id=root_request.get("scene_id"),
            participants=participant_models,
            targets=targets,
        )
        selected_branch = await get_progression_branch(
            db, data.novel_id, str(data.branch_id), lock=True
        )
        if str(selected_branch.root_id) != root_id:
            raise ConflictError("所选分支不属于该世界推进根")
        if selected_branch.deleted_at is not None:
            raise ConflictError("已删除分支不能继续")
        frozen_source = dict(
            selected_branch.source_snapshot_json or root.source_snapshot_json or {}
        )
        source = current_source if data.basis_choice == "current" else frozen_source
        if not source:
            raise ConflictError("所选历史没有可恢复的依据快照")
        confirmation = await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=STORY_ONE_CLICK_ACTION,
            confirmation_id=data.context_confirmation_id,
        )
        _validate_confirmation_scope(
            dict(confirmation.compile_options or {}),
            type("Selection", (), {"participants": participant_models})(),
            source["scene_id"],
        )
        execution_snapshot = root.llm_execution_snapshot_json
        envelope = __import__(
            "infrastructure.llm.workflow_budget", fromlist=["AIRunEnvelope"]
        ).AIRunEnvelope(raw_envelope)
        branch_id = uuid4()
        branch = StoryWorldProgressionBranch(
            id=branch_id,
            novel_id=UUID(data.novel_id),
            root_id=UUID(root_id),
            parent_step_id=parent.id,
            branch_kind="continue",
            basis_choice=data.basis_choice,
            source_hash=source["source_hash"],
            request_json={
                "scene_id": source["scene_id"],
                "step_length": data.step_length
                or root_request.get("step_length", "auto"),
                "run_policy": "one_step",
                "steps": None,
                "mode": root_request.get("mode", "free"),
                "targets": root_request.get("targets", []),
                "instructions": root_request.get("instructions", ""),
                "retained_constraints": root_request.get("retained_constraints", []),
                "stop_at_goal": root_request.get("stop_at_goal", True),
            },
            source_snapshot_json=source,
            status="queued",
        )
        db.add(branch)
        root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
        await db.flush()
        return await _enqueue_existing_root(
            db,
            root=root,
            branch=branch,
            operation_id=str(data.operation_id),
            request_payload=fingerprint_request,
            meta_request={"context_confirmation_id": data.context_confirmation_id},
            execution_snapshot=execution_snapshot,
            envelope=envelope,
            confirmation_id=data.context_confirmation_id,
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.get(
    "/history",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.history",
        "x-novelcraft-operation-trace-fields": {
            "novel_id": "novel_id",
            "scene_id": "scene_id",
            "root_id": "root_id",
        },
    },
)
async def api_progression_history(
    db: DbSession,
    *,
    novel_id: str = Query(...),
    scene_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
):
    _enabled()
    await require_active_project(db, novel_id)
    try:
        return await read_progression_history(
            db, novel_id, scene_id=scene_id, root_id=root_id
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/branches/{branch_id}/metadata",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.edit_history",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionMetadataRequest),
    },
)
async def api_progression_metadata(
    branch_id: str, data: ProgressionMetadataRequest, db: DbSession
):
    _enabled()
    await require_active_project(db, data.novel_id)
    changes = data.model_dump(include={"name", "note", "starred"}, exclude_unset=True)
    try:
        return await update_branch_metadata(
            db,
            novel_id=data.novel_id,
            branch_id=branch_id,
            changes=changes,
            expected_updated_at=data.expected_updated_at,
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/branches/{branch_id}/delete",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.delete_history",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionDeleteRequest),
    },
)
async def api_delete_progression_branch(
    branch_id: str, data: ProgressionDeleteRequest, db: DbSession
):
    _enabled()
    await require_active_project(db, data.novel_id)
    if not data.confirm:
        raise HTTPException(status_code=400, detail="请确认将该分支移入 30 天恢复区")
    try:
        branch = await get_progression_branch(db, data.novel_id, branch_id)
        root = await get_progression_root(
            db, data.novel_id, str(branch.root_id), lock=True
        )
        branch = await get_progression_branch(db, data.novel_id, branch_id, lock=True)
        if branch.current_task_id or root.current_task_id:
            raise ConflictError("运行中的历史不能删除")
        return await delete_progression_branch(
            db, novel_id=data.novel_id, branch_id=branch_id
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/branches/{branch_id}/restore",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.restore_history",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionDeleteRequest),
    },
)
async def api_restore_progression_branch(
    branch_id: str, data: ProgressionDeleteRequest, db: DbSession
):
    _enabled()
    await require_active_project(db, data.novel_id)
    try:
        return await restore_progression_branch(
            db, novel_id=data.novel_id, branch_id=branch_id
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/compare",
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.compare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionCompareRequest),
    },
)
async def api_compare_progression_steps(data: ProgressionCompareRequest, db: DbSession):
    _enabled()
    try:
        novel_id = data.novel_id
        await require_active_project(db, novel_id)
        return await compare_progression_steps(
            db,
            novel_id=novel_id,
            first_step_id=str(data.first_step_id),
            second_step_id=str(data.second_step_id),
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.get(
    "/roots/{root_id}/branches/{branch_id}/continuous-authorization",
    openapi_extra={
        "x-novelcraft-operation-id": (
            "story.world_progression.read_continuous_authorization"
        ),
        "x-novelcraft-operation-trace-fields": {
            "novel_id": "novel_id",
            "root_id": "root_id",
            "branch_id": "branch_id",
        },
    },
)
async def api_read_continuous_authorization(
    root_id: str,
    branch_id: str,
    db: DbSession,
    *,
    novel_id: str = Query(...),
):
    _enabled()
    await require_active_project(db, novel_id)
    try:
        root = await get_progression_root(db, novel_id, root_id)
        branch = await get_progression_branch(db, novel_id, branch_id)
        if str(branch.root_id) != str(root.id):
            raise ConflictError("分支不属于当前推进根")
        result = await read_continuous_authorization(db, novel_id)
        if result.get("root_id") not in {None, str(root.id)}:
            raise ConflictError("持续授权已绑定到另一条推进根")
        return result
    except Exception as error:
        raise _raise_http(error) from error


@router.put(
    "/roots/{root_id}/branches/{branch_id}/continuous-authorization",
    openapi_extra={
        "x-novelcraft-operation-id": (
            "story.world_progression.set_continuous_authorization"
        ),
        "x-novelcraft-operation-trace-fields": _trace_fields(
            ProgressionContinuousAuthorizationRequest
        ),
    },
)
async def api_set_continuous_authorization(
    root_id: str,
    branch_id: str,
    data: ProgressionContinuousAuthorizationRequest,
    db: DbSession,
):
    _enabled()
    await require_active_project(db, data.novel_id)
    try:
        root = await get_progression_root(db, data.novel_id, root_id, lock=True)
        branch = await get_progression_branch(db, data.novel_id, branch_id, lock=True)
        return await set_continuous_authorization(db, root=root, branch=branch, data=data)
    except Exception as error:
        raise _raise_http(error) from error


# Keep one router at the Story application boundary while the two modules stay
# independently testable.
router.include_router(_hook_router)
