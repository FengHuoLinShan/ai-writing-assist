"""Real PostgreSQL locks fence new versions against chapter-order CAS."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app  # noqa: F401 - register the production Story ports
from core.errors import ConflictError
from modules.project.models import Project
from modules.story.continuity.models import StoryChapterOrderReceipt
from modules.writing.draft_service import WritingChapterOrderService
from modules.writing.models import WritingChapterOrderOperation, WritingDraft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import ChapterOrderPreviewRequest, WritingDraftCreate
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def _seed(sessions, novel_id):
    async with sessions.begin() as db:
        db.add(Project(id=novel_id, title="chapter order concurrency"))
        await db.flush()
        for index in (1, 2):
            await WritingDraftRepository().create(
                db,
                WritingDraftCreate(
                    novel_id=str(novel_id),
                    chapter_index=index,
                    content=f"第{index}章",
                ),
            )
    async with sessions.begin() as db:
        return await WritingChapterOrderService().preview(
            db,
            str(novel_id),
            ChapterOrderPreviewRequest(chapter_indices=[2, 1]),
        )


async def test_new_chapter_first_version_invalidates_concurrent_reorder() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid4()
    release_writer = asyncio.Event()
    writer_ready = asyncio.Event()
    confirm_started = asyncio.Event()
    tasks: list[asyncio.Task] = []
    try:
        preview = await _seed(sessions, novel_id)

        async def create_new_chapter():
            async with sessions.begin() as db:
                await WritingDraftRepository().create(
                    db,
                    WritingDraftCreate(
                        novel_id=str(novel_id),
                        chapter_index=3,
                        content="第三章是作者的新内容",
                    ),
                )
                writer_ready.set()
                await release_writer.wait()

        async def confirm_order():
            async with sessions.begin() as db:
                confirm_started.set()
                await WritingChapterOrderService().confirm(
                    db,
                    str(novel_id),
                    str(preview.receipt_id),
                    expected_preview_hash=preview.preview_hash,
                    confirmed=True,
                )

        tasks.append(asyncio.create_task(create_new_chapter()))
        await writer_ready.wait()
        tasks.append(asyncio.create_task(confirm_order()))
        await confirm_started.wait()
        done, _ = await asyncio.wait({tasks[1]}, timeout=0.1)
        assert not done, "reorder must wait for the new chapter's catalog lock"
        release_writer.set()
        await tasks[0]
        with pytest.raises(ConflictError, match="已变化"):
            await tasks[1]

        async with sessions() as db:
            drafts = (
                await db.scalars(
                    select(WritingDraft).where(WritingDraft.novel_id == novel_id)
                )
            ).all()
            assert {(row.chapter_index, row.version_number) for row in drafts} == {
                (1, 1),
                (2, 1),
                (3, 1),
            }
            operation = await db.get(WritingChapterOrderOperation, preview.receipt_id)
            assert operation is not None and operation.status == "previewed"
            assert (
                await db.scalar(
                    select(StoryChapterOrderReceipt.id).where(
                        StoryChapterOrderReceipt.novel_id == novel_id
                    )
                )
                is None
            )
    finally:
        release_writer.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_new_version_invalidates_concurrent_restore() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid4()
    release_writer = asyncio.Event()
    writer_ready = asyncio.Event()
    restore_started = asyncio.Event()
    tasks: list[asyncio.Task] = []
    try:
        preview = await _seed(sessions, novel_id)
        async with sessions.begin() as db:
            await WritingChapterOrderService().confirm(
                db,
                str(novel_id),
                str(preview.receipt_id),
                expected_preview_hash=preview.preview_hash,
                confirmed=True,
            )
        async with sessions.begin() as db:
            restore_preview = await WritingChapterOrderService().preview_restore(
                db, str(novel_id), str(preview.receipt_id)
            )
            assert restore_preview.can_restore is True

        async def add_version():
            async with sessions.begin() as db:
                await WritingDraftRepository().create(
                    db,
                    WritingDraftCreate(
                        novel_id=str(novel_id),
                        chapter_index=1,
                        content="重排后追加的作者正文",
                    ),
                )
                writer_ready.set()
                await release_writer.wait()

        async def restore_order():
            async with sessions.begin() as db:
                restore_started.set()
                await WritingChapterOrderService().restore(
                    db,
                    str(novel_id),
                    str(preview.receipt_id),
                    expected_preview_hash=restore_preview.restore_preview_hash,
                    confirmed=True,
                )

        tasks.append(asyncio.create_task(add_version()))
        await writer_ready.wait()
        tasks.append(asyncio.create_task(restore_order()))
        await restore_started.wait()
        done, _ = await asyncio.wait({tasks[1]}, timeout=0.1)
        assert not done, "restore must wait for the chapter version lock"
        release_writer.set()
        await tasks[0]
        with pytest.raises(ConflictError, match="来源已有变化"):
            await tasks[1]

        async with sessions() as db:
            operation = await db.get(WritingChapterOrderOperation, preview.receipt_id)
            receipt = await db.get(StoryChapterOrderReceipt, preview.receipt_id)
            assert operation is not None and operation.status == "executed"
            assert receipt is not None and receipt.status == "applied"
            drafts = (
                await db.scalars(
                    select(WritingDraft).where(WritingDraft.novel_id == novel_id)
                )
            ).all()
            chapter_versions = sorted(
                row.version_number for row in drafts if row.chapter_index == 1
            )
            assert chapter_versions == [1, 2]
    finally:
        release_writer.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
