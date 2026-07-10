"""
TB1: RAG 章节索引 — 测试
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate
from tests.conftest import test_character_id, test_project_id  # noqa: F401


@pytest.fixture
def repo() -> RagChunkRepository:
    return RagChunkRepository()


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
    with patch("modules.rag.index_state.enqueue_task", enqueue):
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
    with patch("modules.rag.index_state.enqueue_task", enqueue):
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    with patch("infrastructure.llm.client.LLMClient") as client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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

    embed_exc = Exception("embedding down")
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        result = await handle_rag_reindex_novel(db_session, task)

    assert result["total_chapters"] == 1
    assert result["chunks_created"] >= 1
    chapter_indices = [c["chapter_index"] for c in result["chapters"]]
    assert chapter_indices == [2]


@pytest.mark.asyncio
async def test_retry_embeddings_task_updates_failed_chunks(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """rag_retry_embeddings 只修复目标项目内的失败向量。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_retry_embeddings

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
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_retry_embeddings",
        status="running",
        meta={"novel_id": test_project_id, "start_chapter": 1, "end_chapter": 1},
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()

    fake_embedding = [0.1] * 768
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    assert refreshed.embedding_status == "succeeded"
    assert refreshed.embedding is not None
    assert refreshed.embedding_error is None
    assert skipped.embedding_status == "failed"


@pytest.mark.asyncio
async def test_retry_embeddings_task_counts_partial_batch_fallback(
    db_session: AsyncSession,
    repo: RagChunkRepository,
    test_project_id: str,  # noqa: F811
):
    """批量路径降级后部分成功时，应统计成功数并清理失败 stale embedding。"""
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.tasks import handle_rag_retry_embeddings

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

    fake_embedding = [0.1] * 768

    async def _fake_embedding(value):
        if isinstance(value, list):
            raise RuntimeError("batch down")
        if value == "可恢复片段":
            return fake_embedding
        raise RuntimeError("single down")

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    from modules.rag.tasks import handle_rag_retry_embeddings

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

    fake_embedding = [0.1] * 768

    async def _fake_embedding(value):
        if isinstance(value, list):
            raise RuntimeError("batch down")
        return fake_embedding

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    from modules.rag.tasks import handle_rag_retry_embeddings

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

    fake_embedding = [0.1] * 768

    async def _fake_embedding(texts):
        return [fake_embedding for _ in texts]

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
    from modules.rag.tasks import handle_rag_retry_embeddings

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

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
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
