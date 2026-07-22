"""
TB1: RAG 章节索引 — 测试
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate


@pytest.fixture
def repo() -> RagChunkRepository:
    return RagChunkRepository()


def _new_task_handler_session(
    db_session: AsyncSession,
    checkpoint: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncSession:
    from infrastructure.tasks.worker import _TaskHandlerSession

    bind = db_session.bind
    assert bind is not None
    session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    if checkpoint is None:

        async def checkpoint() -> bool:
            return True

    session.set_task_commit_hook(checkpoint)
    return session

@pytest.mark.asyncio
async def test_index_state_coalesces_requests_and_requeues_latest_source(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from unittest.mock import MagicMock, patch

    from modules.rag.contracts import RagIndexReport
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    first_source = await create_draft_only(
        db_session,
        test_project_id,
        19,
        content="第一个工作稿",
    )
    service = RagIndexStateService()
    enqueue = MagicMock(side_effect=["task-1", "task-2"])
    with patch(
        "modules.rag.index_state.enqueue_task",
        autospec=True,
        side_effect=enqueue,
    ):
        first = await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=19,
            content_mode="working",
        )
        duplicate = await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=19,
            content_mode="working",
        )

        assert first["task_id"] == "task-1"
        assert duplicate["task_id"] is None
        assert enqueue.call_count == 1

        await service.mark_running(
            db_session,
            novel_id=test_project_id,
            chapter_index=19,
            content_mode="working",
        )
        second_source = await create_draft_only(
            db_session,
            test_project_id,
            19,
            content="执行中又产生的最新工作稿",
        )
        refreshed = await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=19,
            content_mode="working",
        )
        assert refreshed["task_id"] is None
        assert refreshed["requested_source_id"] == second_source.id
        assert enqueue.call_count == 1

        requeued = await service.finish(
            db_session,
            novel_id=test_project_id,
            report=RagIndexReport(
                chapter_index=19,
                content_mode="working",
                source_draft_id=first_source.id,
                source_content_hash=first_source.content_hash,
                chunks_created=1,
            ),
        )

    assert requeued == "task-2"
    assert enqueue.call_count == 2


@pytest.mark.asyncio
async def test_queued_index_claim_refreshes_source_changed_before_execution(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from unittest.mock import MagicMock, patch

    from modules.rag.contracts import RagIndexReport
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    first_source = await create_draft_only(
        db_session,
        test_project_id,
        23,
        content="入队时的工作稿",
    )
    service = RagIndexStateService()
    enqueue = MagicMock(return_value="task-1")
    with patch(
        "modules.rag.index_state.enqueue_task",
        autospec=True,
        side_effect=enqueue,
    ):
        requested = await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=23,
            content_mode="working",
        )
        assert requested["requested_source_id"] == first_source.id

        latest_source = await create_draft_only(
            db_session,
            test_project_id,
            23,
            content="执行前已经切换的工作稿",
        )
        assert await service.mark_running(
            db_session,
            novel_id=test_project_id,
            chapter_index=23,
            content_mode="working",
        )

        stored = await service._get(
            db_session,
            novel_id=test_project_id,
            chapter_index=23,
            content_mode="working",
            lock=False,
        )
        assert stored is not None
        assert str(stored.requested_source_id) == latest_source.id
        assert stored.requested_hash == latest_source.content_hash

        followup = await service.finish(
            db_session,
            novel_id=test_project_id,
            report=RagIndexReport(
                chapter_index=23,
                content_mode="working",
                source_draft_id=latest_source.id,
                source_content_hash=latest_source.content_hash,
                chunks_created=1,
            ),
        )

    assert followup is None
    assert enqueue.call_count == 1


@pytest.mark.asyncio
async def test_mark_index_dirty_records_publish_source_without_extra_task(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from unittest.mock import MagicMock, patch

    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_published_draft_only

    source = await create_published_draft_only(
        db_session,
        test_project_id,
        20,
        content="新发布正文",
    )
    enqueue = MagicMock()
    with patch(
        "modules.rag.index_state.enqueue_task",
        autospec=True,
        side_effect=enqueue,
    ):
        state = await RagIndexStateService().mark_dirty(
            db_session,
            novel_id=test_project_id,
            chapter_index=20,
            content_mode="canonical",
        )

    assert state["status"] == "pending"
    assert state["requested_source_id"] == source.id
    assert state["requested_hash"] == source.content_hash
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_direct_and_queued_index_claims_skip_duplicate_execution(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.contracts import RagIndexReport
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_published_draft_only

    source = await create_published_draft_only(
        db_session,
        test_project_id,
        21,
        content="只应索引一次",
    )
    service = RagIndexStateService()
    await service.mark_dirty(
        db_session,
        novel_id=test_project_id,
        chapter_index=21,
        content_mode="canonical",
    )

    assert await service.begin_direct(
        db_session,
        novel_id=test_project_id,
        chapter_index=21,
        content_mode="canonical",
    )
    assert not await service.begin_direct(
        db_session,
        novel_id=test_project_id,
        chapter_index=21,
        content_mode="canonical",
    )
    assert not await service.mark_running(
        db_session,
        novel_id=test_project_id,
        chapter_index=21,
        content_mode="canonical",
    )

    await service.finish(
        db_session,
        novel_id=test_project_id,
        report=RagIndexReport(
            chapter_index=21,
            content_mode="canonical",
            source_draft_id=source.id,
            source_content_hash=source.content_hash,
            chunks_created=1,
        ),
    )

    assert not await service.begin_direct(
        db_session,
        novel_id=test_project_id,
        chapter_index=21,
        content_mode="canonical",
    )
    assert await service.begin_direct(
        db_session,
        novel_id=test_project_id,
        chapter_index=21,
        content_mode="canonical",
        force=True,
    )


@pytest.mark.asyncio
async def test_legacy_queued_index_claim_creates_missing_state(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    source = await create_draft_only(
        db_session,
        test_project_id,
        22,
        content="旧入队路径仍可建立状态",
    )
    service = RagIndexStateService()

    assert await service.mark_running(
        db_session,
        novel_id=test_project_id,
        chapter_index=22,
        content_mode="working",
    )
    state = await service.freshness(
        db_session,
        novel_id=test_project_id,
        content_mode="working",
        chapter_from=22,
        chapter_to=22,
    )

    assert state["total"] == 1
    assert state["statuses"] == ["running"]
    stored = await service._get(
        db_session,
        novel_id=test_project_id,
        chapter_index=22,
        content_mode="working",
        lock=False,
    )
    assert stored is not None
    assert str(stored.requested_source_id) == source.id
    assert stored.requested_hash == source.content_hash


@pytest.mark.asyncio
async def test_prepared_index_claim_rejects_a_changed_source_before_writes(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    source = await create_draft_only(
        db_session,
        test_project_id,
        24,
        content="最新工作稿",
    )
    service = RagIndexStateService()

    stale_claim = await service.begin_prepared(
        db_session,
        novel_id=test_project_id,
        chapter_index=24,
        content_mode="working",
        source_draft_id=source.id,
        source_content_hash="0" * 64,
    )

    assert stale_claim == "source_changed"
    assert (
        await service._get(  # noqa: SLF001 - verify no stale running owner is left
            db_session,
            novel_id=test_project_id,
            chapter_index=24,
            content_mode="working",
            lock=False,
        )
        is None
    )

    current_claim = await service.begin_prepared(
        db_session,
        novel_id=test_project_id,
        chapter_index=24,
        content_mode="working",
        source_draft_id=source.id,
        source_content_hash=source.content_hash,
    )
    assert current_claim == "claimed"

    # In the task-only protocol a legitimate owner never commits "running":
    # it commits running + chunks + finish together. A visible running row is
    # therefore an orphan from the legacy path and must be reclaimable.
    await db_session.commit()
    orphan_reclaim = await service.begin_prepared(
        db_session,
        novel_id=test_project_id,
        chapter_index=24,
        content_mode="working",
        source_draft_id=source.id,
        source_content_hash=source.content_hash,
    )
    assert orphan_reclaim == "claimed"


@pytest.mark.asyncio
async def test_failed_index_state_can_be_requeued(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    source = await create_draft_only(
        db_session,
        test_project_id,
        28,
        content="失败状态必须允许后续重试。",
    )
    service = RagIndexStateService()
    enqueue = MagicMock(side_effect=["task-1", "task-2"])
    with patch(
        "modules.rag.index_state.enqueue_task",
        autospec=True,
        side_effect=enqueue,
    ):
        first = await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=28,
            content_mode="working",
        )
        await service.fail(
            db_session,
            novel_id=test_project_id,
            chapter_index=28,
            content_mode="working",
            error="provider unavailable",
            expected_source_id=source.id,
            expected_source_hash=source.content_hash,
            match_expected_source=True,
        )
        failed = await service._get(  # noqa: SLF001 - verify retry transition
            db_session,
            novel_id=test_project_id,
            chapter_index=28,
            content_mode="working",
            lock=False,
        )
        assert failed is not None
        assert failed.status == "failed"

        retried = await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=28,
            content_mode="working",
        )

    assert first["task_id"] == "task-1"
    assert retried["task_id"] == "task-2"
    assert retried["status"] == "pending"
    assert enqueue.call_count == 2


@pytest.mark.asyncio
async def test_legacy_direct_index_failure_transitions_running_to_failed(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    await create_draft_only(
        db_session,
        test_project_id,
        32,
        content="legacy eval indexing source",
    )
    service = RagIndexStateService()
    claimed = await service.begin_direct(
        db_session,
        novel_id=test_project_id,
        chapter_index=32,
        content_mode="working",
    )

    changed = await service.fail(
        db_session,
        novel_id=test_project_id,
        chapter_index=32,
        content_mode="working",
        error="legacy indexing failed",
    )
    stored = await service._get(  # noqa: SLF001 - verify legacy transition
        db_session,
        novel_id=test_project_id,
        chapter_index=32,
        content_mode="working",
        lock=False,
    )

    assert claimed is True
    assert changed is True
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_message == "legacy indexing failed"


@pytest.mark.asyncio
async def test_old_failure_cannot_overwrite_fresh_success(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.contracts import RagIndexReport
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    source = await create_draft_only(
        db_session,
        test_project_id,
        30,
        content="并发成功不能被旧失败覆盖。",
    )
    service = RagIndexStateService()
    assert (
        await service.begin_prepared(
            db_session,
            novel_id=test_project_id,
            chapter_index=30,
            content_mode="working",
            source_draft_id=source.id,
            source_content_hash=source.content_hash,
        )
        == "claimed"
    )
    await service.finish(
        db_session,
        novel_id=test_project_id,
        report=RagIndexReport(
            chapter_index=30,
            content_mode="working",
            source_draft_id=source.id,
            source_content_hash=source.content_hash,
        ),
    )

    changed = await service.fail(
        db_session,
        novel_id=test_project_id,
        chapter_index=30,
        content_mode="working",
        error="late provider failure",
        expected_source_id=source.id,
        expected_source_hash=source.content_hash,
        match_expected_source=True,
    )
    stored = await service._get(  # noqa: SLF001 - verify fenced transition
        db_session,
        novel_id=test_project_id,
        chapter_index=30,
        content_mode="working",
        lock=False,
    )

    assert changed is False
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.error_message is None


@pytest.mark.asyncio
async def test_old_failure_cannot_overwrite_new_source_pending(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.rag.index_state import RagIndexStateService
    from modules.writing.facade import create_draft_only

    old_source = await create_draft_only(
        db_session,
        test_project_id,
        31,
        content="旧源",
    )
    service = RagIndexStateService()
    with patch(
        "modules.rag.index_state.enqueue_task",
        autospec=True,
        return_value="task-1",
    ):
        await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=31,
            content_mode="working",
        )
        new_source = await create_draft_only(
            db_session,
            test_project_id,
            31,
            content="新源",
        )
        await service.request(
            db_session,
            novel_id=test_project_id,
            chapter_index=31,
            content_mode="working",
        )

    changed = await service.fail(
        db_session,
        novel_id=test_project_id,
        chapter_index=31,
        content_mode="working",
        error="old attempt failed",
        expected_source_id=old_source.id,
        expected_source_hash=old_source.content_hash,
        match_expected_source=True,
    )
    stored = await service._get(  # noqa: SLF001 - verify fenced transition
        db_session,
        novel_id=test_project_id,
        chapter_index=31,
        content_mode="working",
        lock=False,
    )

    assert changed is False
    assert stored is not None
    assert stored.status == "pending"
    assert str(stored.requested_source_id) == new_source.id
    assert stored.requested_hash == new_source.content_hash
    assert stored.error_message is None


@pytest.mark.asyncio
async def test_task_index_rejects_an_ordinary_session(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
    repo: RagChunkRepository,
) -> None:
    from modules.rag.indexing import IndexingService

    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await IndexingService(repo=repo).index_chapter_for_task(
            db_session,
            uuid.UUID(test_project_id),
            1,
        )


@pytest.mark.asyncio
async def test_task_index_releases_transaction_before_embedding(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
    repo: RagChunkRepository,
) -> None:
    from modules.rag.indexing import IndexingService
    from modules.writing.facade import create_published_draft_only

    await create_published_draft_only(
        db_session,
        test_project_id,
        25,
        content="任务索引必须在无数据库事务时等待 embedding。" * 80,
    )
    embedding_transaction_states: list[bool] = []
    checkpoint_count = 0

    from infrastructure.tasks.worker import _TaskHandlerSession

    bind = db_session.bind
    assert bind is not None
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return True

    task_session.set_task_commit_hook(_checkpoint)

    async def _generate_embedding(texts):  # type: ignore[no-untyped-def]
        embedding_transaction_states.append(task_session.in_transaction())
        return [[0.1] * 768 for _text in texts]

    try:
        with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
            client_cls.return_value.generate_embedding = AsyncMock(
                side_effect=_generate_embedding
            )
            outcome = await IndexingService(repo=repo).index_chapter_for_task(
                task_session,
                uuid.UUID(test_project_id),
                25,
            )

        assert embedding_transaction_states == [False]
        assert checkpoint_count == 2
        assert outcome.status == "indexed"
        assert outcome.report.chunks_created > 0
        chunks = await repo.find_by_chapter(
            task_session,
            uuid.UUID(test_project_id),
            25,
            content_mode="canonical",
        )
        assert len(chunks) == outcome.report.chunks_created
        assert all(chunk.embedding_status == "succeeded" for chunk in chunks)
    finally:
        await task_session.close()


@pytest.mark.asyncio
async def test_task_index_revalidates_same_source_row_after_embedding_checkpoint(
    tmp_path: Path,
) -> None:
    """A checkpoint must not let expire_on_commit=False reuse a stale draft."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from core.base import Base
    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.project.models import Project
    from modules.rag.index_state import RagIndexStateService
    from modules.rag.indexing import IndexingService, _ChapterIndexPlan
    from modules.writing.models import WritingDraft
    from modules.writing.source_hashing import hash_text

    database_path = tmp_path / "rag-identity-map.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    project_id = uuid.uuid4()
    draft_id = uuid.uuid4()
    old_content = "checkpoint 前的旧正文。" * 80
    new_content = "embedding 期间并发更新的新正文。" * 80
    checkpoint_count = 0
    mutation_count = 0
    embedding_transaction_states: list[bool] = []
    retained_drafts: list[WritingDraft] = []

    class RetainingIndexingService(IndexingService):
        async def _prepare_chapter_index(
            self,
            db: AsyncSession,
            novel_id: uuid.UUID,
            chapter_index: int,
            *,
            content_mode: str,
        ) -> _ChapterIndexPlan:
            plan = await super()._prepare_chapter_index(
                db,
                novel_id,
                chapter_index,
                content_mode=content_mode,
            )
            loaded_draft = await db.get(WritingDraft, draft_id)
            assert loaded_draft is not None
            retained_drafts.append(loaded_draft)
            return plan

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with AsyncSession(engine, expire_on_commit=False) as setup_session:
            setup_session.add(Project(id=project_id, title="identity map revalidation"))
            setup_session.add(
                WritingDraft(
                    id=draft_id,
                    novel_id=project_id,
                    chapter_index=1,
                    title="第一章",
                    content=old_content,
                    content_hash=hash_text(old_content),
                    version_number=1,
                    status="published",
                )
            )
            await setup_session.commit()

        task_session = _TaskHandlerSession(
            bind=engine,
            expire_on_commit=False,
            autoflush=False,
        )

        async def _checkpoint() -> bool:
            nonlocal checkpoint_count
            checkpoint_count += 1
            return True

        task_session.set_task_commit_hook(_checkpoint)

        async def _generate_embedding(texts):  # type: ignore[no-untyped-def]
            nonlocal mutation_count
            embedding_transaction_states.append(task_session.in_transaction())
            if mutation_count == 0:
                async with AsyncSession(
                    engine,
                    expire_on_commit=False,
                ) as concurrent_session:
                    concurrent_draft = await concurrent_session.get(
                        WritingDraft,
                        draft_id,
                    )
                    assert concurrent_draft is not None
                    concurrent_draft.content = new_content
                    concurrent_draft.content_hash = hash_text(new_content)
                    await concurrent_session.commit()
                mutation_count += 1
            return [[0.1] * 768 for _text in texts]

        try:
            with patch(
                "infrastructure.llm.client.LLMClient",
                autospec=True,
            ) as client_cls:
                client_cls.return_value.generate_embedding = AsyncMock(
                    side_effect=_generate_embedding
                )
                outcome = await RetainingIndexingService().index_chapter_for_task(
                    task_session,
                    project_id,
                    1,
                )
                assert retained_drafts[0].content == new_content
        finally:
            await task_session.close()

        async with AsyncSession(engine, expire_on_commit=False) as verify_session:
            chunks = await RagChunkRepository().find_by_chapter(
                verify_session,
                project_id,
                1,
                content_mode="canonical",
            )
            state = await RagIndexStateService()._get(  # noqa: SLF001
                verify_session,
                novel_id=str(project_id),
                chapter_index=1,
                content_mode="canonical",
                lock=False,
            )

        assert mutation_count == 1
        assert len(retained_drafts) == 2
        assert embedding_transaction_states == [False, False]
        assert checkpoint_count == 3
        assert outcome.report.source_draft_id == str(draft_id)
        assert outcome.report.source_content_hash == hash_text(new_content)
        assert chunks
        assert all("新正文" in chunk.text for chunk in chunks)
        assert all("旧正文" not in chunk.text for chunk in chunks)
        assert state is not None
        assert state.indexed_source_id == draft_id
        assert state.indexed_hash == hash_text(new_content)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_task_index_uses_project_first_lock_order_and_two_checkpoints() -> None:
    from modules.rag.contracts import RagIndexReport
    from modules.rag.embedding_writer import EmbeddingWriteResult
    from modules.rag.indexing import (
        IndexingService,
        _ChapterIndexPlan,
        _EmbeddingTarget,
    )

    novel_id = uuid.uuid4()
    source_id = str(uuid.uuid4())
    source_hash = "a" * 64
    plan = _ChapterIndexPlan(
        chapter_index=26,
        content_mode="canonical",
        source_draft_id=source_id,
        source_content_hash=source_hash,
        items=[],
    )
    target = _EmbeddingTarget(chunk_index=0, text="预计算")
    report = RagIndexReport(
        chapter_index=26,
        source_draft_id=source_id,
        source_content_hash=source_hash,
    )
    events: list[str] = []
    db = AsyncMock()
    db.task_checkpoint_enabled = True
    db.expire_all = MagicMock(side_effect=lambda: events.append("expire"))

    async def _record_commit() -> None:
        events.append("commit")

    async def _record_guard(*_args, **_kwargs) -> object:
        events.append("project")
        return object()

    async def _record_prepare(*_args, **_kwargs) -> _ChapterIndexPlan:
        events.append("prepare")
        return plan

    async def _record_embed(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        events.append("embed")
        return [target], EmbeddingWriteResult()

    async def _record_claim(*_args, **_kwargs) -> str:
        events.append("claim")
        return "claimed"

    async def _record_preflight(*_args, **_kwargs) -> str:
        events.append("preflight")
        return "ready"

    async def _record_persist(*_args, **_kwargs) -> RagIndexReport:
        events.append("persist")
        return report

    async def _record_finish(*_args, **_kwargs) -> None:
        events.append("finish")

    db.commit = AsyncMock(side_effect=_record_commit)
    service = IndexingService(repo=MagicMock(spec=RagChunkRepository))
    with (
        patch(
            "modules.project.facade.require_active_project",
            autospec=True,
            side_effect=_record_guard,
        ),
        patch(
            "modules.rag.index_state.RagIndexStateService",
            autospec=True,
        ) as state_class,
        patch.object(
            IndexingService,
            "_prepare_chapter_index",
            autospec=True,
            side_effect=_record_prepare,
        ),
        patch.object(
            IndexingService,
            "_embed_plan",
            autospec=True,
            side_effect=_record_embed,
        ),
        patch.object(
            IndexingService,
            "_persist_preembedded_plan",
            autospec=True,
            side_effect=_record_persist,
        ),
    ):
        state_class.return_value.begin_prepared = AsyncMock(side_effect=_record_claim)
        state_class.return_value.preflight_prepared = AsyncMock(
            side_effect=_record_preflight
        )
        state_class.return_value.finish = AsyncMock(side_effect=_record_finish)

        outcome = await service.index_chapter_for_task(db, novel_id, 26)

    assert outcome.status == "indexed"
    assert events == [
        "project",
        "prepare",
        "preflight",
        "commit",
        "expire",
        "embed",
        "project",
        "claim",
        "persist",
        "finish",
        "commit",
    ]


@pytest.mark.asyncio
async def test_task_index_skips_embedding_when_prepared_source_is_fresh() -> None:
    from modules.rag.indexing import IndexingService, _ChapterIndexPlan

    novel_id = uuid.uuid4()
    plan = _ChapterIndexPlan(
        chapter_index=27,
        content_mode="canonical",
        source_draft_id=str(uuid.uuid4()),
        source_content_hash="b" * 64,
        items=[],
    )
    db = AsyncMock()
    db.task_checkpoint_enabled = True
    db.expire_all = MagicMock()
    service = IndexingService(repo=MagicMock(spec=RagChunkRepository))
    with (
        patch(
            "modules.project.facade.require_active_project",
            autospec=True,
        ),
        patch(
            "modules.rag.index_state.RagIndexStateService",
            autospec=True,
        ) as state_class,
        patch.object(
            IndexingService,
            "_prepare_chapter_index",
            autospec=True,
            return_value=plan,
        ),
        patch.object(
            IndexingService,
            "_embed_plan",
            autospec=True,
        ) as embed_plan,
    ):
        state_class.return_value.preflight_prepared = AsyncMock(return_value="fresh")

        outcome = await service.index_chapter_for_task(db, novel_id, 27)

    assert outcome.status == "coalesced"
    db.commit.assert_awaited_once_with()
    db.expire_all.assert_called_once_with()
    embed_plan.assert_not_awaited()
    state_class.return_value.begin_prepared.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_index_marks_failed_after_repeated_source_changes() -> None:
    from modules.rag.indexing import IndexingService, _ChapterIndexPlan

    novel_id = uuid.uuid4()
    plan = _ChapterIndexPlan(
        chapter_index=29,
        content_mode="canonical",
        source_draft_id=str(uuid.uuid4()),
        source_content_hash="c" * 64,
        items=[],
    )
    db = AsyncMock()
    db.task_checkpoint_enabled = True
    service = IndexingService(repo=MagicMock(spec=RagChunkRepository))
    with (
        patch(
            "modules.project.facade.require_active_project",
            autospec=True,
        ) as project_guard,
        patch(
            "modules.rag.index_state.RagIndexStateService",
            autospec=True,
        ) as state_class,
        patch.object(
            IndexingService,
            "_prepare_chapter_index",
            autospec=True,
            return_value=plan,
        ) as prepare,
        patch.object(
            IndexingService,
            "_embed_plan",
            autospec=True,
        ) as embed_plan,
    ):
        state = state_class.return_value
        state.preflight_prepared = AsyncMock(return_value="source_changed")
        state.fail = AsyncMock()

        with pytest.raises(RuntimeError, match="持续变化"):
            await service.index_chapter_for_task(db, novel_id, 29)

    assert prepare.await_count == 3
    assert state.preflight_prepared.await_count == 3
    embed_plan.assert_not_awaited()
    state.begin_prepared.assert_not_awaited()
    state.fail.assert_awaited_once_with(
        db,
        novel_id=str(novel_id),
        chapter_index=29,
        content_mode="canonical",
        error="source changed repeatedly during task indexing",
        expected_source_id=plan.source_draft_id,
        expected_source_hash=plan.source_content_hash,
        match_expected_source=True,
    )
    assert project_guard.await_count == 4
    assert db.rollback.await_count == 4
    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_embedding_writer_updates_loaded_chunks_without_refetching() -> None:
    """Embedding writer 已持有 chunk，不应每个 embedding 再按 id 查询。"""
    from modules.rag.embedding_writer import EmbeddingWriter

    class Repo:
        async def update_embedding(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("writer should update loaded chunks directly")

    class DB:
        def __init__(self) -> None:
            self.flush_count = 0

        async def flush(self) -> None:
            self.flush_count += 1

    class BatchLLM:
        async def generate_embedding(self, texts):  # type: ignore[no-untyped-def]
            assert texts == ["甲", "乙"]
            return [[0.1, 0.2], [0.3, 0.4]]

    class PerChunkLLM:
        async def generate_embedding(self, text):  # type: ignore[no-untyped-def]
            assert text == "丙"
            return [0.5, 0.6]

    db = DB()
    batch_chunks = [
        SimpleNamespace(id=uuid.uuid4(), text="甲"),
        SimpleNamespace(id=uuid.uuid4(), text="乙"),
    ]
    result = await EmbeddingWriter(Repo(), BatchLLM()).write_batch(  # type: ignore[arg-type]
        db,  # type: ignore[arg-type]
        batch_chunks,  # type: ignore[arg-type]
        warning_prefix="batch",
    )

    assert result.failed_count == 0
    assert [chunk.embedding for chunk in batch_chunks] == [[0.1, 0.2], [0.3, 0.4]]
    assert [chunk.embedding_status for chunk in batch_chunks] == [
        "succeeded",
        "succeeded",
    ]

    per_chunk = SimpleNamespace(id=uuid.uuid4(), text="丙")
    result = await EmbeddingWriter(Repo(), PerChunkLLM()).write_per_chunk(  # type: ignore[arg-type]
        db,  # type: ignore[arg-type]
        [per_chunk],  # type: ignore[list-item]
    )

    assert result.failed_count == 0
    assert per_chunk.embedding == [0.5, 0.6]
    assert per_chunk.embedding_status == "succeeded"
    assert db.flush_count == 2


@pytest.mark.asyncio
async def test_embedding_writer_falls_back_per_chunk_after_batch_failure() -> None:
    """批量 embedding 失败后应逐片挽救，且清理旧状态。"""
    from modules.rag.embedding_writer import EmbeddingWriter

    class Repo:
        pass

    class DB:
        def __init__(self) -> None:
            self.flush_count = 0

        async def flush(self) -> None:
            self.flush_count += 1

    class FallbackLLM:
        async def generate_embedding(self, value):  # type: ignore[no-untyped-def]
            if isinstance(value, list):
                raise RuntimeError("batch down")
            if value == "可恢复片段":
                return [0.1, 0.2]
            raise RuntimeError("single down")

    success_chunk = SimpleNamespace(
        id=uuid.uuid4(),
        text="可恢复片段",
        embedding=[0.9, 0.9],
        embedding_status="failed",
        embedding_error="old error",
        index_warnings=["old warning"],
    )
    failed_chunk = SimpleNamespace(
        id=uuid.uuid4(),
        text="仍失败片段",
        embedding=[0.8, 0.8],
        embedding_status="failed",
        embedding_error="old error",
        index_warnings=["old warning"],
    )

    result = await EmbeddingWriter(Repo(), FallbackLLM()).write_batch(  # type: ignore[arg-type]
        DB(),  # type: ignore[arg-type]
        [success_chunk, failed_chunk],  # type: ignore[list-item]
        warning_prefix="章节 embedding 失败",
    )

    assert result.failed_count == 1
    assert result.warnings[0] == "章节 embedding 失败: batch down"
    assert result.warnings[1] == (
        "本章 1/2 个片段 embedding 失败，检索将降级为关键词匹配"
    )
    assert success_chunk.embedding == [0.1, 0.2]
    assert success_chunk.embedding_status == "succeeded"
    assert success_chunk.embedding_error is None
    assert success_chunk.index_warnings == []
    assert failed_chunk.embedding is None
    assert failed_chunk.embedding_status == "failed"
    assert failed_chunk.embedding_error == "single down"
    assert failed_chunk.index_warnings == ["embedding 生成失败: single down"]


@pytest.mark.asyncio
async def test_embedding_writer_redacts_persisted_provider_diagnostics() -> None:
    from modules.rag.embedding_writer import EmbeddingWriter

    secret = "private-embedding-token-value"

    class FailingLLM:
        async def generate_embedding(self, _value):  # type: ignore[no-untyped-def]
            raise RuntimeError(
                f"Authorization: Bearer {secret} api_key={secret}"
            )

    chunk = SimpleNamespace(
        id=uuid.uuid4(),
        text="失败片段",
        embedding=[0.1],
        embedding_status="pending",
        embedding_error=None,
        index_warnings=[],
    )

    result = await EmbeddingWriter(SimpleNamespace(), FailingLLM()).embed_per_chunk(
        [chunk]
    )

    assert result.failed_count == 1
    assert secret not in chunk.embedding_error
    assert secret not in chunk.index_warnings[0]
    assert "[REDACTED]" in chunk.embedding_error


@pytest.mark.asyncio
async def test_embedding_writer_closes_only_the_client_it_owns() -> None:
    from modules.rag.embedding_writer import EmbeddingWriter

    repo = SimpleNamespace()
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
        owned_client = client_cls.return_value
        writer = EmbeddingWriter(repo)  # type: ignore[arg-type]
        await writer.close()
        await writer.close()

    owned_client.close.assert_awaited_once_with()

    injected_client = AsyncMock()
    writer = EmbeddingWriter(repo, injected_client)  # type: ignore[arg-type]
    await writer.close()
    injected_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_embedding_writer_closes_owned_client_on_body_error() -> None:
    from modules.rag.embedding_writer import EmbeddingWriter

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
        writer = EmbeddingWriter(SimpleNamespace())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="body failed"):
            async with writer:
                raise RuntimeError("body failed")

    client_cls.return_value.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_embedding_writer_closes_owned_client_when_cancelled() -> None:
    from modules.rag.embedding_writer import EmbeddingWriter

    entered = asyncio.Event()
    blocker = asyncio.Event()
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
        writer = EmbeddingWriter(SimpleNamespace())  # type: ignore[arg-type]

        async def _run() -> None:
            async with writer:
                entered.set()
                await blocker.wait()

        task = asyncio.create_task(_run())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    client_cls.return_value.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_collect_annotation_sources_uses_chapter_scene_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG indexing should not load all scenes for every chapter."""
    from modules.rag import source_collection

    novel_id = uuid.uuid4()
    calls: list[str] = []
    scene = {
        "id": "scene-1",
        "chapter_ids": ["2"],
        "scene_chunks": [{"chapter_index": 2, "start_offset": 0, "end_offset": 10}],
    }

    async def _fail_get_scenes_by_novel(*args, **kwargs):
        calls.append("all_scenes")
        raise AssertionError("chapter indexing should not load all scenes")

    async def _get_scenes_by_chapter(db, novel_id_arg: str, chapter_index: int):
        calls.append("chapter_scenes")
        assert novel_id_arg == str(novel_id)
        assert chapter_index == 2
        return [scene]

    async def _get_scene_spans_by_chapter(
        db,
        novel_id_arg: str,
        chapter_index: int,
        **_kwargs,
    ):
        calls.append("chapter_spans")
        assert novel_id_arg == str(novel_id)
        assert chapter_index == 2
        return []

    async def _load_terms(*args, **kwargs):
        return []

    async def _importance_map(*args, **kwargs):
        return {}

    import modules.outline.facade as outline_facade

    monkeypatch.setattr(
        outline_facade,
        "get_scenes_by_novel",
        _fail_get_scenes_by_novel,
    )
    monkeypatch.setattr(
        outline_facade,
        "get_scenes_by_chapter",
        _get_scenes_by_chapter,
        raising=False,
    )
    monkeypatch.setattr(
        outline_facade,
        "get_scene_spans_by_chapter",
        _get_scene_spans_by_chapter,
        raising=False,
    )
    monkeypatch.setattr(source_collection, "_load_project_terms", _load_terms)
    monkeypatch.setattr(
        source_collection,
        "_container_get",
        lambda name: _importance_map,
    )

    (
        scenes,
        spans,
        terms,
        importance,
    ) = await source_collection.collect_annotation_sources(None, novel_id, 2)  # type: ignore[arg-type]

    assert calls == ["chapter_scenes", "chapter_spans"]
    assert scenes == [scene]
    assert spans == []
    assert terms == []
    assert importance == {}


def test_build_chunk_create_prefers_scene_span_overlap() -> None:
    from modules.rag.chunk_annotation import build_chunk_create
    from modules.rag.chunking import ChineseNovelChunk, ChunkingService

    scene_id = uuid.uuid4()
    span_id = uuid.uuid4()
    fallback_scene_id = uuid.uuid4()
    cn_chunk = ChineseNovelChunk(
        chunk_index=0,
        text="命中 span 的正文片段",
        start_offset=30,
        end_offset=50,
        char_count=9,
    )

    data = build_chunk_create(
        cn_chunk,
        chapter_index=2,
        chunking=ChunkingService(),
        project_terms=[],
        entity_importance_map={},
        scenes_for_chapter=[
            {
                "id": str(fallback_scene_id),
                "scene_chunks": [{"chapter_index": 2, "start_pos": 0, "end_pos": 100}],
            }
        ],
        scene_spans_for_chapter=[
            SimpleNamespace(
                id=str(span_id),
                scene_id=str(scene_id),
                start_offset=20,
                end_offset=60,
                mapping_status="exact",
            )
        ],
    )

    assert data.scene_id == str(scene_id)
    assert data.scene_span_id == str(span_id)


@pytest.mark.asyncio
async def test_index_chapter_bulk_creates_chunks(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    """全量章节索引不应逐 chunk create/flush。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.indexing import IndexingService
    from modules.writing.models import WritingDraft

    class ReplaceOnlyRepo(RagChunkRepository):
        def __init__(self) -> None:
            super().__init__()
            self.replace_calls = 0

        async def create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("index_chapter should bulk-create chunks")

        async def create_many(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("index_chapter should use idempotent replace")

        async def replace_chapter_chunks(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.replace_calls += 1
            return await super().replace_chapter_chunks(*args, **kwargs)

    nid_uuid = uuid.UUID(hex=test_project_id)
    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content="用于批量创建 RAG chunk 的正文。" * 120,
            version_number=1,
        )
    )
    await db_session.flush()

    repo = ReplaceOnlyRepo()
    fake_embedding = [0.1] * 768

    async def _fake_batch_embedding(texts):
        assert isinstance(texts, list)
        return [fake_embedding for _ in texts]

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=_fake_batch_embedding)
        mock_client_cls.return_value = mock_client

        report = await IndexingService(repo=repo).index_chapter_with_report(
            db_session,
            nid_uuid,
            1,
            content_mode="working",
        )

    assert repo.replace_calls == 1
    assert report.chunks_created > 0
    assert mock_client.generate_embedding.call_count == 1
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(chunks) == report.chunks_created
    assert [str(chunk.id) for chunk in chunks] == report.chunks_created_ids


