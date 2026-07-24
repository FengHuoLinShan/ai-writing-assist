"""
任务入队工具 — 封装 AsyncTask 创建

facade 和 service 层通过此函数入队任务，不直接实例化 AsyncTask。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.contracts import (
    CoalescedTaskContract,
    TaskCoalescingMode,
)
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry


def build_task_coalescing_key(
    *,
    task_type: str,
    novel_id: str,
    scope: Sequence[str],
) -> str:
    """Build the internal digest used for database-level task coalescing."""
    normalized_novel_id = str(uuid.UUID(str(novel_id)))
    normalized_scope = tuple(str(value).strip() for value in scope)
    if not normalized_scope or any(not value for value in normalized_scope):
        raise ValueError("coalescing scope must contain non-empty values")
    payload = json.dumps(
        {
            "novel_id": normalized_novel_id,
            "scope": normalized_scope,
            "task_type": str(task_type),
            "version": 1,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _new_task(
    *,
    task_type: str,
    meta: dict[str, Any] | None,
    status: str,
    progress: float,
    coalescing_key: str | None,
) -> AsyncTask:
    definition = TaskRegistry().get_definition(task_type)
    return AsyncTask(
        id=uuid.uuid4(),
        task_type=task_type,
        status=status,
        meta=meta or {},
        progress=progress,
        recovery_policy=(definition.recovery_policy if definition else "restart_origin"),
        max_attempts=definition.max_attempts if definition else 1,
        attempt=0,
        coalescing_key=coalescing_key,
    )


def enqueue_task(
    db: AsyncSession,
    task_type: str,
    meta: dict[str, Any] | None = None,
    status: str = "pending",
    progress: float = 0.0,
) -> str:
    """创建并添加一个异步任务到 session，返回 task_id"""
    task = _new_task(
        task_type=task_type,
        status=status,
        meta=meta or {},
        progress=progress,
        coalescing_key=None,
    )
    db.add(task)
    return str(task.id)


async def _get_active_coalesced_task(
    db: AsyncSession,
    *,
    coalescing_key: str,
    pending_only: bool = False,
) -> AsyncTask | None:
    statuses = ("pending",) if pending_only else ("pending", "running")
    stmt = (
        select(AsyncTask)
        .where(
            AsyncTask.coalescing_key == coalescing_key,
            AsyncTask.status.in_(statuses),
        )
        .order_by(
            case((AsyncTask.status == "pending", 0), else_=1),
            AsyncTask.created_at.desc(),
            AsyncTask.id.desc(),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def lock_task_coalescing_key(
    db: AsyncSession,
    *,
    coalescing_key: str | None,
) -> None:
    """Serialize enqueue/claim transitions for one key on PostgreSQL."""
    if not isinstance(coalescing_key, str) or not coalescing_key:
        return
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"task_coalescing:{coalescing_key}"},
    )


async def enqueue_coalesced_task(
    db: AsyncSession,
    *,
    task_type: str,
    novel_id: str,
    scope: Sequence[str],
    meta: dict[str, Any] | None = None,
    mode: TaskCoalescingMode = "reuse_active",
) -> CoalescedTaskContract:
    """Atomically create or reuse one task in a secret-free coalescing scope."""
    if mode not in {"reuse_active", "one_pending_follower"}:
        raise ValueError(f"unsupported task coalescing mode: {mode}")
    key = build_task_coalescing_key(
        task_type=task_type,
        novel_id=novel_id,
        scope=scope,
    )
    await lock_task_coalescing_key(db, coalescing_key=key)
    existing = await _get_active_coalesced_task(
        db,
        coalescing_key=key,
        pending_only=mode == "one_pending_follower",
    )
    if existing is not None:
        return CoalescedTaskContract(
            task_id=str(existing.id),
            status=str(existing.status),
            reused=True,
        )
    if mode == "reuse_active":
        existing = await _get_active_coalesced_task(
            db,
            coalescing_key=key,
        )
        if existing is not None:
            return CoalescedTaskContract(
                task_id=str(existing.id),
                status=str(existing.status),
                reused=True,
            )

    task = _new_task(
        task_type=task_type,
        meta=meta,
        status="pending",
        progress=0.0,
        coalescing_key=key,
    )
    try:
        async with db.begin_nested():
            db.add(task)
            await db.flush()
    except IntegrityError:
        existing = await _get_active_coalesced_task(
            db,
            coalescing_key=key,
            pending_only=mode == "one_pending_follower",
        )
        if existing is None:
            existing = await _get_active_coalesced_task(
                db,
                coalescing_key=key,
            )
        if existing is None:
            raise
        return CoalescedTaskContract(
            task_id=str(existing.id),
            status=str(existing.status),
            reused=True,
        )
    return CoalescedTaskContract(
        task_id=str(task.id),
        status="pending",
        reused=False,
    )


async def get_latest_coalesced_task(
    db: AsyncSession,
    *,
    task_type: str,
    novel_id: str,
    scope: Sequence[str],
) -> CoalescedTaskContract | None:
    """Return the newest task for a keyed scope without exposing its key."""
    key = build_task_coalescing_key(
        task_type=task_type,
        novel_id=novel_id,
        scope=scope,
    )
    task = (
        await db.execute(
            select(AsyncTask)
            .where(AsyncTask.coalescing_key == key)
            .order_by(AsyncTask.created_at.desc(), AsyncTask.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if task is None:
        return None
    return CoalescedTaskContract(
        task_id=str(task.id),
        status=str(task.status),
        reused=True,
    )
