"""
任务管理 API 路由

提供以下端点：
- POST /api/tasks — 提交新任务
- GET /api/tasks/{task_id} — 查询任务状态
- POST /api/tasks/{task_id}/cancel — 取消任务
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from core.api_params import NovelIdQuery
from core.container import get as get_container_service
from core.dependencies import DbSession
from infrastructure.tasks.contracts import TaskAction
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.lifecycle import TaskLifecycleService, lifecycle_contract
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from shared.constants import TASK_MAX_HEARTBEAT_GAP
from shared.enums import TaskStatus as TaskStatusEnum

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
_lifecycle = TaskLifecycleService()
_VALIDATION_ERROR_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def _public_task_result(value: Any) -> dict[str, Any]:
    """Project task results without private top-level worker checkpoints.

    Business handlers may persist resumable receipts under underscore-prefixed
    keys.  Those values remain available to the worker and lifecycle service,
    but are never part of the task status wire contract.
    """
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and not key.startswith("_")
    }


async def _require_active_project(db: DbSession, novel_id: str) -> None:
    guard = get_container_service("project.require_active")
    await guard(db, novel_id)


_MODULE_API_ONLY_TASK_TYPES = {
    "smart_dedup_scan",
    "interaction_story_generate",
    "interaction_summary_refresh",
    "deep_import",
    "deep_import_resume",
    "scene_auto_extraction",
    "world_object_auto_extraction",
    "plot_structure_auto_extraction",
    "world_alias_relation_extraction",
    "world_entity_fusion_suggestions",
    "world_bible_projection_refresh",
    "world_bible_synopsis_refresh",
    "plot_structure_generate",
    "chapter_card_extraction",
    "chapter_scene_generate",
    "outline_analyze",
    "outline_generate",
    "story_outline_generate",
    "writing_generate",
    "writing_conflict_ai_review",
    "publish_chapter",
    "rag_index_chapter",
    "rag_reindex_novel",
    "rag_retry_embeddings",
    "outline_structure_generation",
}


def _generic_submit_validation_errors(
    exc: PydanticValidationError,
    schema: type[BaseModel],
) -> list[dict[str, Any]]:
    """Return useful schema errors without echoing submitted metadata."""
    known_fields = set(schema.model_fields)
    details: list[dict[str, Any]] = []
    for error in exc.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        location: list[int | str] = []
        for index, part in enumerate(error.get("loc", [])):
            if isinstance(part, int):
                location.append(part)
            elif index == 0 and isinstance(part, str) and part in known_fields:
                location.append(part)
            else:
                location.append("[field]")
        raw_type = error.get("type")
        details.append(
            {
                "loc": location,
                "type": (
                    raw_type
                    if isinstance(raw_type, str)
                    and _VALIDATION_ERROR_TYPE_RE.fullmatch(raw_type)
                    else "validation_error"
                ),
            }
        )
    return details


# ============================================================
# Schema
# ============================================================


class TaskSubmitRequest(BaseModel):
    """提交任务请求"""

    task_type: str = Field(..., description="任务类型标识")
    meta: dict[str, Any] = Field(default_factory=dict, description="任务元数据（入参）")


class TaskSubmitResponse(BaseModel):
    """提交任务响应"""

    task_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态")


class TaskStatusResponse(BaseModel):
    """任务状态查询响应"""

    task_id: str
    task_type: str
    status: str
    progress: float | None
    meta: dict[str, Any]
    result: dict[str, Any]
    error_message: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    heartbeat_at: str | None = None
    attempt: int = 0
    max_attempts: int = 1
    stale: bool = False
    lifecycle: dict[str, Any] = Field(default_factory=dict)
    available_actions: list[TaskAction] = Field(default_factory=list)


class TaskCancelResponse(BaseModel):
    """取消任务响应"""

    task_id: str
    status: str
    cancelled: bool


class TaskRetryResponse(BaseModel):
    task_id: str
    status: str
    attempt: int
    max_attempts: int


# ============================================================
# API Endpoints
# ============================================================


@router.post("", response_model=TaskSubmitResponse, status_code=201)
async def submit_task(
    request: TaskSubmitRequest,
    db: DbSession,
) -> TaskSubmitResponse:
    """提交新任务到队列

    - 验证 task_type 是否有对应的注册处理器
    - 创建 async_tasks 记录
    - 返回 task_id
    """
    registry = TaskRegistry()
    if request.task_type in _MODULE_API_ONLY_TASK_TYPES:
        raise HTTPException(
            status_code=403,
            detail=f"Task type {request.task_type} must be submitted through module API",
        )
    if request.task_type not in registry:
        registered = registry.registered_types
        raise HTTPException(
            status_code=400,
            detail=f"Unknown task type: {request.task_type}. "
            f"Registered types: {registered}",
        )

    definition = registry.get_definition(request.task_type)
    submit_schema = definition.generic_submit_schema if definition else None
    if submit_schema is None:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Task type {request.task_type} must be submitted through module API"
            ),
        )
    try:
        validated_meta = submit_schema.model_validate(request.meta or {}).model_dump(
            mode="json",
            exclude_none=True,
        )
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=_generic_submit_validation_errors(exc, submit_schema),
        ) from exc
    if not isinstance(validated_meta, dict):
        raise HTTPException(
            status_code=422,
            detail="Generic task metadata schema must serialize to an object",
        )

    novel_id = validated_meta.get("novel_id")
    if definition.owner_scope == "project":
        if novel_id is None:
            raise HTTPException(status_code=422, detail="project task requires novel_id")
        await _require_active_project(db, str(novel_id))

    task_id = enqueue_task(
        db,
        request.task_type,
        meta=validated_meta,
        status=TaskStatusEnum.pending.value,
        progress=0.0,
        novel_id=str(novel_id) if novel_id is not None else None,
    )
    await db.flush()

    return TaskSubmitResponse(
        task_id=task_id,
        status=TaskStatusEnum.pending.value,
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: uuid.UUID,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> TaskStatusResponse:
    """查询任务状态

    （Bug L3: task_id 改为原生 UUID 类型，由 FastAPI 自动校验）
    """
    await _require_active_project(db, novel_id)
    stmt = select(AsyncTask).where(
        AsyncTask.id == task_id,
        AsyncTask.novel_id == uuid.UUID(str(novel_id)),
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    lifecycle = lifecycle_contract(
        task,
        max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
    )
    return TaskStatusResponse(
        task_id=str(task.id),
        task_type=task.task_type,
        status=task.status or "pending",
        progress=task.progress,
        meta=task.meta or {},
        result=_public_task_result(task.result),
        error_message=task.error_message,
        created_at=str(task.created_at) if task.created_at else None,
        started_at=str(task.started_at) if task.started_at else None,
        finished_at=str(task.finished_at) if task.finished_at else None,
        heartbeat_at=lifecycle.heartbeat_at,
        attempt=lifecycle.attempt,
        max_attempts=lifecycle.max_attempts,
        stale=lifecycle.stale,
        lifecycle={
            "reason": lifecycle.transition_reason,
            "recovery_policy": lifecycle.recovery_policy,
            "recovery_required": lifecycle.recovery_required,
            "stale_detected_at": lifecycle.stale_detected_at,
        },
        available_actions=lifecycle.available_actions,
    )


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
async def cancel_task(
    task_id: uuid.UUID,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> TaskCancelResponse:
    """取消一个 pending 或 running 的任务

    （Bug L3: task_id 改为原生 UUID 类型）
    """
    await _require_active_project(db, novel_id)
    stmt = select(AsyncTask).where(
        AsyncTask.id == task_id,
        AsyncTask.novel_id == uuid.UUID(str(novel_id)),
    ).with_for_update()
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be cancelled (status: {task.status})",
        )

    await _lifecycle.cancel(db, task=task)
    await db.flush()

    return TaskCancelResponse(
        task_id=str(task.id),
        status=str(task.status),
        cancelled=True,
    )


@router.post("/{task_id}/retry", response_model=TaskRetryResponse)
async def retry_task(
    task_id: uuid.UUID,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> TaskRetryResponse:
    await _require_active_project(db, novel_id)
    stmt = select(AsyncTask).where(
        AsyncTask.id == task_id,
        AsyncTask.novel_id == uuid.UUID(str(novel_id)),
    ).with_for_update()
    task = (await db.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    try:
        await _lifecycle.retry(db, task=task)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskRetryResponse(
        task_id=str(task.id),
        status=task.status,
        attempt=int(task.attempt or 0),
        max_attempts=int(task.max_attempts or 1),
    )