@pytest.mark.asyncio
async def test_manual_upsert_loads_existing_rows_in_one_query() -> None:
    repo = RagChunkRepository()
    novel_id = uuid.uuid4()
    first = repo._chunk_row(  # noqa: SLF001 - focused repository regression
        novel_id,
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=0,
            text="updated first",
            index_version="cn-novel-v1",
        ),
    )
    second = repo._chunk_row(  # noqa: SLF001 - focused repository regression
        novel_id,
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=1,
            text="new second",
            index_version="cn-novel-v1",
        ),
    )
    existing = SimpleNamespace(id=uuid.uuid4(), **{**first, "text": "old first"})
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = [existing]
    db = AsyncMock()
    db.execute.return_value = scalar_result
    db.add = MagicMock()

    await repo._manual_upsert_chapter_chunk_rows(  # noqa: SLF001
        db,
        [first, second],
    )

    assert db.execute.await_count == 1
    assert existing.text == "updated first"
    added = db.add.call_args.args[0]
    assert added.chunk_index == 1
    assert added.text == "new second"


@pytest.mark.asyncio
async def test_manual_upsert_duplicate_input_key_keeps_last_row(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    repo = RagChunkRepository()
    novel_id = uuid.UUID(test_project_id)
    items = [
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=0,
            text="first duplicate",
            index_version="cn-novel-v1",
        ),
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=0,
            text="last duplicate",
            index_version="cn-novel-v1",
        ),
    ]

    chunks = await repo.replace_chapter_chunks(
        db_session,
        novel_id,
        source_type="chapter_text",
        chapter_index=1,
        content_mode="working",
        items=items,
    )

    assert len(chunks) == 1
    assert chunks[0].text == "last duplicate"


