"""Stable task lifecycle seams for other modules."""

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


async def cancel_unfinished_tasks_for_novel(
    db: AsyncSession,
    *,
    novel_id: str,
    transition_reason: str,
) -> int:
    """Cancel only pending/running tasks belonging to one novel."""
    return await TaskLifecycleService().cancel_unfinished_for_novel(
        db,
        novel_id=novel_id,
        transition_reason=transition_reason,
    )


async def delete_tasks_for_novel(
    db: AsyncSession,
    *,
    novel_id: str,
) -> int:
    """Delete task history after one project is permanently deleted."""
    return await delete_tasks_for_novels(db, novel_ids=[novel_id])


async def delete_tasks_for_novels(
    db: AsyncSession,
    *,
    novel_ids: list[str],
) -> int:
    """Delete task history after projects are permanently deleted."""
    return await TaskLifecycleService().delete_for_novels(
        db,
        novel_ids=novel_ids,
    )
