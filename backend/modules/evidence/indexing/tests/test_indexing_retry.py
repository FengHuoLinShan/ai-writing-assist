"""
TB1: RAG 章节索引 — 测试
"""


from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.repositories import RagChunkRepository
from modules.evidence.indexing.schemas import RagChunkCreate


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
async def test_retry_embeddings_task_rejects_an_ordinary_session(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.evidence.indexing.indexing import IndexingService

    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await IndexingService(repo=repo).retry_embeddings_for_task(
            db_session,
            test_project_id,
        )


@pytest.mark.asyncio
async def test_retry_embeddings_normal_seam_keeps_caller_transaction(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    """The existing API/service seam must not take transaction ownership."""
    from modules.evidence.indexing.indexing import IndexingService

    await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="普通调用方仍拥有事务",
            embedding_status="failed",
        ),
    )
    transaction_states: list[bool] = []

    async def _generate(texts):  # type: ignore[no-untyped-def]
        transaction_states.append(db_session.in_transaction())
        return [[0.1] * 768 for _text in texts]

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
        client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
        result = await IndexingService(repo=repo).retry_embeddings(
            db_session,
            uuid.UUID(test_project_id),
        )

    assert result["succeeded"] == 1
    assert transaction_states == [True]
    assert db_session.in_transaction()


@pytest.mark.asyncio
async def test_retry_embeddings_task_checkpoints_around_transaction_free_embedding(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.evidence.indexing.indexing import IndexingService

    await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="provider 等待时不应持有事务",
            embedding_status="failed",
        ),
    )
    checkpoint_count = 0
    transaction_states: list[bool] = []

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return True

    task_session = _new_task_handler_session(db_session, _checkpoint)

    async def _generate(texts):  # type: ignore[no-untyped-def]
        transaction_states.append(task_session.in_transaction())
        return [[0.1] * 768 for _text in texts]

    try:
        with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
            client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
            result = await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    assert result == {
        "total": 1,
        "succeeded": 1,
        "failed": 0,
        "remaining_retryable_count": 0,
        "warnings": [],
    }
    assert transaction_states == [False]
    assert checkpoint_count == 3


@pytest.mark.asyncio
async def test_retry_embeddings_task_replans_stale_text_without_double_counting(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    """A stale successful vector is skipped; the new text is counted only once."""
    from modules.evidence.indexing.indexing import IndexingService

    chunk = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            source_id=str(uuid.uuid4()),
            source_content_hash="a" * 64,
            content_mode="working",
            chapter_index=2,
            chunk_index=0,
            index_version="retry-v1",
            text="旧版本文本",
            embedding_status="failed",
        ),
    )
    first_embedding = [0.1] * 768
    second_embedding = [0.2] * 768
    provider_calls = 0
    task_session = _new_task_handler_session(db_session)

    async def _generate(texts):  # type: ignore[no-untyped-def]
        nonlocal provider_calls
        provider_calls += 1
        assert not task_session.in_transaction()
        if provider_calls == 1:
            chunk.text = "并发更新后的新文本"
            chunk.source_content_hash = "b" * 64
            await db_session.flush()
            return [first_embedding for _text in texts]
        assert texts == ["并发更新后的新文本"]
        return [second_embedding for _text in texts]

    try:
        with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
            client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
            result = await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    await db_session.refresh(chunk)
    assert provider_calls == 2
    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert chunk.text == "并发更新后的新文本"
    assert chunk.source_content_hash == "b" * 64
    assert list(chunk.embedding) == second_embedding


@pytest.mark.asyncio
async def test_retry_embeddings_task_does_not_overwrite_concurrent_success(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.evidence.indexing.indexing import IndexingService

    chunk = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=3,
            text="同一片段由另一个任务先完成",
            embedding_status="failed",
        ),
    )
    concurrent_embedding = [0.8] * 768
    stale_embedding = [0.1] * 768
    task_session = _new_task_handler_session(db_session)

    async def _generate(texts):  # type: ignore[no-untyped-def]
        assert not task_session.in_transaction()
        chunk.embedding = concurrent_embedding  # type: ignore[assignment]
        chunk.embedding_status = "succeeded"
        chunk.embedding_error = None
        chunk.index_warnings = ["并发任务已完成"]
        await db_session.flush()
        return [stale_embedding for _text in texts]

    try:
        with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
            client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
            result = await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    await db_session.refresh(chunk)
    assert result["succeeded"] == 1
    assert list(chunk.embedding) == concurrent_embedding
    assert chunk.index_warnings == ["并发任务已完成"]


@pytest.mark.asyncio
async def test_retry_embeddings_task_counts_deleted_chunk_as_resolved_once(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    """A chunk deleted during provider wait is resolved without stale write-back."""
    from modules.evidence.indexing.indexing import IndexingService

    chunk = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=3,
            text="provider 返回前被删除",
            embedding_status="failed",
        ),
    )
    task_session = _new_task_handler_session(db_session)

    async def _generate(texts):  # type: ignore[no-untyped-def]
        assert not task_session.in_transaction()
        await db_session.delete(chunk)
        await db_session.flush()
        return [[0.1] * 768 for _text in texts]

    try:
        with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
            client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
            result = await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    assert result == {
        "total": 1,
        "succeeded": 1,
        "failed": 0,
        "remaining_retryable_count": 0,
        "warnings": [],
    }
    assert await repo.get(db_session, chunk.id) is None


