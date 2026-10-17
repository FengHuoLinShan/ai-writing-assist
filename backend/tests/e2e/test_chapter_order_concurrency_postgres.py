"""Real PostgreSQL locks fence new versions against chapter-order CAS."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app  # noqa: F401 - register the production Story ports
from core.container import container_scope
from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.operation_trace_models import (
    AssistantOperationTrace,
    AssistantOperationTracePreference,
)
from modules.assistant.operation_trace_service import set_operation_trace_preference
from modules.evidence.indexing.models import RagIndexState
from modules.project.models import Project
from modules.story.continuity.models import StoryChapterOrderReceipt
from modules.writing.draft_service import WritingChapterOrderService
from modules.writing.models import WritingChapterOrderOperation, WritingDraft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import ChapterOrderPreviewRequest, WritingDraftCreate
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_chapter_order_http_trace_and_foreign_owner_isolation(
    db_session: AsyncSession,
    async_client: AsyncClient,
) -> None:
    preference = await db_session.get(
        AssistantOperationTracePreference, BOOTSTRAP_ACCOUNT_ID
    )
    original_preference = (
        {
            column.name: getattr(preference, column.name)
            for column in preference.__table__.columns
        }
        if preference is not None
        else None
    )
    try:
        await set_operation_trace_preference(db_session, str(BOOTSTRAP_ACCOUNT_ID), True)
        created = await async_client.post(
            "/api/projects", json={"title": "合成章节顺序回执"}
        )
        assert created.status_code == 201, created.text
        novel_id = created.json()["id"]
        for chapter_index in (1, 2):
            response = await async_client.post(
                "/api/writing/drafts/autosave",
                json={
                    "novel_id": novel_id,
                    "chapter_index": chapter_index,
                    "content": f"第{chapter_index}章合成正文。",
                },
            )
            assert response.status_code == 201, response.text
        params = {"novel_id": novel_id}
        preview = await async_client.post(
            "/api/writing/chapters/order/preview",
            params=params,
            json={"chapter_indices": [2, 1]},
        )
        assert preview.status_code == 200, preview.text
        receipt_id = preview.json()["receipt_id"]
        confirm_url = f"/api/writing/chapters/order/{receipt_id}/confirm"
        confirm_body = {
            "expected_preview_hash": preview.json()["preview_hash"],
            "confirmed": True,
        }
        executed = await async_client.post(confirm_url, params=params, json=confirm_body)
        assert executed.status_code == 200, executed.text
        replay = await async_client.post(confirm_url, params=params, json=confirm_body)
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        restore_preview = await async_client.get(
            f"/api/writing/chapters/order/{receipt_id}/restore-preview", params=params
        )
        assert restore_preview.status_code == 200, restore_preview.text
        restore_url = f"/api/writing/chapters/order/{receipt_id}/restore"
        restore_body = {
            "expected_preview_hash": restore_preview.json()["restore_preview_hash"],
            "confirmed": True,
        }
        restored = await async_client.post(restore_url, params=params, json=restore_body)
        assert restored.status_code == 200, restored.text
        assert restored.json()["result_ref"] == executed.json()["result_ref"]
        replay_restore = await async_client.post(
            restore_url, params=params, json=restore_body
        )
        assert replay_restore.status_code == 200
        assert replay_restore.json()["replayed"] is True
        traces = (
            await db_session.scalars(
                select(AssistantOperationTrace).where(
                    AssistantOperationTrace.novel_id == UUID(novel_id)
                )
            )
        ).all()
        original = [
            row
            for row in traces
            if row.op_id == "writing.chapter.reorder" and row.event_type == "executed"
        ]
        reversal = [
            row
            for row in traces
            if row.op_id == "writing.chapter.reorder" and row.event_type == "restored"
        ]
        assert len(original) == len(reversal) == 1
        assert original[0].call_id == reversal[0].call_id
        assert executed.json()["result_ref"] in original[0].result_refs
        assert [
            row.event_type
            for row in traces
            if row.op_id == "writing.chapter.reorder.restore"
        ].count("executed") == 1

        foreign = Account(support_code=f"A1-{uuid4().hex[:12]}")
        db_session.add(foreign)
        await db_session.flush()
        project = await db_session.get(Project, UUID(novel_id))
        assert project is not None
        project.owner_id = foreign.id
        await db_session.flush()
        denied = await async_client.get(
            "/api/writing/chapters/order/history", params=params
        )
        assert denied.status_code == 404
        denied_timeline = await async_client.get(
            f"/api/novels/{novel_id}/memories/fact-timeline"
        )
        assert denied_timeline.status_code == 404

    finally:
        preference = await db_session.get(
            AssistantOperationTracePreference, BOOTSTRAP_ACCOUNT_ID
        )
        if original_preference is None:
            if preference is not None:
                await db_session.delete(preference)
        else:
            assert preference is not None
            for key, value in original_preference.items():
                setattr(preference, key, value)
        await db_session.flush()


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


async def test_chapter_order_pg_rolls_back_dirty_index_and_story_receipt(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid4()
    db_session.add(Project(id=novel_id, title="chapter order PG rollback"))
    await db_session.flush()
    repo = WritingDraftRepository()
    for index in (1, 2):
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=str(novel_id), chapter_index=index, content=f"第{index}章"
            ),
        )
    service = WritingChapterOrderService()
    preview = await service.preview(
        db_session,
        str(novel_id),
        ChapterOrderPreviewRequest(chapter_indices=[2, 1]),
    )

    state_query = select(
        RagIndexState.chapter_index,
        RagIndexState.content_mode,
        RagIndexState.requested_source_id,
        RagIndexState.requested_hash,
        RagIndexState.status,
        RagIndexState.active_task_id,
        RagIndexState.generation,
    ).where(RagIndexState.novel_id == novel_id)
    task_query = select(AsyncTask.id).where(
        AsyncTask.novel_id == novel_id,
        AsyncTask.task_type == "rag_index_chapter",
    )
    before_states = set((await db_session.execute(state_query)).all())
    before_tasks = set((await db_session.scalars(task_query)).all())

    async def fail_standing(_db, *, novel_id: str) -> None:
        raise RuntimeError(f"invalidation failed for {novel_id}")

    with container_scope(
        {"story.invalidate_world_progression_for_reorder": fail_standing}
    ):
        with pytest.raises(RuntimeError, match="invalidation failed"):
            async with db_session.begin_nested():
                await service.confirm(
                    db_session,
                    str(novel_id),
                    str(preview.receipt_id),
                    expected_preview_hash=preview.preview_hash,
                    confirmed=True,
                )
    drafts = (
        await db_session.scalars(
            select(WritingDraft).where(WritingDraft.novel_id == novel_id)
        )
    ).all()
    assert sorted(draft.chapter_index for draft in drafts) == [1, 2]
    operation = await db_session.get(WritingChapterOrderOperation, preview.receipt_id)
    assert operation is not None and operation.status == "previewed"
    assert (
        await db_session.scalars(
            select(StoryChapterOrderReceipt).where(
                StoryChapterOrderReceipt.novel_id == novel_id
            )
        )
    ).all() == []
    assert set((await db_session.execute(state_query)).all()) == before_states
    assert set((await db_session.scalars(task_query)).all()) == before_tasks


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