@pytest.mark.asyncio
async def test_replace_chapter_chunks_is_idempotent_for_same_chapter(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    nid = uuid.UUID(hex=test_project_id)
    first = [
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=0,
            text="旧 chunk 0",
            index_version="cn-novel-v1",
        ),
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=1,
            text="旧 chunk 1",
            index_version="cn-novel-v1",
        ),
    ]
    second = [
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=0,
            text="新 chunk 0",
            index_version="cn-novel-v1",
        )
    ]

    await repo.replace_chapter_chunks(
        db_session,
        nid,
        source_type="chapter_text",
        chapter_index=1,
        items=first,
    )
    await repo.replace_chapter_chunks(
        db_session,
        nid,
        source_type="chapter_text",
        chapter_index=1,
        items=second,
    )

    chunks = await repo.find_by_chapter(
        db_session,
        nid,
        1,
        source_type="chapter_text",
        content_mode="working",
    )
    assert [(chunk.chunk_index, chunk.text) for chunk in chunks] == [(0, "新 chunk 0")]


@pytest.mark.asyncio
async def test_delete_by_chapter_removes_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: delete_by_chapter 应删除指定章节的所有 chunk"""
    nid = uuid.UUID(hex=test_project_id)

    # 先创建 2 个第 1 章 chunk + 1 个第 2 章 chunk
    await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="第一章内容。",
        ),
    )
    await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="第一章更多内容。",
        ),
    )
    await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=2,
            text="第二章内容。",
        ),
    )

    # 执行删除第 1 章
    deleted = await repo.delete_by_chapter(db_session, nid, "chapter_text", 1)
    assert deleted == 2, f"应删除 2 个 chunk，实际删除了 {deleted}"

    # 验证第 1 章的 chunk 已删除
    remaining = await repo.find_by_chapter(db_session, nid, 1)
    assert len(remaining) == 0, "第 1 章的 chunk 应全部删除"

    # 第 2 章的 chunk 应保留
    ch2 = await repo.find_by_chapter(db_session, nid, 2)
    assert len(ch2) == 1, "第 2 章的 chunk 应保留 1 个"


@pytest.mark.asyncio
async def test_deleted_rag_data_can_be_fully_rebuilt_from_writing(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.writing.facade import create_draft_only

    content = "原文是唯一事实源，派生索引可删除重建。" * 20
    draft = await create_draft_only(
        db_session,
        test_project_id,
        6,
        content=content,
    )
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
        client = AsyncMock()
        client.generate_embedding = AsyncMock(side_effect=Exception("offline"))
        client_cls.return_value = client
        first = await index_chapter_with_report(
            db_session,
            test_project_id,
            6,
            content_mode="working",
        )

    assert first.chunks_created > 0
    await repo.delete_by_novel(db_session, uuid.UUID(test_project_id))
    assert (
        await repo.find_by_chapter(
            db_session,
            uuid.UUID(test_project_id),
            6,
            content_mode="working",
        )
        == []
    )

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
        client = AsyncMock()
        client.generate_embedding = AsyncMock(side_effect=Exception("offline"))
        client_cls.return_value = client
        rebuilt = await index_chapter_with_report(
            db_session,
            test_project_id,
            6,
            content_mode="working",
        )

    chunks = await repo.find_by_chapter(
        db_session,
        uuid.UUID(test_project_id),
        6,
        content_mode="working",
    )
    assert len(chunks) == rebuilt.chunks_created == first.chunks_created
    assert all(chunk.source_id == uuid.UUID(draft.id or "") for chunk in chunks)
    assert all(chunk.source_content_hash == draft.content_hash for chunk in chunks)


@pytest.mark.asyncio
async def test_delete_by_chapter_no_op_when_none(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: 删除不存在的章节应返回 0"""
    nid = uuid.UUID(hex=test_project_id)
    deleted = await repo.delete_by_chapter(db_session, nid, "chapter_text", 99)
    assert deleted == 0


