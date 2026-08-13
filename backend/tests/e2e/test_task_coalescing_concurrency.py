from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.tasks.facade import enqueue_coalesced_task, enqueue_operation_task
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from modules.project.models import Project
from modules.rag.repositories import RagChunkRepository
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_transactions_reuse_one_pending_task() -> None:
    """The PostgreSQL advisory lock and unique index close query/insert races."""
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    task_type = f"coalescing-race-{uuid.uuid4()}"
    novel_id = str(uuid.uuid4())
    ready = 0
    ready_lock = asyncio.Lock()
    release = asyncio.Event()

    async def submit() -> str:
        nonlocal ready
        async with ready_lock:
            ready += 1
            if ready == 2:
                release.set()
        await release.wait()
        async with sessions.begin() as db:
            queued = await enqueue_coalesced_task(
                db,
                task_type=task_type,
                novel_id=novel_id,
                scope=("same",),
                meta={"novel_id": novel_id},
            )
            return queued.task_id

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Project(
                    id=uuid.UUID(novel_id),
                    title="coalescing pending race",
                )
            )

        first_id, second_id = await asyncio.gather(submit(), submit())

        assert first_id == second_id
        async with sessions() as verify_db:
            count = await verify_db.scalar(
                select(func.count())
                .select_from(AsyncTask)
                .where(
                    AsyncTask.task_type == task_type,
                    AsyncTask.status == "pending",
                )
            )
            assert count == 1
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(AsyncTask.task_type == task_type)
            )
            await cleanup_db.execute(
                delete(Project).where(Project.id == uuid.UUID(novel_id))
            )
        await engine.dispose()


async def test_rag_scene_annotation_uses_the_chapter_advisory_lock() -> None:
    """A Scene-only writer cannot pass a chapter replacement in PostgreSQL."""
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    acquired = asyncio.Event()
    release = asyncio.Event()
    contender_acquired = asyncio.Event()
    repo = RagChunkRepository()

    async def holder() -> None:
        async with sessions.begin() as db:
            await repo.lock_chapter_chunks(db, novel_id, 1)
            acquired.set()
            await release.wait()

    async def contender() -> None:
        await acquired.wait()
        async with sessions.begin() as db:
            await repo.lock_chapter_chunks(db, novel_id, 1)
            contender_acquired.set()

    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="rag scene lock race"))

        holder_task = asyncio.create_task(holder())
        contender_task = asyncio.create_task(contender())
        await acquired.wait()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(contender_acquired.wait(), timeout=0.1)
        release.set()
        await asyncio.gather(holder_task, contender_task)
        assert contender_acquired.is_set()
    finally:
        release.set()
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_concurrent_operation_receipt_creates_one_task() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    operation_id = str(uuid.uuid4())
    novel_id = str(uuid.uuid4())
    task_type = f"operation-race-{uuid.uuid4()}"
    release = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def submit() -> str:
        nonlocal ready
        async with ready_lock:
            ready += 1
            if ready == 2:
                release.set()
        await release.wait()
        async with sessions.begin() as db:
            receipt = await enqueue_operation_task(
                db,
                operation_id=operation_id,
                task_type=task_type,
                novel_id=novel_id,
                request_payload={"novel_id": novel_id, "input": "same"},
                meta={"novel_id": novel_id},
            )
            return receipt.task_id

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=uuid.UUID(novel_id), title="operation receipt race"))

        first_id, second_id = await asyncio.gather(submit(), submit())

        assert first_id == second_id == operation_id
        async with sessions() as verify_db:
            assert await verify_db.scalar(
                select(func.count())
                .select_from(AsyncTask)
                .where(AsyncTask.id == uuid.UUID(operation_id))
            ) == 1
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(AsyncTask.id == uuid.UUID(operation_id))
            )
            await cleanup_db.execute(
                delete(Project).where(Project.id == uuid.UUID(novel_id))
            )
        await engine.dispose()


async def test_running_owner_allows_only_one_pending_follower() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=8, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    task_type = f"coalescing-follower-{uuid.uuid4()}"
    novel_id = str(uuid.uuid4())
    lifecycle = TaskLifecycleService()

    async def submit_follower() -> str:
        async with sessions.begin() as db:
            queued = await enqueue_coalesced_task(
                db,
                task_type=task_type,
                novel_id=novel_id,
                scope=("same",),
                meta={"novel_id": novel_id},
                mode="one_pending_follower",
            )
            return queued.task_id

    try:
        async with sessions.begin() as project_db:
            project_db.add(
                Project(
                    id=uuid.UUID(novel_id),
                    title="coalescing pending follower",
                )
            )

        async with sessions.begin() as setup_db:
            owner = await enqueue_coalesced_task(
                setup_db,
                task_type=task_type,
                novel_id=novel_id,
                scope=("same",),
                meta={"novel_id": novel_id},
            )
        async with sessions() as claim_db:
            claimed = await lifecycle.claim_next(claim_db)
            assert claimed is not None
            assert str(claimed.id) == owner.task_id
            owner_lease = str(claimed.lease_id)

        follower_ids = await asyncio.gather(*(submit_follower() for _ in range(6)))
        assert len(set(follower_ids)) == 1

        async with sessions() as blocked_db:
            assert await lifecycle.claim_next(blocked_db) is None

        async with sessions() as finish_db:
            assert await lifecycle.finalize(
                finish_db,
                task_id=uuid.UUID(owner.task_id),
                lease_id=owner_lease,
                status="done",
            )
        async with sessions() as follower_db:
            claimed_follower = await lifecycle.claim_next(follower_db)
            assert claimed_follower is not None
            assert str(claimed_follower.id) == follower_ids[0]
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(AsyncTask).where(AsyncTask.task_type == task_type)
            )
            await cleanup_db.execute(
                delete(Project).where(Project.id == uuid.UUID(novel_id))
            )
        await engine.dispose()
