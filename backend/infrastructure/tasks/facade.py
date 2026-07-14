"""Stable task lifecycle seams for other modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.contracts import (
    CompletedTaskPayloadContract,
    TaskLifecycleContract,
    TaskOwnerContract,
)
from infrastructure.tasks.lifecycle import TaskLifecycleService


def require_task_checkpoint_session(db: AsyncSession) -> None:
    """Reject commit-owning task seams outside a fenced handler session."""
    if getattr(db, "task_checkpoint_enabled", False) is not True:
        raise RuntimeError(
            "task checkpoint operation requires a fenced TaskWorker handler session"
        )


async def list_running_task_types_for_novel(
    db: AsyncSession,
    *,
    novel_id: str,
    task_types: set[str],
    exclude_task_id: str,
) -> list[str]:
    """Minimal novel-scoped projection used by short source finalizers."""
    return await TaskLifecycleService().list_running_types_for_novel(
        db,
        novel_id=novel_id,
        task_types=task_types,
        exclude_task_id=exclude_task_id,
    )


async def require_running_task_attempt(
    db: AsyncSession,
    *,
    task_id: str,
    task_type: str,
    novel_id: str,
    lease_id: str,
    attempt: int,
) -> None:
    """Lock/fence one exact attempt without exposing task ORM payloads."""
    await TaskLifecycleService().require_running_attempt(
        db,
        task_id=task_id,
        task_type=task_type,
        novel_id=novel_id,
        lease_id=lease_id,
        attempt=attempt,
    )


async def get_completed_task_payload(
    db: AsyncSession,
    *,
    task_id: str,
    task_type: str,
    novel_id: str,
    for_update: bool = False,
) -> CompletedTaskPayloadContract | None:
    """Return a strictly scoped completed task source for an apply workflow."""
    return await TaskLifecycleService().get_completed_payload(
        db,
        task_id=task_id,
        task_type=task_type,
        novel_id=novel_id,
        for_update=for_update,
    )


async def replace_completed_task_result(
    db: AsyncSession,
    *,
    task_id: str,
    task_type: str,
    novel_id: str,
    expected_revision_token: datetime | None,
    result: dict[str, Any],
) -> bool:
    """CAS one exactly scoped completed task result in the caller transaction."""
    return await TaskLifecycleService().replace_completed_result(
        db,
        task_id=task_id,
        task_type=task_type,
        novel_id=novel_id,
        expected_revision_token=expected_revision_token,
        result=result,
    )


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


async def get_task_owner(
    db: AsyncSession,
    *,
    task_id: str,
) -> TaskOwnerContract | None:
    """Return only the novel owner needed by an external authorization guard."""
    return await TaskLifecycleService().get_owner(db, task_id=task_id)


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
