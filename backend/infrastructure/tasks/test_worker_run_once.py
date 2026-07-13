from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_fails", "expected_status"),
    [(False, "done"), (True, "failed")],
    ids=["success", "failure"],
)
async def test_run_once_returns_reloaded_terminal_task(
    test_engine,
    handler_fails: bool,
    expected_status: str,
) -> None:
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    task_type = f"run-once-reload-{uuid.uuid4()}"
    registry = TaskRegistry()

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def handler(*, db, task):
        if handler_fails:
            raise RuntimeError("expected handler failure")
        return {"task_id": str(task.id), "ok": True}

    registry.register(task_type, handler)
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type=task_type,
                    status="pending",
                    meta={},
                )
            )

        worker = TaskWorker(
            db_manager=TestManager(),
            heartbeat_interval=60.0,
        )
        returned = await worker.run_once()

        assert returned is not None
        assert returned.id == task_id
        assert returned.status == expected_status
        assert returned.finished_at is not None
        assert returned.lease_id is None
        if handler_fails:
            assert "expected handler failure" in str(returned.error_message)
        else:
            assert returned.progress == 1.0
            assert returned.result == {"task_id": str(task_id), "ok": True}
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