@pytest.mark.asyncio
async def test_index_chapter_creates_chunks_with_character_ids(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
    test_character_id: str,  # noqa: F811
):
    """RED: index_chapter 应创建带角色标记的 chunk"""
    import uuid as _uuid

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 先创建一个草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角从沉睡中醒来。测试主角环顾四周。",
        version_number=1,
    )
    db_session.add(draft)
    await db_session.flush()

    # 执行索引
    chunk_count = await index_chapter(
        db_session,
        test_project_id,
        1,
        content_mode="working",
    )
    assert chunk_count > 0, f"应创建至少 1 个 chunk，实际创建 {chunk_count}"

    # 验证 chunk 包含 character_ids
    chunks = await repo.find_by_chapter(
        db_session,
        nid_uuid,
        1,
        content_mode="working",
    )
    assert len(chunks) > 0, "应能找到第 1 章的 chunk"

    # CoreEntity 角色的 ID 按 entity_type 归入 character_ids。
    all_character_ids = []
    for c in chunks:
        all_character_ids.extend(c.character_ids or [])
    assert test_character_id in all_character_ids, (
        f"chunk 应包含角色 ID {test_character_id}，实际包含: {all_character_ids}"
    )


@pytest.mark.asyncio
async def test_index_chapter_replaces_old_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
    test_character_id: str,  # noqa: F811
):
    """RED: 重新索引应替换旧 chunk 而非追加"""
    import uuid as _uuid

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 先创建旧 chunk
    await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="旧内容。",
            content_mode="working",
        ),
    )

    # 创建草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角做了某事。",
        version_number=2,
    )
    db_session.add(draft)
    await db_session.flush()

    # 索引新内容
    chunk_count = await index_chapter(
        db_session,
        test_project_id,
        1,
        content_mode="working",
    )
    assert chunk_count > 0

    # 验证只有新 chunk，旧 chunk 被替换
    chunks = await repo.find_by_chapter(
        db_session,
        nid_uuid,
        1,
        content_mode="working",
    )
    for c in chunks:
        assert "旧内容" not in c.text, "旧 chunk 应已被删除"