@pytest.mark.asyncio
async def test_retry_embeddings_task_deduplicates_same_id_revectorization(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
) -> None:
    """One chunk re-entering retry state is processed again but counted once."""
    from sqlalchemy import update

    from modules.evidence.indexing.indexing import IndexingService
    from modules.evidence.indexing.models import RagChunk

    chunk_id: uuid.UUID | None = None

    class RevectorizingRepo(RagChunkRepository):
        candidate_reads = 0

        async def find_embedding_retry_candidate_values(self, db, novel_id, **kwargs):  # type: ignore[no-untyped-def]
            self.candidate_reads += 1
            if self.candidate_reads == 2:
                assert chunk_id is not None
                await db.execute(
                    update(RagChunk)
                    .where(
                        RagChunk.id == chunk_id,
                        RagChunk.novel_id == novel_id,
                    )
                    .values(
                        embedding=None,
                        embedding_status="pending_vectorization",
                    )
                )
                await db.flush()
            return await super().find_embedding_retry_candidate_values(
                db,
                novel_id,
                **kwargs,
            )

    repo = RevectorizingRepo()
    chunk = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=3,
            text="同一 ID 再次进入向量化",
            embedding_status="failed",
        ),
    )
    chunk_id = chunk.id
    task_session = _new_task_handler_session(db_session)
    provider_calls = 0

    async def _generate(texts):  # type: ignore[no-untyped-def]
        nonlocal provider_calls
        provider_calls += 1
        return [[0.1 * provider_calls] * 768 for _text in texts]

    try:
        with patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls:
            client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
            result = await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    await db_session.refresh(chunk)
    assert provider_calls == 2
    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert list(chunk.embedding) == [0.2] * 768


@pytest.mark.asyncio
async def test_retry_embeddings_task_rechecks_project_after_provider_wait(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    from datetime import UTC, datetime

    from core.errors import NotFoundError
    from modules.evidence.indexing.indexing import IndexingService
    from modules.project.models import Project

    chunk = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=4,
            text="项目回收后不得写回",
            embedding_status="failed",
        ),
    )
    project = await db_session.get(Project, uuid.UUID(test_project_id))
    assert project is not None
    task_session = _new_task_handler_session(db_session)

    async def _generate(texts):  # type: ignore[no-untyped-def]
        assert not task_session.in_transaction()
        project.deleted_at = datetime.now(UTC)
        await db_session.flush()
        return [[0.1] * 768 for _text in texts]

    try:
        with (
            patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls,
            pytest.raises(NotFoundError),
        ):
            client_cls.return_value.generate_embedding = AsyncMock(side_effect=_generate)
            await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    await db_session.refresh(chunk)
    assert chunk.embedding_status == "failed"
    assert chunk.embedding is None


