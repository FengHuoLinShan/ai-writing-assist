from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.logging_context import (
    bind_validated_novel_id,
    current_novel_id_for_log,
)
from infrastructure.llm.errors import LLMAuthError, LLMTimeoutError
from infrastructure.llm.retry import transport_retries_enabled
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

    registry.register(task_type, handler, owner_scope="global")
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


@pytest.mark.asyncio
async def test_transient_llm_failure_requeues_once_without_transport_retry(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_id = uuid.uuid4()
    task_type = f"transient-retry-{uuid.uuid4()}"
    registry = TaskRegistry()
    calls = 0

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def handler(*, db, task):
        nonlocal calls
        calls += 1
        assert transport_retries_enabled() is False
        if calls == 1:
            raise LLMTimeoutError("temporary")
        return {"ok": True}

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=2,
        retry_transient_llm_errors=True,
    )
    try:
        async with sessions.begin() as db:
            task = AsyncTask(id=task_id, task_type=task_type, status="pending", meta={})
            task.recovery_policy = "auto_requeue"
            task.max_attempts = 2
            db.add(task)
        worker = TaskWorker(db_manager=TestManager(), heartbeat_interval=60.0)

        first = await worker.run_once()
        second = await worker.run_once()

        assert first is not None and first.status == "pending"
        assert first.attempt == 1
        assert first.transition_reason == "transient_retry"
        assert second is not None and second.status == "done"
        assert second.attempt == 2
        assert calls == 2
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))


@pytest.mark.asyncio
async def test_non_retryable_llm_failure_finishes_immediately(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    task_id = uuid.uuid4()
    task_type = f"terminal-retry-{uuid.uuid4()}"
    registry = TaskRegistry()
    calls = 0

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def handler(*, db, task):
        nonlocal calls
        calls += 1
        raise LLMAuthError("bad credentials")

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=2,
        retry_transient_llm_errors=True,
    )
    try:
        async with sessions.begin() as db:
            db.add(AsyncTask(id=task_id, task_type=task_type, status="pending", meta={}))
        result = await TaskWorker(
            db_manager=TestManager(), heartbeat_interval=60.0
        ).run_once()
        assert result is not None and result.status == "failed"
        assert result.attempt == 1
        assert calls == 1
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))


@pytest.mark.asyncio
async def test_handler_failure_auto_requeues_only_until_frozen_attempt_limit(
    test_engine,
) -> None:
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    task_type = f"run-once-auto-requeue-{uuid.uuid4()}"
    registry = TaskRegistry()

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def handler(*, db, task):
        del db, task
        raise RuntimeError("transient cleanup failure")

    registry.register(
        task_type,
        handler,
        owner_scope="global",
        recovery_policy="auto_requeue",
        max_attempts=2,
    )
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type=task_type,
                    status="pending",
                    recovery_policy="auto_requeue",
                    max_attempts=2,
                    meta={},
                )
            )

        worker = TaskWorker(db_manager=TestManager(), heartbeat_interval=60.0)
        worker._heartbeat_loop = AsyncMock(return_value=None)
        first = await worker.run_once()
        assert first is not None
        assert first.status == "pending"
        assert first.attempt == 1
        assert first.finished_at is None
        assert first.lease_id is None
        assert first.result["lifecycle"]["reason"] == "handler_error"

        assert await worker.run_once() is None
        async with sessions.begin() as retry_db:
            persisted = await retry_db.get(AsyncTask, task_id)
            assert persisted is not None
            persisted.updated_at = datetime.now(UTC) - timedelta(seconds=2)

        second = await worker.run_once()
        assert second is not None
        assert second.status == "failed"
        assert second.attempt == 2
        assert second.finished_at is not None
        assert "transient cleanup failure" in str(second.error_message)
        assert worker.stats["failed"] == 1
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))


@pytest.mark.asyncio
async def test_handler_can_checkpoint_progress_without_domain_commit(test_engine) -> None:
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    task_type = f"run-once-progress-checkpoint-{uuid.uuid4()}"
    registry = TaskRegistry()
    observed: dict[str, object] = {}

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def handler(*, db, task):
        assert db.in_transaction() is False
        task.result = {"phase": "provider", "message": "正在分析正文"}
        task.update_progress(0.42)
        observed["accepted"] = await db.checkpoint_task_progress()
        assert db.in_transaction() is False
        async with sessions() as inspection_db:
            persisted = await inspection_db.get(AsyncTask, task.id)
            assert persisted is not None
            observed["progress"] = persisted.progress
            observed["result"] = dict(persisted.result or {})
        return {"ok": True}

    registry.register(task_type, handler, owner_scope="global")
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

        returned = await TaskWorker(
            db_manager=TestManager(),
            heartbeat_interval=60.0,
        ).run_once()

        assert returned is not None
        assert returned.status == "done"
        assert observed == {
            "accepted": True,
            "progress": 0.42,
            "result": {"phase": "provider", "message": "正在分析正文"},
        }
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "opens_transaction",
    [False, True],
    ids=["no-transaction", "read-transaction"],
)
async def test_successful_preflight_leaves_handler_without_transaction(
    test_engine,
    caplog,
    opens_transaction: bool,
) -> None:
    """A real handler session starts outside the preflight read transaction."""
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    task_type = f"run-once-preflight-read-{uuid.uuid4()}"
    novel_id = str(uuid.uuid4())
    expected_meta = {"novel_id": novel_id, "payload": "preserved"}
    registry = TaskRegistry()
    observed: dict[str, object] = {}

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def preflight(db, task):
        if opens_transaction:
            await db.execute(select(1))
        assert db.in_transaction() is opens_transaction
        assert bind_validated_novel_id(novel_id) is True

    async def handler(*, db, task):
        observed["in_transaction"] = db.in_transaction()
        observed["meta"] = dict(task.meta or {})
        observed["progress"] = task.progress
        observed["log_novel_id"] = current_novel_id_for_log()
        return {"ok": True}

    registry.register(task_type, handler)
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type=task_type,
                    status="pending",
                    progress=0.25,
                    meta=expected_meta,
                )
            )

        worker = TaskWorker(
            db_manager=TestManager(),
            heartbeat_interval=60.0,
            task_preflight=preflight,
        )
        with caplog.at_level("INFO", logger="infrastructure.tasks.worker"):
            returned = await worker.run_once()

        assert returned is not None
        assert returned.status == "done"
        assert observed == {
            "in_transaction": False,
            "meta": expected_meta,
            "progress": 0.25,
            "log_novel_id": novel_id,
        }
        assert f"novel_id={novel_id}" in "\n".join(caplog.messages)
        assert current_novel_id_for_log() == "<none>"
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))


