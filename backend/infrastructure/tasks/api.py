"""
任务管理 API 路由

提供以下端点：
- POST /api/tasks — 提交新任务
- GET /api/tasks/{task_id} — 查询任务状态
- POST /api/tasks/{task_id}/cancel — 取消任务
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from shared.enums import TaskStatus as TaskStatusEnum

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_MODULE_API_ONLY_TASK_TYPES = {
    "deep_import",
    "deep_import_resume",
    "scene_auto_extraction",
    "world_object_auto_extraction",
    "plot_structure_auto_extraction",
    "world_entity_extraction",
    "world_alias_relation_extraction",
    "world_bible_projection_refresh",
    "writing_generate",
    "outline_structure_generation",
    "outline_chapter_scenes_extract",
}


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


class TaskCancelResponse(BaseModel):
    """取消任务响应"""

    task_id: str
    status: str
    cancelled: bool


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

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type=request.task_type,
        status=TaskStatusEnum.pending.value,
        meta=request.meta or {},
        progress=0.0,
    )
    db.add(task)
    await db.flush()

    return TaskSubmitResponse(
        task_id=str(task.id),
        status=str(task.status),
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
    stmt = select(AsyncTask).where(
        AsyncTask.id == task_id,
        AsyncTask.meta["novel_id"].as_string() == str(novel_id),
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    return TaskStatusResponse(
        task_id=str(task.id),
        task_type=task.task_type,
        status=task.status or "pending",
        progress=task.progress,
        meta=task.meta or {},
        result=task.result or {},
        error_message=task.error_message,
        created_at=str(task.created_at) if task.created_at else None,
        started_at=str(task.started_at) if task.started_at else None,
        finished_at=str(task.finished_at) if task.finished_at else None,
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
    stmt = select(AsyncTask).where(
        AsyncTask.id == task_id,
        AsyncTask.meta["novel_id"].as_string() == str(novel_id),
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    if task.status not in ("pending", "running"):
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be cancelled (status: {task.status})",
        )

    task.mark_cancelled()
    await db.flush()

    return TaskCancelResponse(
        task_id=str(task.id),
        status=str(task.status),
        cancelled=True,
    )
