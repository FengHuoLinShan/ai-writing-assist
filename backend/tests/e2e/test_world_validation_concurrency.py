from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.project.models import Project
from modules.world.models import WorldValidationRun
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _run(novel_id: uuid.UUID, scope: str) -> WorldValidationRun:
    return WorldValidationRun(
        id=uuid.uuid4(),
        novel_id=novel_id,
        trigger="manual",
        scope=scope,
        policy_version="e2e-v1",
        policy_hash="a" * 64,
        manifest_hash="b" * 64,
        dependency_hash="c" * 64,
    )


async def test_full_single_flight_does_not_block_targeted_and_cascades() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    full_inserted = asyncio.Event()
    release_full = asyncio.Event()

    async def hold_full() -> None:
        async with sessions.begin() as db:
            db.add(_run(novel_id, "full"))
            await db.flush()
            full_inserted.set()
            await release_full.wait()

    async def insert_conflicting_full() -> bool:
        try:
            async with sessions.begin() as db:
                db.add(_run(novel_id, "full"))
                await db.flush()
        except IntegrityError:
            return True
        return False

    holder: asyncio.Task[None] | None = None
    conflict: asyncio.Task[bool] | None = None
    try:
        async with sessions.begin() as db:
            db.add(
                Project(
                    id=novel_id,
                    title="world validation concurrency",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )

        holder = asyncio.create_task(hold_full())
        await asyncio.wait_for(full_inserted.wait(), timeout=2)

        async with sessions.begin() as db:
            db.add(_run(novel_id, "targeted"))
            await asyncio.wait_for(db.flush(), timeout=2)

        conflict = asyncio.create_task(insert_conflicting_full())
        done, _ = await asyncio.wait({conflict}, timeout=0.1)
        assert not done, "second full run must wait for the active transaction"

        release_full.set()
        await asyncio.wait_for(holder, timeout=2)
        assert await asyncio.wait_for(conflict, timeout=2)

        async with sessions.begin() as db:
            assert await db.scalar(
                select(func.count(WorldValidationRun.id)).where(
                    WorldValidationRun.novel_id == novel_id
                )
            ) == 2
            project = await db.get(Project, novel_id)
            assert project is not None
            await db.delete(project)

        async with sessions() as db:
            assert await db.scalar(
                select(func.count(WorldValidationRun.id)).where(
                    WorldValidationRun.novel_id == novel_id
                )
            ) == 0
    finally:
        release_full.set()
        for task in (holder, conflict):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (holder, conflict) if task is not None),
            return_exceptions=True,
        )
        await engine.dispose()
