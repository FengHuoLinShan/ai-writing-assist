"""
任务入队工具 — 封装 AsyncTask 创建

facade 和 service 层通过此函数入队任务，不直接实例化 AsyncTask。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask


def enqueue_task(
    db: AsyncSession,
    task_type: str,
    meta: dict[str, Any] | None = None,
    status: str = "pending",
    progress: float = 0.0,
) -> str:
    """创建并添加一个异步任务到 session，返回 task_id"""
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type=task_type,
        status=status,
        meta=meta or {},
        progress=progress,
    )
    db.add(task)
    return str(task.id)
