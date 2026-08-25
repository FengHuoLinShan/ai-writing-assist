from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.project.models import Project
from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.repositories import SceneCheckpointRepository
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _values(source_hash: str) -> dict:
    return {
        "status": "ready",
        "confirmed": False,
        "is_current": True,
        "state_json": {"entities": {}},
        "evidence_refs": [],
        "display_summary": source_hash,
        "source_hash": source_hash,
        "retry_count": 0,
    }


async def test_concurrent_first_checkpoint_creation_serializes_per_dimension() -> None:
    """An absent row still needs a lock before the partial unique index can help."""
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    first_written = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    first_task: asyncio.Task[None] | None = None
    second_task: asyncio.Task[None] | None = None

    async def create_first() -> None:
        async with sessions() as db:
            await db.begin()
            await SceneCheckpointRepository().replace_system(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                scene_index=0,
                dimension="entities",
                values=_values("first"),
            )
            first_written.set()
            await release_first.wait()
            await db.commit()

    async def create_second() -> None:
        await first_written.wait()
        async with sessions.begin() as db:
            second_started.set()
            await SceneCheckpointRepository().replace_system(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                scene_index=0,
                dimension="entities",
                values=_values("second"),
            )

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="scene checkpoint concurrency"))

        first_task = asyncio.create_task(create_first())
        await asyncio.wait_for(first_written.wait(), timeout=2.0)
        second_task = asyncio.create_task(create_second())
        await asyncio.wait_for(second_started.wait(), timeout=2.0)

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the second creator must wait for the first transaction"

        release_first.set()
        await asyncio.gather(first_task, second_task)

        async with sessions() as verify_db:
            rows = list(
                (
                    await verify_db.execute(
                        select(MemorySceneCheckpoint)
                        .where(
                            MemorySceneCheckpoint.novel_id == novel_id,
                            MemorySceneCheckpoint.scene_id == scene_id,
                            MemorySceneCheckpoint.dimension == "entities",
                        )
                        .order_by(MemorySceneCheckpoint.created_at)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2
            assert sum(item.is_current for item in rows) == 1
            assert next(item for item in rows if item.is_current).source_hash == "second"
    finally:
        release_first.set()
        pending = [
            task
            for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
