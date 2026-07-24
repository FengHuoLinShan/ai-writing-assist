from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateIndex

from infrastructure.tasks.enqueuer import (
    build_task_coalescing_key,
    lock_task_coalescing_key,
)
from infrastructure.tasks.facade import (
    enqueue_coalesced_task,
    get_latest_coalesced_task,
)
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask


def test_coalescing_key_is_normalized_digest() -> None:
    novel_id = uuid.uuid4()

    key = build_task_coalescing_key(
        task_type="rag_index_chapter",
        novel_id=str(novel_id).upper(),
        scope=("chapter", "3", "working"),
    )

    assert len(key) == 64
    assert str(novel_id) not in key
    assert key == build_task_coalescing_key(
        task_type="rag_index_chapter",
        novel_id=str(novel_id),
        scope=("chapter", "3", "working"),
    )


def test_coalescing_partial_unique_indexes_compile_for_supported_databases() -> None:
    indexes = {index.name: index for index in AsyncTask.__table__.indexes}
    for name in (
        "uq_async_tasks_coalescing_pending",
        "uq_async_tasks_coalescing_running",
    ):
        index = indexes[name]
        postgres_sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        sqlite_sql = str(CreateIndex(index).compile(dialect=sqlite.dialect()))
        assert "UNIQUE INDEX" in postgres_sql
        assert "WHERE coalescing_key IS NOT NULL" in postgres_sql
        assert "UNIQUE INDEX" in sqlite_sql
        assert "WHERE coalescing_key IS NOT NULL" in sqlite_sql


@pytest.mark.asyncio
async def test_postgres_coalescing_uses_transaction_advisory_lock() -> None:
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    db.execute = AsyncMock()
    bind = MagicMock()
    bind.dialect.name = "postgresql"
    db.get_bind.return_value = bind

    await lock_task_coalescing_key(db, coalescing_key="a" * 64)

    statement, params = db.execute.await_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert params == {"key": f"task_coalescing:{'a' * 64}"}


