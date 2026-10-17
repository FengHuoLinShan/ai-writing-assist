"""Author routes for the isolated candidate world-progression workflow."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select

from core.dependencies import DbSession
from core.errors import ConflictError, NotFoundError
from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.workflow_budget import AIRunEnvelope, new_ai_run_envelope
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from infrastructure.tasks.models import AsyncTask
from modules.evidence.facade import (
    attach_result_ref,
    prepare_confirmed_ai_action,
)
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story.generation import STORY_ONE_CLICK_ACTION
from modules.story.world_progression_budget import preview_progression_budget
from modules.story.world_progression_context import (
    _latest_written_scene,
    read_progression_source,
    scope_progression_source,
)
from modules.story.world_progression_continuous import (
    read_continuous_authorization,
    set_continuous_authorization,
)
from modules.story.world_progression_hooks_api import router as _hook_router
from modules.story.world_progression_models import (
    StoryWorldProgressionAuthorization,
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_schemas import (
    ProgressionAdvanceRequest,
    ProgressionBudgetPreviewRequest,
    ProgressionCompareRequest,
    ProgressionContinuousAuthorizationRequest,
    ProgressionDeleteRequest,
    ProgressionMetadataRequest,
    ProgressionParticipant,
    ProgressionResumeRequest,
    ProgressionStartRequest,
    ProgressionTarget,
)
from modules.story.world_progression_service import (
    compare_progression_steps,
    delete_progression_branch,
    get_progression_branch,
    get_progression_root,
    get_progression_step,
    list_root_metrics,
    progression_resume_hash,
    read_progression_history,
    restore_progression_branch,
    update_branch_metadata,
)
from modules.story.world_progression_tasks import (
    WORLD_PROGRESSION_CAPABILITY,
    WORLD_PROGRESSION_TASK,
    _budget_stop,
    _task_meta,
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
    if isinstance(error, ProjectLLMConfigurationError):
        return HTTPException(
            status_code=409,
            detail="请先在账户设置中连接并验证模型，再重新预览世界推进预算。",
        )
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(
        status_code=500,
        detail="世界推进暂时无法完成该操作，请稍后重试。",
    )


def _model_name(snapshot: dict) -> str:
    return str((snapshot.get("profile") or {}).get("model") or "unknown")


async def _source_for_request(db, data, *, snapshot=None):
    confirmation_id = str(getattr(data, "context_confirmation_id", "") or "")
    if not confirmation_id:
        raise ValueError("世界推进预算预览必须先确认本次资料范围")
    confirmed = await prepare_confirmed_ai_action(
        db,
        novel_id=data.novel_id,
        action=STORY_ONE_CLICK_ACTION,
        confirmation_id=confirmation_id,
    )
    source = await read_progression_source(
        db,
        novel_id=data.novel_id,
        scene_id=data.scene_id,
        participants=data.participants,
        targets=data.targets,
        confirmed_context=confirmed,
    )
    _validate_confirmation_scope(
        dict(confirmed.compile_options or {}), data, source["scene_id"]
    )
    if snapshot is not None:
        source["llm_execution_snapshot"] = snapshot
    return source, confirmed


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
        request={"novel_id": str(root.novel_id), **meta_request},
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
    await require_active_project(db, data.novel_id)
    _enabled()
    try:
        snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
        if not data.context_confirmation_id:
            scene_id = data.scene_id
            if scene_id is None:
                scene_id = str((await _latest_written_scene(db, data.novel_id))["id"])
            return {
                "requires_context_confirmation": True,
                "scene_id": scene_id,
            }
        source, _confirmed = await _source_for_request(db, data, snapshot=snapshot)
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
    await require_active_project(db, data.novel_id)
    _enabled()
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
        source, _confirmed = await _source_for_request(db, data, snapshot=snapshot)
        preview = preview_progression_budget(
            data,
            source,
            model_name=_model_name(snapshot),
            metrics=await list_root_metrics(db, data.novel_id),
        )
        if preview["preview_hash"] != data.budget_preview_hash:
            raise ConflictError("世界、参与者或预算选择已变化，请重新预览")
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
        # The models intentionally have no ORM relationship; flush the parent
        # before its composite (novel_id, root_id) child FK.
        db.add(root)
        await db.flush()
        db.add(branch)
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
    await require_active_project(db, data.novel_id)
    _enabled()
    if str(data.root_id) != root_id:
        raise HTTPException(status_code=409, detail="推进请求与所选运行不匹配")
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
        from modules.story.exploration_service import (
            require_legacy_progression_root,
        )

        require_legacy_progression_root(root)
        parent = await get_progression_step(db, data.novel_id, str(data.parent_step_id))
        if str(parent.root_id) != root_id:
            raise ConflictError("所选父步骤不属于该世界推进根")
        require_legacy_progression_root(root, parent)
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
        if stop := _budget_stop(AIRunEnvelope(raw_envelope)):
            raise ConflictError(f"原运行预算已暂停，不能继续追加步骤：{stop}")

        root_request = dict(root.request_json or {})
        participants = [item for item in root_request.get("participants") or []]
        participant_models = [
            ProgressionParticipant.model_validate(item) for item in participants
        ]
        targets = [
            ProgressionTarget.model_validate(item)
            for item in root_request.get("targets") or []
        ]
        confirmed = await prepare_confirmed_ai_action(
            db,
            novel_id=data.novel_id,
            action=STORY_ONE_CLICK_ACTION,
            confirmation_id=data.context_confirmation_id,
        )
        current_source = await read_progression_source(
            db,
            novel_id=data.novel_id,
            scene_id=root_request.get("scene_id"),
            participants=participant_models,
            targets=targets,
            confirmed_context=confirmed,
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
        source = (
            current_source
            if data.basis_choice == "current"
            else await scope_progression_source(
                db,
                frozen_source,
                confirmed.compiled,
                expected_novel_id=data.novel_id,
                expected_scene_id=str(root.scene_id),
            )
        )
        if not source:
            raise ConflictError("所选历史没有可恢复的依据快照")
        _validate_confirmation_scope(
            dict(confirmed.compile_options or {}),
            type("Selection", (), {"participants": participant_models})(),
            source["scene_id"],
        )
        execution_snapshot = root.llm_execution_snapshot_json
        envelope = AIRunEnvelope(raw_envelope)
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
                "stop_at_goal": root_request.get("stop_at_goal", False),
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


@router.post(
    "/roots/{root_id}/branches/{branch_id}/resume",
    status_code=http_status.HTTP_202_ACCEPTED,
    openapi_extra={
        "x-novelcraft-operation-id": "story.world_progression.resume",
        "x-novelcraft-operation-trace-fields": _trace_fields(ProgressionResumeRequest),
    },
)
async def api_resume_progression(
    root_id: str, branch_id: str, data: ProgressionResumeRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    _enabled()
    if str(data.root_id) != root_id or str(data.branch_id) != branch_id:
        raise HTTPException(status_code=409, detail="恢复请求与所选历史分支不匹配")
    request_payload = data.model_dump(mode="json", exclude={"operation_id"})
    try:
        existing = await _existing_task(
            db,
            operation_id=data.operation_id,
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            task = await db.get(AsyncTask, UUID(str(existing.task_id)))
            meta = dict(task.meta or {}) if task is not None else {}
            if (
                str(meta.get("world_progression_root_id") or "") != root_id
                or str(meta.get("world_progression_branch_id") or "") != branch_id
            ):
                raise ConflictError("重复恢复操作与原推进分支不匹配")
            return _response(existing.task_id, existing.status, root_id, branch_id)

        root = await get_progression_root(db, data.novel_id, root_id, lock=True)
        branch = await get_progression_branch(db, data.novel_id, branch_id, lock=True)
        if str(branch.root_id) != root_id:
            raise ConflictError("恢复分支不属于所选推进根")
        from modules.story.exploration_service import (
            require_legacy_progression_root,
        )

        require_legacy_progression_root(root)
        latest_step_id = await db.scalar(
            select(StoryWorldProgressionStep.id)
            .where(
                StoryWorldProgressionStep.novel_id == UUID(data.novel_id),
                StoryWorldProgressionStep.branch_id == branch.id,
            )
            .order_by(StoryWorldProgressionStep.step_number.desc())
            .limit(1)
        )
        if latest_step_id is not None:
            latest_step = await get_progression_step(
                db, data.novel_id, str(latest_step_id)
            )
            require_legacy_progression_root(root, latest_step)
        existing = await _existing_task(
            db,
            operation_id=data.operation_id,
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            task = await db.get(AsyncTask, UUID(str(existing.task_id)))
            meta = dict(task.meta or {}) if task is not None else {}
            if (
                str(meta.get("world_progression_root_id") or "") != root_id
                or str(meta.get("world_progression_branch_id") or "") != branch_id
            ):
                raise ConflictError("重复恢复操作与原推进分支不匹配")
            return _response(existing.task_id, existing.status, root_id, branch_id)
        if progression_resume_hash(root, branch) != data.resume_hash:
            raise ConflictError("预算或半步检查点已变化，请刷新历史后重新确认")
        if branch.stop_reason == "invalid_resolution":
            raise ConflictError("无效裁决不能重放；请从上一完整步骤明确创建新分支")
        if branch.status not in {
            "failed",
            "paused_unknown",
            "paused_budget",
            "running",
            "queued",
        }:
            raise ConflictError("这个分支没有可恢复的中断步骤")
        pending = dict(branch.pending_step_json or {})
        if not pending or not pending.get("source_hash"):
            raise ConflictError("分支缺少可恢复的持久检查点")
        for task_id in {root.current_task_id, branch.current_task_id} - {None}:
            prior = await db.get(AsyncTask, task_id)
            if prior is not None and prior.status in {"pending", "running"}:
                raise ConflictError("原世界推进任务仍在运行，不能并发恢复")

        raw = read_ai_run_envelope(root.run_envelope_json)
        if (
            raw is None
            or raw.run_id != root_id
            or raw.root_capability_id != WORLD_PROGRESSION_CAPABILITY
            or raw.novel_id != data.novel_id
        ):
            raise ConflictError("原根累计预算不可恢复")
        unknown = int(raw.requests_unknown)
        if data.acknowledge_unknown_requests != unknown:
            raise ConflictError("未知计费结果数量已变化，请刷新后重新确认")
        if unknown and not data.allow_possible_duplicate_charge:
            raise ConflictError("恢复前须明确确认当前未知请求可能重复计费")
        if not unknown and data.allow_possible_duplicate_charge:
            raise ConflictError("当前没有待确认的未知计费请求")
        envelope = AIRunEnvelope(raw)
        stop = _budget_stop(
            envelope,
            acknowledged_unknown=unknown if data.allow_possible_duplicate_charge else 0,
            baseline_requests_started=raw.requests_started,
        )
        if stop:
            raise ConflictError(f"原根预算已暂停，不能在当前授权下恢复：{stop}")

        request = {**dict(root.request_json or {}), **dict(branch.request_json or {})}
        participants = [
            ProgressionParticipant.model_validate(item)
            for item in request.get("participants") or []
        ]
        targets = [
            ProgressionTarget.model_validate(item)
            for item in request.get("targets") or []
        ]
        confirmed = await prepare_confirmed_ai_action(
            db,
            novel_id=data.novel_id,
            action=STORY_ONE_CLICK_ACTION,
            confirmation_id=data.context_confirmation_id,
        )
        source = await read_progression_source(
            db,
            novel_id=data.novel_id,
            scene_id=request.get("scene_id"),
            participants=participants,
            targets=targets,
            confirmed_context=confirmed,
        )
        if branch.basis_choice == "frozen":
            source = await scope_progression_source(
                db,
                dict(branch.source_snapshot_json or root.source_snapshot_json or {}),
                confirmed.compiled,
                expected_novel_id=data.novel_id,
                expected_scene_id=str(root.scene_id),
            )
        if (
            (
                branch.basis_choice == "current"
                and source["source_hash"] != pending["source_hash"]
            )
            or pending.get("parent_step_id") != str(branch.parent_step_id or "")
            or source["source_hash"] != pending["source_hash"]
        ):
            raise ConflictError("半步来源或父步骤已失效，请从历史明确选择新依据")
        _validate_confirmation_scope(
            dict(confirmed.compile_options or {}),
            SimpleNamespace(participants=participants),
            source["scene_id"],
        )
        root.current_task_id = branch.current_task_id = None
        meta = _task_meta(
            request={
                "novel_id": data.novel_id,
                "context_confirmation_id": data.context_confirmation_id,
            },
            root_id=root.id,
            branch_id=branch.id,
            execution_snapshot=root.llm_execution_snapshot_json,
            envelope=envelope,
            acknowledged_unknown=unknown if data.allow_possible_duplicate_charge else 0,
        )
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id),
            task_type=WORLD_PROGRESSION_TASK,
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta=meta,
        )
        if receipt.reused:
            raise ConflictError("并发恢复操作已登记，请刷新历史核对")
        root.current_task_id = branch.current_task_id = UUID(str(receipt.task_id))
        root.status = branch.status = "queued"
        branch.stop_reason = None
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=str(receipt.task_id),
            status="running",
        )
        await db.flush()
        return _response(receipt.task_id, receipt.status, root_id, branch_id)
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
            "include_deleted": "include_deleted",
        },
    },
)
async def api_progression_history(
    db: DbSession,
    *,
    novel_id: str = Query(...),
    scene_id: str | None = Query(default=None),
    root_id: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
):
    await require_active_project(db, novel_id)
    _enabled()
    try:
        return await read_progression_history(
            db,
            novel_id,
            scene_id=scene_id,
            root_id=root_id,
            include_deleted=include_deleted,
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/branches/{branch_id}/metadata",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only history label, star and note edits use branch version CAS; "
            "they are not available to assistant operations."
        )
    },
)
async def api_progression_metadata(
    branch_id: str, data: ProgressionMetadataRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    _enabled()
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
        "x-novelcraft-operation-exemption": (
            "Author-only confirmed soft deletion revokes matching standing consent; "
            "assistant operations cannot delete candidate history."
        )
    },
)
async def api_delete_progression_branch(
    branch_id: str, data: ProgressionDeleteRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    _enabled()
    if not data.confirm:
        raise HTTPException(status_code=400, detail="请确认将该分支移入 30 天恢复区")
    try:
        branch = await get_progression_branch(db, data.novel_id, branch_id)
        await db.scalar(
            select(StoryWorldProgressionAuthorization)
            .where(StoryWorldProgressionAuthorization.novel_id == UUID(data.novel_id))
            .with_for_update()
        )
        root = await get_progression_root(
            db, data.novel_id, str(branch.root_id), lock=True
        )
        branch = await get_progression_branch(db, data.novel_id, branch_id, lock=True)
        for task_id in {branch.current_task_id, root.current_task_id} - {None}:
            active = await db.get(AsyncTask, task_id)
            if active is not None and active.status in {"pending", "running"}:
                raise ConflictError("运行中的历史不能删除")
        return await delete_progression_branch(
            db, novel_id=data.novel_id, branch_id=branch_id
        )
    except Exception as error:
        raise _raise_http(error) from error


@router.post(
    "/branches/{branch_id}/restore",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only 30-day recovery of a soft-deleted branch; assistant "
            "operations cannot restore or rebind standing consent."
        )
    },
)
async def api_restore_progression_branch(
    branch_id: str, data: ProgressionDeleteRequest, db: DbSession
):
    await require_active_project(db, data.novel_id)
    _enabled()
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
    await require_active_project(db, data.novel_id)
    _enabled()
    try:
        novel_id = data.novel_id
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
    await require_active_project(db, novel_id)
    _enabled()
    try:
        root = await get_progression_root(db, novel_id, root_id)
        branch = await get_progression_branch(db, novel_id, branch_id)
        if str(branch.root_id) != str(root.id):
            raise ConflictError("分支不属于当前推进根")
        return await read_continuous_authorization(db, novel_id)
    except Exception as error:
        raise _raise_http(error) from error


@router.put(
    "/roots/{root_id}/branches/{branch_id}/continuous-authorization",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Author-only persistent spending consent with fresh Evidence confirmation, "
            "revision CAS and the original root budget; AI cannot grant itself consent."
        )
    },
)
async def api_set_continuous_authorization(
    root_id: str,
    branch_id: str,
    data: ProgressionContinuousAuthorizationRequest,
    db: DbSession,
):
    await require_active_project(db, data.novel_id)
    _enabled()
    try:
        await db.scalar(
            select(StoryWorldProgressionAuthorization)
            .where(StoryWorldProgressionAuthorization.novel_id == UUID(data.novel_id))
            .with_for_update()
        )
        root = await get_progression_root(db, data.novel_id, root_id, lock=True)
        branch = await get_progression_branch(db, data.novel_id, branch_id, lock=True)
        return await set_continuous_authorization(db, root=root, branch=branch, data=data)
    except Exception as error:
        raise _raise_http(error) from error


# Keep one router at the Story application boundary while the two modules stay
# independently testable.
router.include_router(_hook_router)