@pytest.mark.asyncio
async def test_preflight_exception_rolls_back_and_skips_handler(test_engine) -> None:
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    task_type = f"run-once-preflight-error-{uuid.uuid4()}"
    novel_id = str(uuid.uuid4())
    registry = TaskRegistry()
    handler_called = False

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def preflight(db, _task):
        await db.execute(select(1))
        bind_validated_novel_id(novel_id)
        raise RuntimeError("expected preflight rejection")

    async def handler(*, db, task):
        nonlocal handler_called
        handler_called = True
        return {"unexpected": True}

    registry.register(task_type, handler)
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type=task_type,
                    status="pending",
                    meta={"novel_id": novel_id},
                )
            )

        returned = await TaskWorker(
            db_manager=TestManager(),
            heartbeat_interval=60.0,
            task_preflight=preflight,
        ).run_once()

        assert returned is not None
        assert returned.status == "failed"
        assert returned.error_message == "RuntimeError: expected preflight rejection"
        assert handler_called is False
        assert current_novel_id_for_log() == "<none>"
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "write_mode",
    ["new", "dirty", "deleted", "flush", "commit"],
)
async def test_preflight_orm_write_fails_task_and_is_rolled_back(
    test_engine,
    write_mode: str,
) -> None:
    """A real preflight cannot smuggle an ORM write into the handler attempt."""
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    staged_task_id = uuid.uuid4()
    task_type = f"run-once-preflight-write-{uuid.uuid4()}"
    registry = TaskRegistry()
    handler_called = False

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def preflight(db, _task):
        if write_mode in {"dirty", "deleted"}:
            staged = await db.get(AsyncTask, staged_task_id)
            assert staged is not None
            if write_mode == "dirty":
                staged.progress = 0.75
            else:
                await db.delete(staged)
        else:
            db.add(
                AsyncTask(
                    id=staged_task_id,
                    task_type="forbidden-preflight-write",
                    status="done",
                    meta={},
                )
            )
        if write_mode == "flush":
            await db.flush()
        elif write_mode == "commit":
            await db.commit()

    async def handler(*, db, task):
        nonlocal handler_called
        handler_called = True
        return {"unexpected": True}

    registry.register(task_type, handler, owner_scope="global")
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
            if write_mode in {"dirty", "deleted"}:
                setup_db.add(
                    AsyncTask(
                        id=staged_task_id,
                        task_type="existing-preflight-write-target",
                        status="done",
                        progress=0.1,
                        meta={},
                    )
                )

        worker = TaskWorker(
            db_manager=TestManager(),
            heartbeat_interval=60.0,
            task_preflight=preflight,
        )
        returned = await worker.run_once()

        assert returned is not None
        assert returned.status == "failed"
        assert returned.error_message == (
            "RuntimeError: Task preflight must be read-only"
        )
        assert handler_called is False
        async with sessions() as verify_db:
            staged = await verify_db.get(AsyncTask, staged_task_id)
            if write_mode in {"dirty", "deleted"}:
                assert staged is not None
                assert staged.progress == 0.1
            else:
                assert staged is None
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(AsyncTask.id.in_((task_id, staged_task_id)))
            )


@pytest.mark.asyncio
async def test_preflight_core_dml_is_rolled_back_before_handler(test_engine) -> None:
    """Core DML is not in ORM state sets, but the boundary still discards it."""
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    task_id = uuid.uuid4()
    staged_task_id = uuid.uuid4()
    task_type = f"run-once-preflight-core-dml-{uuid.uuid4()}"
    registry = TaskRegistry()
    handler_called = False

    class TestManager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    async def preflight(db, _task):
        await db.execute(
            insert(AsyncTask).values(
                id=staged_task_id,
                task_type="discarded-preflight-core-dml",
                status="done",
                progress=1.0,
                meta={},
            )
        )
        assert not db.new and not db.dirty and not db.deleted

    async def handler(*, db, task):
        nonlocal handler_called
        handler_called = True
        assert db.in_transaction() is False
        assert await db.get(AsyncTask, staged_task_id) is None
        return {"ok": True}

    registry.register(task_type, handler, owner_scope="global")
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
            task_preflight=preflight,
        )
        returned = await worker.run_once()

        assert returned is not None
        assert returned.status == "done"
        assert handler_called is True
        async with sessions() as verify_db:
            assert await verify_db.get(AsyncTask, staged_task_id) is None
    finally:
        registry.unregister(task_type)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(AsyncTask.id.in_((task_id, staged_task_id)))
            )