@pytest.mark.asyncio
async def test_index_chapter_with_embeddings(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: index_chapter 应生成并存储 embedding"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    # 创建草稿
    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试主角的欲望是找到真相。",
        version_number=1,
    )
    db_session.add(draft)
    await db_session.flush()

    # mock embedding provider（使用 768 维匹配 Vector(768) 列定义）
    fake_embedding = [0.1] * 768

    async def _fake_batch_embedding(texts):
        assert isinstance(texts, list), "应接收文本列表（批量 embedding）"
        return [fake_embedding for _ in texts]

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=_fake_batch_embedding)
        mock_client_cls.return_value = mock_client

        chunk_count = await index_chapter(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert chunk_count > 0, "应创建 chunks"

    # 验证 chunk 有 embedding
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    for c in chunks:
        assert c.embedding is not None, f"chunk {c.id} 应有 embedding"

    assert mock_client.generate_embedding.call_count == 1
    input_texts = mock_client.generate_embedding.call_args.args[0]
    assert isinstance(input_texts, list)
    assert len(input_texts) == len(chunks)


@pytest.mark.asyncio
async def test_incremental_index_replaces_chunks_with_current_version_binding(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """兼容增量入口必须用当前 draft/hash 全量替换旧 chunk。"""
    from unittest.mock import AsyncMock, patch

    from modules.rag.indexing import IndexingService
    from modules.writing.facade import create_draft_only

    nid_uuid = uuid.UUID(hex=test_project_id)
    old_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="working",
            chapter_index=1,
            chunk_index=0,
            start_offset=0,
            end_offset=4,
            char_count=4,
            text="完全相同",
            embedding_status="succeeded",
        ),
    )
    await db_session.flush()

    draft = await create_draft_only(
        db_session,
        test_project_id,
        1,
        content="完全相同",
    )

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("offline"))
        mock_client_cls.return_value = mock_client
        report = await IndexingService(repo=repo).index_chapter_incremental(
            db_session,
            nid_uuid,
            1,
            old_content="完全相同",
            new_content="完全相同",
            content_mode="working",
        )

    chunks = await repo.find_by_chapter(
        db_session,
        nid_uuid,
        1,
        content_mode="working",
    )
    assert old_chunk.id not in {chunk.id for chunk in chunks}
    assert chunks
    assert all(str(chunk.source_id) == draft.id for chunk in chunks)
    assert all(chunk.source_content_hash == draft.content_hash for chunk in chunks)
    assert "全量替换" in report.warnings[0]


