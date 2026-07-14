from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.project.models import Project
from modules.writing.models import WritingDraft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_first_versions_are_serialized_per_chapter() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    first_created = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def create_first() -> int:
        async with sessions() as db:
            await db.begin()
            draft = await WritingDraftRepository().create(
                db,
                WritingDraftCreate(
                    novel_id=str(novel_id),
                    chapter_index=1,
                    content="first",
                ),
            )
            first_created.set()
            await release_first.wait()
            await db.commit()
            return draft.version_number

    async def create_second() -> int:
        await first_created.wait()
        async with sessions() as db:
            await db.begin()
            second_started.set()
            draft = await WritingDraftRepository().create(
                db,
                WritingDraftCreate(
                    novel_id=str(novel_id),
                    chapter_index=1,
                    content="second",
                ),
            )
            await db.commit()
            return draft.version_number

    first_task: asyncio.Task[int] | None = None
    second_task: asyncio.Task[int] | None = None
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="writing version concurrency"))

        first_task = asyncio.create_task(create_first())
        await first_created.wait()
        second_task = asyncio.create_task(create_second())
        await second_started.wait()

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the second allocator must wait for the chapter lock"

        release_first.set()
        versions = await asyncio.gather(first_task, second_task)
        assert versions == [1, 2]

        async with sessions() as db:
            stored = await WritingDraftRepository().get_version_history(
                db,
                novel_id,
                1,
            )
            assert [draft.version_number for draft in stored] == [2, 1]
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
        async with sessions.begin() as db:
            await db.execute(
                delete(WritingDraft).where(WritingDraft.novel_id == novel_id)
            )
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
