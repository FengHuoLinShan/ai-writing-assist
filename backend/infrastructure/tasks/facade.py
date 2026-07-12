"""Stable read-only task lifecycle projections for other modules."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.contracts import TaskLifecycleContract
from infrastructure.tasks.lifecycle import TaskLifecycleService


async def list_task_lifecycle_contracts(
    db: AsyncSession,
    *,
    task_ids: list[str],
    novel_id: str,
    max_heartbeat_gap: float,
) -> dict[str, TaskLifecycleContract]:
    return await TaskLifecycleService().list_contracts(
        db,
        task_ids=task_ids,
        novel_id=novel_id,
        max_heartbeat_gap=max_heartbeat_gap,
    )
