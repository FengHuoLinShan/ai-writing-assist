from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.story.outline_state.scene_workbench import SceneWorkbenchService
from modules.story.outline_state.schemas import SceneChapterQuickCreate
from modules.writing.models import WritingDraft
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_chapter_links_merge_without_lost_update() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    first_updated = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    service = SceneWorkbenchService()

    async def link_first() -> None:
        async with sessions() as db:
            await db.begin()
            await service.link_scene_to_chapter(db, str(novel_id), 1, str(scene_id))
            first_updated.set()
            await release_first.wait()
            await db.commit()

    async def link_second() -> None:
        await first_updated.wait()
        async with sessions() as db:
            await db.begin()
            second_started.set()
            await service.link_scene_to_chapter(db, str(novel_id), 2, str(scene_id))
            await db.commit()

    first_task: asyncio.Task[None] | None = None
    second_task: asyncio.Task[None] | None = None
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="scene link concurrency"))
            await setup_db.flush()
            setup_db.add_all(
                [
                    WritingDraft(
                        novel_id=novel_id,
                        chapter_index=chapter,
                        version_number=1,
                        title=f"第 {chapter} 章",
                        content="正文",
                        status="draft",
                    )
                    for chapter in (1, 2)
                ]
            )
            setup_db.add(
                Scene(
                    id=scene_id,
                    novel_id=novel_id,
                    scene_index=0,
                    title="跨章 Scene",
                    status="draft",
                    chapter_ids=[],
                    scene_chunks=[],
                )
            )

        first_task = asyncio.create_task(link_first())
        await first_updated.wait()
        second_task = asyncio.create_task(link_second())
        await second_started.wait()

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the second merge must wait for the Scene row lock"

        release_first.set()
        await asyncio.gather(first_task, second_task)

        async with sessions() as verify_db:
            scene = await verify_db.scalar(select(Scene).where(Scene.id == scene_id))
            assert scene is not None
            assert scene.chapter_ids == ["1", "2"]
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


async def test_concurrent_quick_creates_allocate_distinct_tail_indexes() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    first_created = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    service = SceneWorkbenchService()

    async def create_first() -> int:
        async with sessions() as db:
            await db.begin()
            scene = await service.create_scene_for_chapter(
                db,
                str(novel_id),
                1,
                SceneChapterQuickCreate(title="第一场"),
            )
            first_created.set()
            await release_first.wait()
            await db.commit()
            return scene.scene_index

    async def create_second() -> int:
        await first_created.wait()
        async with sessions() as db:
            await db.begin()
            second_started.set()
            scene = await service.create_scene_for_chapter(
                db,
                str(novel_id),
                1,
                SceneChapterQuickCreate(title="第二场"),
            )
            await db.commit()
            return scene.scene_index

    first_task: asyncio.Task[int] | None = None
    second_task: asyncio.Task[int] | None = None
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="scene order concurrency"))
            setup_db.add(
                WritingDraft(
                    novel_id=novel_id,
                    chapter_index=1,
                    version_number=1,
                    title="第一章",
                    content="正文",
                    status="draft",
                )
            )

        first_task = asyncio.create_task(create_first())
        await first_created.wait()
        second_task = asyncio.create_task(create_second())
        await second_started.wait()

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the second allocator must wait for the project order lock"

        release_first.set()
        indexes = await asyncio.gather(first_task, second_task)
        assert indexes == [0, 1]
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
