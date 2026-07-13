"""Atomic task lifecycle transitions and public lifecycle projection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.contracts import TaskAction, TaskLifecycleContract
from infrastructure.tasks.models import AsyncTask


class TaskLifecycleService:
    async def cancel_unfinished_for_novel(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        transition_reason: str,
    ) -> int:
        """Cancel pending/running tasks owned by one novel without committing."""
        result = await db.execute(
            update(AsyncTask)
            .where(
                AsyncTask.meta["novel_id"].as_string() == str(novel_id),
                AsyncTask.status.in_(("pending", "running")),
            )
            .values(
                status="cancelled",
                finished_at=datetime.now(UTC),
                lease_id=None,
                transition_reason=transition_reason,
            )
            .execution_options(synchronize_session=False)
        )
        await db.flush()
        return result.rowcount or 0

    async def delete_for_novels(
        self,
        db: AsyncSession,
        *,
        novel_ids: list[str],
    ) -> int:
        """Delete task history for permanently deleted projects."""
        normalized_ids = list(dict.fromkeys(str(novel_id) for novel_id in novel_ids))
        if not normalized_ids:
            return 0
        result = await db.execute(
            delete(AsyncTask).where(
                AsyncTask.meta["novel_id"].as_string().in_(normalized_ids),
            )
        )
        await db.flush()
        return result.rowcount or 0

    async def list_contracts(
        self,
        db: AsyncSession,
        *,
        task_ids: list[str],
        max_heartbeat_gap: float,
        novel_id: str | None = None,
    ) -> dict[str, TaskLifecycleContract]:
        parsed = []
        for task_id in dict.fromkeys(task_ids):
            try:
                parsed.append(uuid.UUID(str(task_id)))
            except (TypeError, ValueError):
                continue
        if not parsed:
            return {}
        tasks = list(
            (
                await db.execute(select(AsyncTask).where(AsyncTask.id.in_(parsed)))
            ).scalars()
        )
        if novel_id is not None:
            tasks = [
                task
                for task in tasks
                if str((task.meta or {}).get("novel_id") or "") == str(novel_id)
            ]
        return {
            str(task.id): lifecycle_contract(
                task,
                max_heartbeat_gap=max_heartbeat_gap,
            )
            for task in tasks
        }

    async def claim_next(self, db: AsyncSession) -> AsyncTask | None:
        stmt = (
            select(AsyncTask)
            .where(AsyncTask.status == "pending")
            .order_by(AsyncTask.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        task = result.scalar_one_or_none()
        if task is None:
            return None
        task.mark_running(lease_id=str(uuid.uuid4()))
        await db.commit()
        return task

    async def heartbeat(
        self,
        db: AsyncSession,
        *,
        task_id: Any,
        lease_id: str,
    ) -> bool:
        result = await db.execute(
            update(AsyncTask)
            .where(
                AsyncTask.id == task_id,
                AsyncTask.status == "running",
                AsyncTask.lease_id == lease_id,
            )
            .values(heartbeat_at=datetime.now(UTC))
        )
        await db.commit()
        return bool(result.rowcount)

    async def finalize(
        self,
        db: AsyncSession,
        *,
        task_id: Any,
        lease_id: str,
        status: str,
        result_data: dict | None = None,
        error_message: str | None = None,
        recovery_policy: str | None = None,
    ) -> bool:
        values: dict[str, Any] = {
            "status": status,
            "finished_at": datetime.now(UTC),
            "lease_id": None,
        }
        if status == "done":
            values["progress"] = 1.0
            values["error_message"] = None
        elif error_message is not None:
            values["error_message"] = error_message
        if result_data is not None:
            values["result"] = result_data
        if recovery_policy is not None:
            values["recovery_policy"] = recovery_policy
        result = await db.execute(
            update(AsyncTask)
            .where(
                AsyncTask.id == task_id,
                AsyncTask.status == "running",
                AsyncTask.lease_id == lease_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        accepted = bool(result.rowcount)
        if accepted:
            await db.commit()
        else:
            # A cleared/replaced lease means the handler no longer owns this
            # attempt. Roll back its business writes together with the rejected
            # terminal transition instead of committing stale work.
            await db.rollback()
        return accepted

    async def cancel(
        self,
        db: AsyncSession,
        *,
        task: AsyncTask,
    ) -> None:
        task.mark_cancelled()
        task.transition_reason = "user_cancelled"
        await db.flush()

    async def retry(self, db: AsyncSession, *, task: AsyncTask) -> None:
        if task.status != "failed":
            raise ValueError("task is not failed")
        if task.recovery_policy != "auto_requeue":
            raise ValueError("task recovery policy does not allow retry")
        if int(task.attempt or 0) >= int(task.max_attempts or 1):
            raise ValueError("task retry attempts exhausted")
        task.status = "pending"
        task.finished_at = None
        task.heartbeat_at = None
        task.lease_id = None
        task.error_message = None
        task.transition_reason = "manual_retry"
        result_data = dict(task.result or {})
        lifecycle = dict(result_data.get("lifecycle") or {})
        lifecycle["reason"] = "manual_retry"
        lifecycle["recovery_required"] = False
        result_data["lifecycle"] = lifecycle
        task.result = result_data
        await db.flush()

    async def recover_stale(
        self,
        db: AsyncSession,
        *,
        max_heartbeat_gap: float,
    ) -> dict[str, int]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=max_heartbeat_gap)
        stmt = (
            select(AsyncTask)
            .where(
                AsyncTask.status == "running",
                or_(
                    AsyncTask.heartbeat_at < cutoff,
                    (AsyncTask.heartbeat_at.is_(None) & (AsyncTask.started_at < cutoff)),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        tasks = list((await db.execute(stmt)).scalars().all())
        counts = {"auto_requeued": 0, "failed": 0, "manual_resume": 0}
        for task in tasks:
            self._transition_stale(task, now=now)
            if task.status == "pending":
                counts["auto_requeued"] += 1
            else:
                counts["failed"] += 1
                if task.recovery_policy == "manual_resume":
                    counts["manual_resume"] += 1
        if tasks:
            await db.commit()
        return counts

    @staticmethod
    def _transition_stale(task: AsyncTask, *, now: datetime) -> None:
        result_data = dict(task.result or {})
        meta_data = dict(task.meta or {})
        lifecycle = dict(result_data.get("lifecycle") or {})
        history = list(lifecycle.get("transitions") or [])
        transition = {
            "at": now.isoformat(),
            "from": "running",
            "reason": "heartbeat_timeout",
            "attempt": int(task.attempt or 0),
            "lease_id": task.lease_id,
        }
        history.append(transition)
        lifecycle.update(
            {
                "reason": "heartbeat_timeout",
                "recovery_policy": task.recovery_policy,
                "recovery_required": task.recovery_policy == "manual_resume",
                "transitions": history[-50:],
            }
        )
        result_data["lifecycle"] = lifecycle
        task.stale_detected_at = now
        task.transition_reason = "heartbeat_timeout"
        task.lease_id = None

        if task.recovery_policy == "auto_requeue" and int(task.attempt or 0) < int(
            task.max_attempts or 1
        ):
            task.status = "pending"
            task.finished_at = None
            task.error_message = "Task recovered: heartbeat timeout"
            transition["to"] = "pending"
        else:
            task.status = "failed"
            task.finished_at = now
            task.error_message = "Task interrupted: heartbeat timeout"
            transition["to"] = "failed"

        if task.recovery_policy == "manual_resume":
            flags = {
                "interrupted": True,
                "recoverable": True,
                "recovery_required": True,
                "interrupted_at": now.isoformat(),
                "last_heartbeat_at": (
                    task.heartbeat_at.isoformat() if task.heartbeat_at else None
                ),
            }
            result_data.update(flags)
            meta_data.update(flags)
            recovery_summary = dict(result_data.get("recovery_summary") or {})
            recovery_summary.update(
                {
                    "reason": "heartbeat_timeout",
                    "current_phase": result_data.get("current_phase"),
                    "current_chapter": result_data.get("current_chapter"),
                    "current_chapter_range": result_data.get("current_chapter_range"),
                    "last_heartbeat_at": flags["last_heartbeat_at"],
                }
            )
            result_data["recovery_summary"] = {
                key: value for key, value in recovery_summary.items() if value is not None
            }
        task.result = result_data
        task.meta = meta_data


def lifecycle_contract(
    task: AsyncTask,
    *,
    max_heartbeat_gap: float,
    now: datetime | None = None,
) -> TaskLifecycleContract:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=max_heartbeat_gap)
    heartbeat_at = _datetime_attr(task, "heartbeat_at")
    started_at = _datetime_attr(task, "started_at")
    heartbeat = heartbeat_at or started_at
    if heartbeat is not None and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    stale = task.status == "running" and (heartbeat is None or heartbeat < cutoff)
    result_data = task.result or {}
    meta_data = task.meta or {}
    recovery_policy = _string_attr(task, "recovery_policy") or "restart_origin"
    attempt = _int_attr(task, "attempt", 0)
    max_attempts = _int_attr(task, "max_attempts", 1)
    recovery_required = bool(
        result_data.get("recovery_required") or meta_data.get("recovery_required")
    )
    actions: list[TaskAction] = []
    if task.status in {"pending", "running"}:
        actions.append("cancel")
    elif task.status == "failed":
        if recovery_policy == "manual_resume" and recovery_required:
            actions.extend(["resume", "abandon"])
        elif recovery_policy == "auto_requeue" and attempt < max_attempts:
            actions.append("retry")
        elif recovery_policy == "auto_requeue":
            actions.append("restart_origin")
        elif recovery_policy == "restart_origin":
            actions.append("restart_origin")
        else:
            actions.append("dismiss")
    elif task.status in {"done", "cancelled"}:
        actions.append("dismiss")
    return TaskLifecycleContract(
        task_id=str(task.id),
        task_type=task.task_type,
        status=task.status,
        attempt=attempt,
        max_attempts=max_attempts,
        recovery_policy=recovery_policy,
        lease_id=_string_attr(task, "lease_id"),
        heartbeat_at=heartbeat_at.isoformat() if heartbeat_at else None,
        stale_detected_at=(
            _datetime_attr(task, "stale_detected_at").isoformat()
            if _datetime_attr(task, "stale_detected_at")
            else None
        ),
        transition_reason=_string_attr(task, "transition_reason"),
        stale=stale,
        recovery_required=recovery_required,
        available_actions=actions,
    )


def _datetime_attr(task: Any, name: str) -> datetime | None:
    value = getattr(task, name, None)
    return value if isinstance(value, datetime) else None


def _string_attr(task: Any, name: str) -> str | None:
    value = getattr(task, name, None)
    return value if isinstance(value, str) and value else None


def _int_attr(task: Any, name: str, default: int) -> int:
    value = getattr(task, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) else default