@pytest.mark.asyncio
async def test_reuse_active_coalesces_pending_task(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    first = await enqueue_coalesced_task(
        db_session,
        task_type="test_coalesced",
        novel_id=novel_id,
        scope=("one",),
        meta={"novel_id": novel_id},
    )
    second = await enqueue_coalesced_task(
        db_session,
        task_type="test_coalesced",
        novel_id=novel_id,
        scope=("one",),
        meta={"novel_id": novel_id},
    )

    assert first.reused is False
    assert second.reused is True
    assert second.task_id == first.task_id
    assert second.status == "pending"


@pytest.mark.asyncio
async def test_one_pending_follower_waits_for_running_owner(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    owner = await enqueue_coalesced_task(
        db_session,
        task_type="test_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
    )
    owner_task = await db_session.get(AsyncTask, uuid.UUID(owner.task_id))
    assert owner_task is not None
    owner_task.mark_running()
    await db_session.flush()

    follower = await enqueue_coalesced_task(
        db_session,
        task_type="test_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
        mode="one_pending_follower",
    )
    duplicate = await enqueue_coalesced_task(
        db_session,
        task_type="test_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
        mode="one_pending_follower",
    )

    assert follower.reused is False
    assert duplicate.reused is True
    assert duplicate.task_id == follower.task_id
    assert await TaskLifecycleService().claim_next(db_session) is None

    owner_task.mark_done()
    await db_session.flush()
    claimed = await TaskLifecycleService().claim_next(db_session)
    assert claimed is not None
    assert str(claimed.id) == follower.task_id


@pytest.mark.asyncio
async def test_retry_is_superseded_when_pending_follower_exists(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    owner = await enqueue_coalesced_task(
        db_session,
        task_type="test_retry_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
    )
    owner_task = await db_session.get(AsyncTask, uuid.UUID(owner.task_id))
    assert owner_task is not None
    owner_task.status = "running"
    owner_task.attempt = 1
    owner_task.max_attempts = 2
    owner_task.recovery_policy = "auto_requeue"
    await db_session.flush()
    follower = await enqueue_coalesced_task(
        db_session,
        task_type="test_retry_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
        mode="one_pending_follower",
    )
    owner_task.status = "failed"
    await db_session.flush()

    await TaskLifecycleService().retry(db_session, task=owner_task)

    assert owner_task.status == "cancelled"
    assert owner_task.transition_reason == "superseded"
    assert follower.task_id != owner.task_id


@pytest.mark.asyncio
async def test_manual_resume_is_superseded_when_pending_follower_exists(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    owner = await enqueue_coalesced_task(
        db_session,
        task_type="test_manual_resume_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
    )
    owner_task = await db_session.get(AsyncTask, uuid.UUID(owner.task_id))
    assert owner_task is not None
    owner_task.mark_running()
    owner_task.recovery_policy = "manual_resume"
    await db_session.flush()
    follower = await enqueue_coalesced_task(
        db_session,
        task_type="test_manual_resume_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
        mode="one_pending_follower",
    )
    owner_task.mark_failed("interrupted")
    owner_task.result = {"recovery_required": True}
    owner_task.meta = {
        **dict(owner_task.meta or {}),
        "recovery_required": True,
    }
    await db_session.flush()

    resumed = await TaskLifecycleService().resume_manual(
        db_session,
        task_id=owner.task_id,
        task_types={"test_manual_resume_follow"},
        novel_id=novel_id,
    )

    assert resumed.status == "cancelled"
    assert owner_task.transition_reason == "superseded"
    assert follower.task_id != owner.task_id


@pytest.mark.asyncio
async def test_exact_claim_cannot_run_pending_follower_before_owner_finishes(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    owner = await enqueue_coalesced_task(
        db_session,
        task_type="test_exact_claim_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
    )
    owner_task = await db_session.get(AsyncTask, uuid.UUID(owner.task_id))
    assert owner_task is not None
    owner_task.mark_running()
    await db_session.flush()
    follower = await enqueue_coalesced_task(
        db_session,
        task_type="test_exact_claim_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
        mode="one_pending_follower",
    )

    claimed = await TaskLifecycleService().claim_exact(
        db_session,
        task_id=uuid.UUID(follower.task_id),
        task_type="test_exact_claim_follow",
    )

    assert claimed is None
    follower_task = await db_session.get(AsyncTask, uuid.UUID(follower.task_id))
    assert follower_task is not None
    assert follower_task.status == "pending"


@pytest.mark.asyncio
async def test_inline_executor_applies_pending_follower_claim_gate(
    db_session: AsyncSession,
) -> None:
    from infrastructure.tasks.inline import run_task_inline
    from infrastructure.tasks.registry import TaskRegistry

    task_type = f"test_inline_follow_{uuid.uuid4().hex}"
    invoked = False

    async def handler(*, db, task):  # type: ignore[no-untyped-def]
        nonlocal invoked
        invoked = True
        return {}

    registry = TaskRegistry()
    registry.register(task_type, handler)
    novel_id = str(uuid.uuid4())
    try:
        owner = await enqueue_coalesced_task(
            db_session,
            task_type=task_type,
            novel_id=novel_id,
            scope=("project",),
            meta={"novel_id": novel_id},
        )
        owner_task = await db_session.get(AsyncTask, uuid.UUID(owner.task_id))
        assert owner_task is not None
        owner_task.mark_running()
        await db_session.flush()
        follower = await enqueue_coalesced_task(
            db_session,
            task_type=task_type,
            novel_id=novel_id,
            scope=("project",),
            meta={"novel_id": novel_id},
            mode="one_pending_follower",
        )

        with pytest.raises(ValueError, match="waiting for its active"):
            await run_task_inline(
                db_session,
                task_id=follower.task_id,
                expected_task_type=task_type,
            )

        assert invoked is False
    finally:
        registry.unregister(task_type)


@pytest.mark.asyncio
async def test_inline_executor_fences_handler_commits_and_finalizes(
    db_session: AsyncSession,
) -> None:
    from infrastructure.tasks.inline import run_task_inline
    from infrastructure.tasks.registry import TaskRegistry

    task_type = f"test_inline_commit_{uuid.uuid4().hex}"
    commit_observed = False

    async def handler(*, db, task):  # type: ignore[no-untyped-def]
        nonlocal commit_observed
        task.update_progress(0.5)
        await db.commit()
        commit_observed = True
        return {"ok": True}

    registry = TaskRegistry()
    registry.register(task_type, handler)
    novel_id = str(uuid.uuid4())
    try:
        queued = await enqueue_coalesced_task(
            db_session,
            task_type=task_type,
            novel_id=novel_id,
            scope=("project",),
            meta={"novel_id": novel_id},
        )

        result = await run_task_inline(
            db_session,
            task_id=queued.task_id,
            expected_task_type=task_type,
        )

        assert result == {"ok": True}
        assert commit_observed is True
        stored = await db_session.get(AsyncTask, uuid.UUID(queued.task_id))
        assert stored is not None
        await db_session.refresh(stored)
        assert stored.status == "done"
        assert stored.progress == 1.0
    finally:
        registry.unregister(task_type)


@pytest.mark.asyncio
async def test_inline_executor_rejects_commit_after_lease_is_replaced(
    db_session: AsyncSession,
) -> None:
    from sqlalchemy import update

    from infrastructure.tasks.inline import run_task_inline
    from infrastructure.tasks.registry import TaskRegistry

    task_type = f"test_inline_lost_lease_{uuid.uuid4().hex}"
    stale_commit_returned = False

    async def handler(*, db, task):  # type: ignore[no-untyped-def]
        nonlocal stale_commit_returned
        await db.execute(
            update(AsyncTask)
            .where(AsyncTask.id == task.id)
            .values(lease_id=str(uuid.uuid4()))
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        stale_commit_returned = True
        return {}

    registry = TaskRegistry()
    registry.register(task_type, handler)
    novel_id = str(uuid.uuid4())
    try:
        queued = await enqueue_coalesced_task(
            db_session,
            task_type=task_type,
            novel_id=novel_id,
            scope=("project",),
            meta={"novel_id": novel_id},
        )

        with pytest.raises(asyncio.CancelledError):
            await run_task_inline(
                db_session,
                task_id=queued.task_id,
                expected_task_type=task_type,
            )

        assert stale_commit_returned is False
        stored = await db_session.get(AsyncTask, uuid.UUID(queued.task_id))
        assert stored is not None
        await db_session.refresh(stored)
        assert stored.status == "cancelled"
    finally:
        registry.unregister(task_type)


@pytest.mark.asyncio
async def test_stale_running_owner_is_superseded_by_pending_follower(
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    owner = await enqueue_coalesced_task(
        db_session,
        task_type="test_stale_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
    )
    owner_task = await db_session.get(AsyncTask, uuid.UUID(owner.task_id))
    assert owner_task is not None
    owner_task.mark_running()
    owner_task.recovery_policy = "auto_requeue"
    owner_task.max_attempts = 2
    owner_task.started_at = datetime.now(UTC) - timedelta(minutes=5)
    owner_task.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
    follower = await enqueue_coalesced_task(
        db_session,
        task_type="test_stale_follow",
        novel_id=novel_id,
        scope=("project",),
        meta={"novel_id": novel_id},
        mode="one_pending_follower",
    )
    await db_session.flush()

    counts = await TaskLifecycleService().recover_stale(
        db_session,
        max_heartbeat_gap=60,
    )

    await db_session.refresh(owner_task)
    assert counts == {"auto_requeued": 0, "failed": 1, "manual_resume": 0}
    assert owner_task.status == "cancelled"
    assert owner_task.transition_reason == "superseded"
    follower_task = await db_session.scalar(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(follower.task_id))
    )
    assert follower_task is not None
    assert follower_task.status == "pending"


@pytest.mark.asyncio
async def test_scope_isolated_by_novel_and_latest_includes_terminal(
    db_session: AsyncSession,
) -> None:
    first_novel = str(uuid.uuid4())
    second_novel = str(uuid.uuid4())
    first = await enqueue_coalesced_task(
        db_session,
        task_type="test_scope",
        novel_id=first_novel,
        scope=("same",),
        meta={"novel_id": first_novel},
    )
    second = await enqueue_coalesced_task(
        db_session,
        task_type="test_scope",
        novel_id=second_novel,
        scope=("same",),
        meta={"novel_id": second_novel},
    )
    assert first.task_id != second.task_id

    first_task = await db_session.get(AsyncTask, uuid.UUID(first.task_id))
    assert first_task is not None
    first_task.mark_done()
    await db_session.flush()
    latest = await get_latest_coalesced_task(
        db_session,
        task_type="test_scope",
        novel_id=first_novel,
        scope=("same",),
    )
    assert latest is not None
    assert latest.task_id == first.task_id
    assert latest.status == "done"