@pytest.mark.asyncio
async def test_retry_embeddings_task_lease_loss_rolls_back_batch_write(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
) -> None:
    from modules.evidence.indexing.indexing import IndexingService

    chunk = await repo.create(
        db_session,
        uuid.UUID(test_project_id),
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=5,
            text="lease 丢失后不得提交",
            embedding_status="failed",
        ),
    )
    checkpoint_count = 0

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return checkpoint_count == 1

    task_session = _new_task_handler_session(db_session, _checkpoint)
    mock_client = None
    try:
        with (
            patch("infrastructure.llm.client.LLMClient", autospec=True) as client_cls,
            pytest.raises(asyncio.CancelledError),
        ):
            mock_client = client_cls.return_value
            mock_client.generate_embedding = AsyncMock(return_value=[[0.1] * 768])
            await IndexingService(repo=repo).retry_embeddings_for_task(
                task_session,
                test_project_id,
            )
    finally:
        await task_session.close()

    await db_session.refresh(chunk)
    assert checkpoint_count == 2
    assert chunk.embedding_status == "failed"
    assert chunk.embedding is None
    assert mock_client is not None
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_embeddings_task_updates_failed_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """rag_retry_embeddings 只修复目标项目内的失败向量。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.indexing.tasks import handle_rag_retry_embeddings
    from modules.project.models import Project

    nid_uuid = uuid.UUID(hex=test_project_id)
    retry_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="需要重试的片段",
            embedding_status="failed",
            embedding_error="old error",
        ),
    )
    skipped_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=2,
            text="范围外失败片段",
            embedding_status="failed",
        ),
    )
    other_novel_id = uuid.uuid4()
    db_session.add(Project(id=other_novel_id, title="其他项目"))
    await db_session.flush()
    other_chunk = await repo.create(
        db_session,
        other_novel_id,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="其他项目的失败片段",
            embedding_status="failed",
        ),
    )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id, "start_chapter": 1, "end_chapter": 1},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    fake_embedding = [0.1] * 768
    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(return_value=[fake_embedding])
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
    assert task.progress == 1.0
    refreshed = await repo.get(db_session, retry_chunk.id)
    skipped = await repo.get(db_session, skipped_chunk.id)
    other = await repo.get(db_session, other_chunk.id)
    assert refreshed.embedding_status == "succeeded"
    assert refreshed.embedding is not None
    assert refreshed.embedding_error is None
    assert skipped.embedding_status == "failed"
    assert other.embedding_status == "failed"
    assert other.embedding is None


@pytest.mark.asyncio
async def test_retry_embeddings_task_counts_partial_batch_fallback(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """批量路径降级后部分成功时，应统计成功数并清理失败 stale embedding。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.indexing.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    success_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            chunk_index=0,
            text="可恢复片段",
            embedding_status="failed",
            embedding_error="old error",
            index_warnings=["old warning"],
        ),
    )
    failed_chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            chunk_index=1,
            text="仍失败片段",
            embedding_status="failed",
            embedding_error="old error",
            index_warnings=["old warning"],
        ),
    )
    success_chunk.embedding = [0.9] * 768  # type: ignore[assignment]
    failed_chunk.embedding = [0.8] * 768  # type: ignore[assignment]
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    fake_embedding = [0.1] * 768

    async def _fake_embedding(value):
        if isinstance(value, list):
            raise RuntimeError("batch down")
        if value == "可恢复片段":
            return fake_embedding
        raise RuntimeError("single down")

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=_fake_embedding)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    refreshed_success = await repo.get(db_session, success_chunk.id)
    refreshed_failed = await repo.get(db_session, failed_chunk.id)
    assert result["total"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["remaining_retryable_count"] == 1
    assert task.progress == 0.5
    assert result["warnings"][0] == "embedding 重试失败: batch down"
    assert result["warnings"][1] == (
        "本章 1/2 个片段 embedding 失败，检索将降级为关键词匹配"
    )
    assert refreshed_success.embedding_status == "succeeded"
    assert refreshed_success.embedding_error is None
    assert refreshed_success.index_warnings == []
    assert refreshed_failed.embedding is None
    assert refreshed_failed.embedding_status == "failed"
    assert refreshed_failed.embedding_error == "single down"


@pytest.mark.asyncio
async def test_retry_embeddings_task_keeps_batch_warning_after_full_fallback_success(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """批量路径降级后逐片全成功时，也不能丢失 batch warning。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.indexing.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    for index, text in enumerate(["可恢复片段 A", "可恢复片段 B"]):
        await repo.create(
            db_session,
            nid_uuid,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                chunk_index=index,
                text=text,
                embedding_status="failed",
                embedding_error="old error",
                index_warnings=["old warning"],
            ),
        )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    fake_embedding = [0.1] * 768

    async def _fake_embedding(value):
        if isinstance(value, list):
            raise RuntimeError("batch down")
        return fake_embedding

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=_fake_embedding)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    remaining = await repo.count_retryable_embeddings(
        db_session,
        nid_uuid,
        statuses=["failed", "pending_vectorization"],
    )
    assert result["total"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["remaining_retryable_count"] == 0
    assert result["warnings"] == ["embedding 重试失败: batch down"]
    assert task.progress == 1.0
    assert remaining == 0


@pytest.mark.asyncio
async def test_retry_embeddings_task_processes_more_than_one_batch(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """失败向量超过单批上限时，任务应循环直到无剩余候选。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.indexing.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    for index in range(501):
        await repo.create(
            db_session,
            nid_uuid,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                chunk_index=index,
                text=f"失败片段 {index}",
                embedding_status="failed",
            ),
        )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    fake_embedding = [0.1] * 768

    async def _fake_embedding(texts):
        return [fake_embedding for _ in texts]

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=_fake_embedding)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    remaining = await repo.count_retryable_embeddings(
        db_session,
        nid_uuid,
        statuses=["failed", "pending_vectorization"],
    )
    assert result["total"] == 501
    assert result["succeeded"] == 501
    assert result["failed"] == 0
    assert result["remaining_retryable_count"] == 0
    assert remaining == 0
    assert mock_client.generate_embedding.call_count == 2


@pytest.mark.asyncio
async def test_retry_embeddings_task_marks_batch_failure(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """批量 embedding 失败时保持 failed 并写入截断错误。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.indexing.tasks import handle_rag_retry_embeddings

    nid_uuid = uuid.UUID(hex=test_project_id)
    chunk = await repo.create(
        db_session,
        nid_uuid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="失败片段",
            embedding_status="failed",
        ),
    )
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    with patch("infrastructure.llm.client.LLMClient", autospec=True) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=Exception("x" * 1200))
        mock_client_cls.return_value = mock_client

        result = await handle_rag_retry_embeddings(db_session, task)

    refreshed = await repo.get(db_session, chunk.id)
    assert result["total"] == 1
    assert result["succeeded"] == 0
    assert result["failed"] == 1
    assert refreshed.embedding_status == "failed"
    assert len(refreshed.embedding_error) == 1000
