"""Committed worker-loss state, stale recovery and late writers on real PostgreSQL."""

import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_expired_worker_recovery_fences_late_heartbeat_and_duplicate_finalization():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    lifecycle = TaskLifecycleService()
    novel_id, task_id = uuid.uuid4(), uuid.uuid4()
    task_type = "technical-recovery-probe"
    started = time.perf_counter()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Disposable recovery probe"))
            await db.flush()
            db.add(
                AsyncTask(
                    id=task_id,
                    novel_id=novel_id,
                    task_type=task_type,
                    meta={"novel_id": str(novel_id)},
                    status="pending",
                    recovery_policy="auto_requeue",
                    max_attempts=2,
                )
            )
        async with sessions() as db:
            claimed = await lifecycle.claim_exact(
                db, task_id=task_id, task_type=task_type
            )
            old_lease = claimed.lease_id
        # A dead worker cannot release its lease. Reproduce that durable state,
        # then run the real restart scanner in a different committed session.
        async with sessions.begin() as db:
            await db.execute(
                update(AsyncTask)
                .where(AsyncTask.id == task_id)
                .values(heartbeat_at=datetime.now(UTC) - timedelta(seconds=61))
            )
        async with sessions.begin() as db:
            counts = await lifecycle.recover_stale(db, max_heartbeat_gap=60)
            assert counts["auto_requeued"] >= 1
        async with sessions() as db:
            claimed = await lifecycle.claim_exact(
                db, task_id=task_id, task_type=task_type
            )
            new_lease = claimed.lease_id
            assert claimed.attempt == 2 and new_lease != old_lease
        async with sessions() as db:
            assert not await lifecycle.heartbeat(db, task_id=task_id, lease_id=old_lease)
            assert not await lifecycle.finalize(
                db,
                task_id=task_id,
                lease_id=old_lease,
                status="done",
                result_data={"writer": "stale"},
            )
            assert await lifecycle.finalize(
                db,
                task_id=task_id,
                lease_id=new_lease,
                status="done",
                result_data={"writer": "current"},
            )
            assert not await lifecycle.finalize(
                db,
                task_id=task_id,
                lease_id=new_lease,
                status="done",
                result_data={"writer": "duplicate"},
            )
        async with sessions() as db:
            stored = await db.get(AsyncTask, task_id)
            assert stored.status == "done" and stored.result == {"writer": "current"}
        output = Path(".test-artifacts/technical-recovery.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "injection": "committed expired heartbeat simulating lost worker",
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                    "stale_heartbeat_rejected": True,
                    "stale_finalize_rejected": True,
                    "duplicate_finalize_rejected": True,
                },
                indent=2,
            )
        )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