@pytest.mark.asyncio
async def test_incremental_index_delegates_to_version_bound_full_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """兼容入口不再复用旧版本 chunk。"""
    from unittest.mock import AsyncMock

    from modules.rag.contracts import RagIndexReport
    from modules.rag.indexing import IndexingService

    novel_id = uuid.uuid4()
    service = IndexingService()
    full_report = RagIndexReport(
        chapter_index=1,
        content_mode="working",
        source_draft_id=str(uuid.uuid4()),
        source_content_hash="a" * 64,
        chunks_created=2,
    )
    full_index = AsyncMock(return_value=full_report)
    monkeypatch.setattr(service, "index_chapter_with_report", full_index)

    report = await service.index_chapter_incremental(
        SimpleNamespace(),  # type: ignore[arg-type]
        novel_id,
        1,
        old_content="aaaaabbbbb",
        new_content="aaaaaccccc",
        content_mode="working",
    )

    full_index.assert_awaited_once()
    assert report.source_draft_id == full_report.source_draft_id
    assert "全量替换" in report.warnings[0]


@pytest.mark.asyncio
async def test_index_chapter_uses_cn_novel_index_and_project_terms(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """索引应记录显式位置字段，并用人物/世界/剧情线词典标注 chunk。"""
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.world.models import Character, CoreEntity
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    char_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    db_session.add(
        CoreEntity(
            id=char_id,
            novel_id=nid_uuid,
            entity_type="character",
            name="克莱恩·莫雷蒂",
            content_json={"aliases": [{"alias": "周明瑞", "type": "original_name"}]},
            status="canonical",
        )
    )
    db_session.add(
        Character(
            entity_id=char_id,
            novel_id=nid_uuid,
            name="克莱恩·莫雷蒂",
            aliases=[{"alias": "周明瑞", "type": "original_name"}],
            role="主角",
            status="canonical",
        )
    )
    db_session.add(
        CoreEntity(
            id=entity_id,
            novel_id=nid_uuid,
            entity_type="secret",
            name="灰雾",
            summary="神秘空间",
            status="canonical",
        )
    )
    db_session.add(
        WritingDraft(
            id=uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content=(
                "周明瑞从梦中醒来，脑海里残留着穿越谜团。"
                "他看见神秘空间一样的灰雾在眼前翻涌。" * 20
            ),
            version_number=1,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down")
        )
        mock_client_cls.return_value = mock_client

        report = await index_chapter_with_report(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert report.chunks_created > 0
    assert report.embedding_failed_count == report.chunks_created
    assert report.warnings

    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert chunks
    assert all(c.index_version == "cn-novel-v1" for c in chunks)
    assert all(c.chunk_index is not None for c in chunks)
    assert all(c.start_offset is not None and c.end_offset is not None for c in chunks)
    assert all(c.char_count == len(c.text) for c in chunks)
    # CoreEntity 角色按 entity_type 进入 character_ids。
    assert any(str(char_id) in (c.character_ids or []) for c in chunks)
    assert any(str(entity_id) in (c.entity_ids or []) for c in chunks)
    assert all(c.embedding_status == "failed" for c in chunks)


@pytest.mark.asyncio
async def test_index_chapter_embedding_empty_when_no_llm(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: LLM 不可用时不应阻塞索引"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    draft = WritingDraft(
        id=_uuid.uuid4(),
        novel_id=nid_uuid,
        chapter_index=1,
        title="第一章",
        content="测试内容。",
        version_number=1,
    )
    db_session.add(draft)
    await db_session.flush()

    with patch(
        "infrastructure.llm.client.LLMClient",
        autospec=True,
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("API 不可用"))
        mock_client_cls.return_value = mock_client

        # 不应抛出异常
        chunk_count = await index_chapter(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert chunk_count > 0, "即使 embedding 失败也应创建 chunks"
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    # embedding 应为 None（不阻塞索引）
    has_any_embedding = any(c.embedding is not None for c in chunks)
    assert not has_any_embedding, "embedding 失败时所有 chunk 的 embedding 应为 None"


@pytest.mark.asyncio
async def test_reindex_novel_task_rebuilds_all_chapters_with_report(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
):
    """全量重建任务应逐章索引并返回可展示的诊断结果。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_reindex_novel
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    for idx in (1, 2):
        db_session.add(
            WritingDraft(
                id=uuid.uuid4(),
                novel_id=nid_uuid,
                chapter_index=idx,
                title=f"第{idx}章",
                content=f"第{idx}章正文。周明瑞醒来并观察这个世界。" * 8,
                version_number=1,
            )
        )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex_novel",
        status="running",
        meta={"novel_id": test_project_id, "force": True, "content_mode": "working"},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    # Direct handler execution emulates TaskWorker's fenced session.
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down")
        )
        mock_client_cls.return_value = mock_client

        result = await handle_rag_reindex_novel(db_session, task)

    assert result["total_chapters"] == 2
    assert result["chunks_created"] >= 2
    assert result["embedding_failed_count"] == result["chunks_created"]
    assert result["warnings"]
    assert len(result["chapters"]) == 2
    assert task.progress == 1.0


@pytest.mark.asyncio
async def test_index_chapter_skips_no_draft(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: 无草稿的章节应返回 0"""
    from modules.rag.facade import index_chapter

    count = await index_chapter(
        db_session,
        test_project_id,
        99,
        content_mode="working",
    )
    assert count == 0, "无草稿章节应返回 0"


@pytest.mark.asyncio
async def test_index_chapter_replaces_stale_chunks_on_update(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: 更新章节正文后重新索引，旧 chunk 不应残留，新 chunk 应出现"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content="旧正文片段。旧正文片段。旧内容应被清除。" * 6,
            version_number=1,
        )
    )
    await db_session.flush()

    fake_embedding = [0.1] * 768
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=fake_embedding)
        mock_client_cls.return_value = mock_client
        result = await index_chapter_with_report(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert result.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert any("旧正文片段" in c.text for c in chunks)
    assert len(chunks) == result.chunks_created, "首次索引后 chunk 总数应与报告一致"

    # 更新章节：创建新版本草稿
    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章（修订）",
            content="新正文片段。新正文片段。新内容应保留。" * 6,
            version_number=2,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=fake_embedding)
        mock_client_cls.return_value = mock_client
        result = await index_chapter_with_report(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert result.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert all("旧正文片段" not in c.text for c in chunks)
    assert any("新正文片段" in c.text for c in chunks)
    assert len(chunks) == result.chunks_created, (
        "重新索引后旧 chunk 应被删除，总数应与报告一致"
    )


@pytest.mark.asyncio
async def test_index_chapter_with_report_marks_failed_embeddings(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """RED: embedding 失败时 chunk 状态应为 failed 且报告携带 warnings"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content="测试正文。用于验证 embedding 失败降级。" * 8,
            version_number=1,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(
            side_effect=Exception("embedding down"),
        )
        mock_client_cls.return_value = mock_client
        result = await index_chapter_with_report(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert any(c.embedding_status == "failed" for c in chunks)
    assert result.warnings


@pytest.mark.asyncio
async def test_index_chapter_annotates_scene_id(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """索引章节时应按 scene_chunks 区间把 chunk 标注上 scene_id。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    scene_repo = SceneRepository()

    content = "周明瑞从梦中醒来，脑海里残留着穿越谜团。" * 30
    scene = await scene_repo.create(
        db_session,
        nid_uuid,
        SceneCreate(
            scene_index=0,
            title="开场",
            chapter_ids=["1"],
            scene_chunks=[
                {
                    "chapter_id": "1",
                    "chapter_index": 1,
                    "start_pos": 0,
                    "end_pos": len(content),
                }
            ],
            status="draft",
        ),
    )

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content=content,
            version_number=1,
        )
    )
    await db_session.flush()

    embed_exc = Exception("embedding down")
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        report = await index_chapter_with_report(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert report.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert chunks
    assert any(str(c.scene_id) == str(scene.id) for c in chunks), (
        f"至少有一个 chunk 应被标注 scene_id {scene.id}"
    )
    assert any(c.scene_span_id is not None for c in chunks), (
        "至少有一个 chunk 应被标注 scene_span_id"
    )


@pytest.mark.asyncio
async def test_index_chapter_does_not_attribute_chapter_only_scene_span(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """只有章节/段落映射时，不得自动将 chunk 归因到 Scene。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from modules.outline.repositories import SceneRepository
    from modules.outline.schemas import SceneCreate
    from modules.rag.facade import index_chapter_with_report
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    scene_repo = SceneRepository()

    content = "克莱恩在廷根整理线索，确认占卜与梦境的关系。" * 30
    await scene_repo.create(
        db_session,
        nid_uuid,
        SceneCreate(
            scene_index=0,
            title="段落映射场景",
            chapter_ids=["1"],
            scene_chunks=[
                {
                    "chapter_index": 1,
                    "start_paragraph": 0,
                    "end_paragraph": 0,
                }
            ],
            status="draft",
        ),
    )

    db_session.add(
        WritingDraft(
            id=_uuid.uuid4(),
            novel_id=nid_uuid,
            chapter_index=1,
            title="第一章",
            content=content,
            version_number=1,
        )
    )
    await db_session.flush()

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("offline"))
        mock_client_cls.return_value = mock_client

        report = await index_chapter_with_report(
            db_session,
            test_project_id,
            1,
            content_mode="working",
        )

    assert report.chunks_created > 0
    chunks = await repo.find_by_chapter(db_session, nid_uuid, 1)
    assert chunks
    assert all(c.scene_id is None and c.scene_span_id is None for c in chunks)


@pytest.mark.asyncio
async def test_rebuild_novel_with_chapter_range(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
):
    """rag_reindex_novel 任务应只重建指定章节范围。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_reindex_novel
    from modules.writing.models import WritingDraft

    nid_uuid = uuid.UUID(hex=test_project_id)
    for idx in (1, 2, 3):
        db_session.add(
            WritingDraft(
                id=_uuid.uuid4(),
                novel_id=nid_uuid,
                chapter_index=idx,
                title=f"第{idx}章",
                content=f"第{idx}章正文。周明瑞醒来并观察这个世界。" * 8,
                version_number=1,
            )
        )

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex_novel",
        status="running",
        meta={
            "novel_id": test_project_id,
            "start_chapter": 2,
            "end_chapter": 2,
            "content_mode": "working",
        },
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    # Direct handler execution emulates TaskWorker's fenced session.
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    embed_exc = Exception("embedding down")
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_reindex_novel(db_session, task)

    assert result["total_chapters"] == 1
    assert result["chunks_created"] >= 1
    chapter_indices = [c["chapter_index"] for c in result["chapters"]]
    assert chapter_indices == [2]
