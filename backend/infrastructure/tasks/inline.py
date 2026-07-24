"""Exact-task inline executor for isolated/manual harnesses."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import (
    managed_llm_provenance_scope,
    merge_managed_llm_provenance,
)
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from shared.constants import TASK_HEARTBEAT_INTERVAL

_MISSING_ATTRIBUTE = object()


async def run_task_inline(
    db: AsyncSession,
    *,
    task_id: str,
    expected_task_type: str,
) -> dict[str, Any]:
    """Run one pending task through infrastructure-owned lifecycle handling."""
    try:
        parsed_id = uuid.UUID(str(task_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("task_id must be a UUID") from exc
    handler = TaskRegistry().get_handler(expected_task_type)
    if handler is None:
        raise ValueError(f"no handler registered for task type: {expected_task_type}")
    task = await TaskLifecycleService().claim_exact(
        db,
        task_id=parsed_id,
        task_type=expected_task_type,
    )
    if task is None:
        current = (
            await db.execute(
                select(AsyncTask).where(
                    AsyncTask.id == parsed_id,
                    AsyncTask.task_type == expected_task_type,
                )
            )
        ).scalar_one_or_none()
        if current is None:
            raise ValueError("task not found or task type mismatch")
        if current.status == "pending":
            raise ValueError("task is waiting for its active coalesced owner")
        raise ValueError("only a pending task can run inline")
    claimed_task_id = task.id
    lease_id = str(task.lease_id or "")
    heartbeat_task = asyncio.create_task(_heartbeat_loop(claimed_task_id, lease_id))
    previous_inline_marker = getattr(db, "task_inline_execution_enabled", None)
    db.task_inline_execution_enabled = True
    restore_commit = _install_commit_fence(db, task=task, lease_id=lease_id)
    with managed_llm_provenance_scope() as managed_steps:
        try:
            result = await handler(db=db, task=task)
            restore_commit()
            result_data = result if isinstance(result, dict) else {"result": result}
            if managed_steps:
                result_data = merge_managed_llm_provenance(
                    result_data,
                    managed_steps,
                )
            accepted = await TaskLifecycleService().finalize(
                db,
                task_id=claimed_task_id,
                lease_id=lease_id,
                status="done",
                result_data=result_data,
            )
            if not accepted:
                raise asyncio.CancelledError
            return result_data
        except asyncio.CancelledError:
            restore_commit()
            await db.rollback()
            await TaskLifecycleService().finalize(
                db,
                task_id=claimed_task_id,
                lease_id=lease_id,
                status="cancelled",
            )
            raise
        except Exception as exc:
            restore_commit()
            await db.rollback()
            await TaskLifecycleService().finalize(
                db,
                task_id=claimed_task_id,
                lease_id=lease_id,
                status="failed",
                error_message=redact_diagnostic(
                    f"{type(exc).__name__}: {exc}", limit=1000
                ),
            )
            raise
        finally:
            restore_commit()
            if previous_inline_marker is None:
                delattr(db, "task_inline_execution_enabled")
            else:
                db.task_inline_execution_enabled = previous_inline_marker
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


def _install_commit_fence(
    db: AsyncSession,
    *,
    task: AsyncTask,
    lease_id: str,
) -> Callable[[], None]:
    """Apply the worker's running-lease checkpoint to inline handler commits."""
    previous_instance_commit = getattr(db, "__dict__", {}).get(
        "commit",
        _MISSING_ATTRIBUTE,
    )
    original_commit = db.commit
    restored = False

    async def fenced_commit() -> None:
        accepted = await TaskLifecycleService().checkpoint_running_attempt(
            db,
            task=task,
            lease_id=lease_id,
        )
        if not accepted:
            await db.rollback()
            raise asyncio.CancelledError
        await original_commit()

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        restored = True
        if previous_instance_commit is _MISSING_ATTRIBUTE:
            delattr(db, "commit")
        else:
            setattr(db, "commit", previous_instance_commit)

    setattr(db, "commit", fenced_commit)
    return restore


async def _heartbeat_loop(task_id: Any, lease_id: str) -> None:
    from core.database import get_manager

    lifecycle = TaskLifecycleService()
    while True:
        await asyncio.sleep(TASK_HEARTBEAT_INTERVAL)
        try:
            async with get_manager().session_factory() as session:
                accepted = await lifecycle.heartbeat(
                    session,
                    task_id=task_id,
                    lease_id=lease_id,
                )
                if not accepted:
                    return
        except Exception:
            return
