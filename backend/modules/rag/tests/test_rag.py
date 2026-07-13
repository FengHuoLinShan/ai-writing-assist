"""
RAG 模块测试

测试 CRUD、检索、分块、服务以及任务处理器注册。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.registry import TaskRegistry
from modules.rag import tasks as rag_tasks  # noqa: F401 — 注册任务处理器
from modules.rag.chunking import ChunkingService
from modules.rag.contracts import RagChunkContract, RagQueryContract, RagResultBundle
from modules.rag.facade import (
    create_chunk,
    get_index_status,
    list_chunks,
    retrieve,
    split_text_into_chunks,
)
from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository
from modules.rag.retrieval import RetrievalOrchestrator as RetrievalService
from modules.rag.schemas import (
    RagChunkCreate,
    SimilarEntity,
)
from modules.rag.scoring import (
    compute_keyword_score,
    compute_keyword_score_with_proximity,
    smart_tokenize_chinese,
)

# ============================================================
# 任务处理器注册测试
# ============================================================


def test_rag_task_handlers_are_registered() -> None:
    """rag_reindex_novel、rag_index_chapter 和 retry 任务应注册"""
    registry = TaskRegistry()
    assert "rag_reindex_novel" in registry
    assert "rag_index_chapter" in registry
    assert "rag_retry_embeddings" in registry
    handler = registry.get_handler("rag_reindex_novel")
    assert handler is not None
    assert callable(handler)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def repo() -> RagChunkRepository:
    return RagChunkRepository()


@pytest.fixture
def chunking() -> ChunkingService:
    return ChunkingService()


@pytest.fixture
def retrieval() -> RetrievalService:
    return RetrievalService()


@pytest.fixture
def sample_chunk_data() -> RagChunkCreate:
    return RagChunkCreate(
        source_type="chapter_text",
        source_id=str(uuid.uuid4()),
        chapter_index=1,
        text="艾伦从沉睡中醒来，发现自己置身于一片陌生的森林中。树木高耸入云，阳光透过叶间的缝隙洒下斑驳的光影。空气中弥漫着泥土和青草的气息，还有一丝若有若无的花香。",
        summary="艾伦在陌生森林中醒来",
        entity_ids=[str(uuid.uuid4())],
        character_ids=[str(uuid.uuid4())],
        thread_ids=[str(uuid.uuid4())],
        visibility="author_only",
        importance=0.8,
        meta={"location": "forest"},
    )


@pytest.fixture
def sample_chunk_data_2() -> RagChunkCreate:
    return RagChunkCreate(
        source_type="world_entity",
        source_id=str(uuid.uuid4()),
        chapter_index=3,
        text="古老的城堡坐落于悬崖之巅，灰色的石墙上爬满了常春藤。城堡内部阴暗潮湿，只有几支火把在走廊中闪烁着微弱的光芒。",
        summary="古老城堡的描述",
        entity_ids=[str(uuid.uuid4())],
        character_ids=[],
        thread_ids=[],
        visibility="reader_known",
        importance=0.6,
        meta={"location": "castle"},
    )


# ============================================================
# Repository 测试
# ============================================================


class TestRagChunkRepository:
    """测试数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
    ) -> None:
        """测试创建 RAG 片段"""
        chunk = await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        assert chunk.id is not None
        assert chunk.novel_id == sample_novel_id
        assert chunk.source_type == "chapter_text"
        assert chunk.text == sample_chunk_data.text
        assert chunk.importance == 0.8
        assert chunk.entity_ids == sample_chunk_data.entity_ids
        assert chunk.visibility == "author_only"

    @pytest.mark.asyncio
    async def test_create_many_preserves_order_and_assigns_ids(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """批量创建应保持输入顺序，并一次性返回可继续处理的 ORM 对象。"""
        chunks = await repo.create_many(
            db_with_project,
            sample_novel_id,
            [sample_chunk_data, sample_chunk_data_2],
        )

        assert [chunk.source_type for chunk in chunks] == [
            "chapter_text",
            "world_entity",
        ]
        assert all(chunk.id is not None for chunk in chunks)
        assert chunks[0].entity_ids == sample_chunk_data.entity_ids
        assert chunks[1].meta == sample_chunk_data_2.meta

    def test_postgres_json_filter_binds_json_array(
        self,
        repo: RagChunkRepository,
    ) -> None:
        """PostgreSQL JSONB contains 应绑定数组，而不是 JSON 字符串。"""

        class _Dialect:
            name = "postgresql"

        class _Bind:
            dialect = _Dialect()

        class _Db:
            def get_bind(self):
                return _Bind()

        expr = repo._json_array_contains_all(
            _Db(),
            RagChunk.character_ids,
            ["char-1"],
        )

        assert getattr(expr.right, "value", None) == ["char-1"]
        assert str(getattr(expr.right, "type", "")) == "JSONB"

    @pytest.mark.asyncio
    async def test_get(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
    ) -> None:
        """测试根据 ID 获取片段"""
        created = await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        fetched = await repo.get(db_with_project, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.text == sample_chunk_data.text

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
    ) -> None:
        """测试获取不存在的片段"""
        fake_id = uuid.uuid4()
        fetched = await repo.get(db_with_project, fake_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_multi(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """测试分页获取片段列表"""
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data_2)
        await db_with_project.flush()

        items, total = await repo.get_multi(
            db_with_project, sample_novel_id, skip=0, limit=10
        )
        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_delete(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
    ) -> None:
        """测试删除片段"""
        created = await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        deleted = await repo.delete(db_with_project, created.id)
        assert deleted is True

        fetched = await repo.get(db_with_project, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_many(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """批量删除片段应去重 ID，并返回实际删除数。"""
        first = await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        second = await repo.create(db_with_project, sample_novel_id, sample_chunk_data_2)

        deleted = await repo.delete_many(
            db_with_project,
            [first.id, first.id, second.id],
        )

        assert deleted == 2
        assert await repo.get(db_with_project, first.id) is None
        assert await repo.get(db_with_project, second.id) is None
        assert await repo.delete_many(db_with_project, []) == 0

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
    ) -> None:
        """测试删除不存在的片段"""
        fake_id = uuid.uuid4()
        deleted = await repo.delete(db_with_project, fake_id)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_mark_embedding_failed_clears_stale_embedding(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """失败 chunk 不应保留旧向量继续参与向量评分。"""
        chunk = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="待迁移片段",
                embedding_status="pending_vectorization",
            ),
        )
        chunk.embedding = [0.1] * 768  # type: ignore[assignment]
        await db_with_project.flush()

        updated = await repo.mark_embedding_failed(db_with_project, chunk.id, "down")
        await db_with_project.flush()
        refreshed = await repo.get(db_with_project, chunk.id)

        assert updated is True
        assert refreshed.embedding_status == "failed"
        assert refreshed.embedding is None

    @pytest.mark.asyncio
    async def test_retryable_embedding_queries_are_scoped_to_novel_and_range(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """失败向量重试候选必须按 novel_id 和章节范围隔离。"""
        other_novel_id = uuid.uuid4()
        from modules.project.models import Project

        db_with_project.add(
            Project(
                id=other_novel_id,
                title="另一个项目",
                genre="玄幻",
                language="zh",
            )
        )
        await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="第一章失败片段",
                embedding_status="failed",
            ),
        )
        await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=2,
                text="第二章待重向量化片段",
                embedding_status="pending_vectorization",
            ),
        )
        await repo.create(
            db_with_project,
            other_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="其他项目失败片段",
                embedding_status="failed",
            ),
        )
        await db_with_project.flush()

        count = await repo.count_retryable_embeddings(
            db_with_project,
            sample_novel_id,
            statuses=["failed", "pending_vectorization"],
            start_chapter=2,
            end_chapter=2,
        )
        candidates = await repo.find_embedding_retry_candidates(
            db_with_project,
            sample_novel_id,
            statuses=["failed", "pending_vectorization"],
            start_chapter=2,
            end_chapter=2,
        )

        assert count == 1
        assert len(candidates) == 1
        assert candidates[0].novel_id == sample_novel_id
        assert candidates[0].chapter_index == 2

    @pytest.mark.asyncio
    async def test_keyword_search(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """测试关键词检索"""
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data_2)
        await db_with_project.flush()

        results = await repo.keyword_search(db_with_project, sample_novel_id, "森林")
        assert len(results) >= 1
        assert "森林" in results[0].text

        results = await repo.keyword_search(db_with_project, sample_novel_id, "城堡")
        assert len(results) >= 1
        assert "城堡" in results[0].text

    @pytest.mark.asyncio
    async def test_keyword_search_with_filters(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """测试带过滤条件的关键词检索"""
        created = await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data_2)
        await db_with_project.flush()

        results = await repo.keyword_search(
            db_with_project,
            sample_novel_id,
            "森林",
            character_ids=sample_chunk_data.character_ids,
        )
        assert len(results) >= 1
        assert results[0].id == created.id

    @pytest.mark.asyncio
    async def test_keyword_search_filters_by_scene_id(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """同章不同 Scene 的 chunks，scene_id=A 时只返回 A。"""
        scene_a = str(uuid.uuid4())
        scene_b = str(uuid.uuid4())
        chunk_a = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                scene_id=scene_a,
                text="警报声在主控室响起。",
                importance=0.2,
            ),
        )
        await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                scene_id=scene_b,
                text="警报声在后续房间响起。",
                importance=0.9,
            ),
        )
        await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="警报声在无 Scene 标注片段中响起。",
                importance=1.0,
            ),
        )
        await db_with_project.flush()

        results = await repo.keyword_search(
            db_with_project,
            sample_novel_id,
            "警报声",
            chapter_index=1,
            scene_id=scene_a,
            strict_scene_filter=True,
        )

        assert [chunk.id for chunk in results] == [chunk_a.id]

    @pytest.mark.asyncio
    async def test_vector_search_filters_by_scene_id_in_python_fallback(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """vector path 也必须应用 scene_id metadata filter。"""
        scene_a = str(uuid.uuid4())
        scene_b = str(uuid.uuid4())
        embedding = [1.0, *([0.0] * 767)]
        chunk_a = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                scene_id=scene_a,
                text="主控室当前 Scene。",
                embedding_status="succeeded",
            ),
        )
        chunk_a.embedding = embedding
        chunk_b = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                scene_id=scene_b,
                text="后续 Scene。",
                embedding_status="succeeded",
            ),
        )
        chunk_b.embedding = embedding
        chunk_null = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="无 Scene 标注片段。",
                embedding_status="succeeded",
            ),
        )
        chunk_null.embedding = embedding
        await db_with_project.flush()

        results = await repo.vector_search(
            db_with_project,
            sample_novel_id,
            embedding,
            chapter_index=1,
            scene_id=scene_a,
            strict_scene_filter=True,
            top_k=5,
        )

        assert [chunk.id for chunk, _score in results] == [chunk_a.id]

    @pytest.mark.asyncio
    async def test_keyword_search_prioritizes_chunks_matching_more_query_terms(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                chunk_index=1,
                text="森林里传来遥远的回声。",
                importance=0.9,
            ),
        )
        stronger = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                chunk_index=2,
                text="森林里发现了失落令牌，守卫因此打开城门。",
                importance=0.1,
            ),
        )
        await db_with_project.flush()

        results = await repo.keyword_search(
            db_with_project,
            sample_novel_id,
            "森林 令牌",
            limit=1,
        )

        assert [chunk.id for chunk in results] == [stronger.id]

    @pytest.mark.asyncio
    async def test_keyword_search_recalls_unspaced_chinese_compound_query(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        chunk = await repo.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="森林里发现了失落令牌，守卫因此打开城门。",
            ),
        )
        await db_with_project.flush()

        results = await repo.keyword_search(
            db_with_project,
            sample_novel_id,
            "森林令牌",
            limit=3,
        )

        assert [item.id for item in results] == [chunk.id]

    @pytest.mark.asyncio
    async def test_find_by_entity(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
    ) -> None:
        """测试按实体 ID 检索"""
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        await db_with_project.flush()

        entity_id = sample_chunk_data.entity_ids[0]
        results = await repo.find_by_entity(db_with_project, sample_novel_id, entity_id)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_vector_search_returns_empty(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """测试向量检索返回空列表（SQLite 模式）"""
        results = await repo.vector_search(
            db_with_project,
            sample_novel_id,
            [0.1] * 10,
            top_k=5,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_count_by_novel(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
    ) -> None:
        """测试统计片段数"""
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        await db_with_project.flush()
        count = await repo.count_by_novel(db_with_project, sample_novel_id)
        assert count == 1

    @pytest.mark.asyncio
    async def test_delete_by_novel(
        self,
        repo: RagChunkRepository,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """测试批量删除"""
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data)
        await repo.create(db_with_project, sample_novel_id, sample_chunk_data_2)
        await db_with_project.flush()
        deleted = await repo.delete_by_novel(db_with_project, sample_novel_id)
        assert deleted == 2


# ============================================================
# ChunkingService 测试
# ============================================================


class TestChunkingService:
    """测试分块服务"""

    def test_split_by_paragraphs(self, chunking: ChunkingService) -> None:
        """测试按段落分割"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        chunks = chunking.split_by_paragraphs(text)
        assert len(chunks) == 3
        assert "第一段内容" in chunks[0]
        assert "第二段内容" in chunks[1]
        assert "第三段内容" in chunks[2]

    def test_split_by_paragraphs_empty(self, chunking: ChunkingService) -> None:
        """测试空文本分割"""
        chunks = chunking.split_by_paragraphs("")
        assert chunks == []
        chunks = chunking.split_by_paragraphs("   ")
        assert chunks == []

    def test_split_by_length(self, chunking: ChunkingService) -> None:
        """测试按长度分割"""
        text = "这是一个测试文本。" * 50
        chunks = chunking.split_by_length(text, chunk_size=100, overlap=0)
        assert len(chunks) > 1
        assert all(c for c in chunks)

    def test_split_by_length_with_overlap(self, chunking: ChunkingService) -> None:
        """测试带重叠的长度分割"""
        text = "这是第一句。这是第二句。这是第三句。这是第四句。" * 10
        chunks = chunking.split_by_length(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1

    def test_extract_summary_short(self, chunking: ChunkingService) -> None:
        """测试短文本摘要"""
        text = "这是一段短文本。"
        summary = chunking.extract_summary(text, max_length=200)
        assert summary == text

    def test_extract_summary_long(self, chunking: ChunkingService) -> None:
        """测试长文本摘要"""
        text = "这是一段很长的文本。" * 50
        summary = chunking.extract_summary(text, max_length=20)
        assert len(summary) <= 23

    def test_split_long_paragraph(self, chunking: ChunkingService) -> None:
        """测试超长段落按句号分割"""
        long_para = "第一句。第二句！第三句？第四句。" * 100
        chunks = chunking.split_by_paragraphs(long_para, max_length=200)
        assert len(chunks) > 1

    def test_split_chinese_novel_keeps_offsets_and_overlap(
        self,
        chunking: ChunkingService,
    ) -> None:
        """中文小说分块应保留正文位置，并为长正文创建前后文重叠。"""
        text = "\n\n".join(
            [
                "周明瑞睁开眼睛，发现自己躺在陌生的房间里。" * 12,
                "他按住额头，试图理清脑海里混乱的记忆。" * 12,
                "窗外的煤气灯仍然亮着，克莱恩这个名字浮了出来。" * 12,
            ]
        )

        chunks = chunking.split_chinese_novel(
            text,
            target_length=180,
            max_length=260,
            overlap=40,
        )

        assert len(chunks) >= 3
        assert chunks[0].chunk_index == 0
        assert all(c.text == text[c.start_offset : c.end_offset].strip() for c in chunks)
        assert all(c.char_count == len(c.text) for c in chunks)
        assert any(
            chunks[i].start_offset < chunks[i - 1].end_offset
            for i in range(1, len(chunks))
        )

    def test_cn_boundary_prefers_scene_transition_over_paragraph(
        self,
        chunking: ChunkingService,
    ) -> None:
        """场景转换关键词优先级高于更接近 target 的段落边界。"""
        text = "甲" * 90 + "\n\n" + "乙" * 20 + "第二天" + "丙" * 40

        boundary = chunking._choose_cn_boundary_with_scenes(
            text,
            start=0,
            target_length=100,
            hard_end=len(text),
        )

        assert boundary == text.rfind("第二天")

    def test_cn_boundary_scene_pattern_keeps_only_last_occurrence(
        self,
        chunking: ChunkingService,
    ) -> None:
        """保持旧语义：每个 scene pattern 只取窗口内最后一次出现。"""
        text = "甲" * 90 + "第二天" + "乙" * 30 + "第二天" + "丙" * 40

        boundary = chunking._choose_cn_boundary_with_scenes(
            text,
            start=0,
            target_length=100,
            hard_end=len(text),
        )

        assert boundary == text.rfind("第二天")

    def test_cn_boundary_prefers_location_transition_over_paragraph(
        self,
        chunking: ChunkingService,
    ) -> None:
        text = "甲" * 90 + "\n\n来到王城，众人放慢脚步。" + "乙" * 40

        boundary = chunking._choose_cn_boundary_with_scenes(
            text,
            start=0,
            target_length=100,
            hard_end=len(text),
        )

        assert boundary == text.rfind("\n\n")

    def test_cn_boundary_uses_paragraph_then_sentence_fallbacks(
        self,
        chunking: ChunkingService,
    ) -> None:
        paragraph_text = "甲" * 90 + "\n\n" + "乙" * 50
        sentence_text = "甲" * 90 + "。" + "乙" * 50

        paragraph_boundary = chunking._choose_cn_boundary_with_scenes(
            paragraph_text,
            start=0,
            target_length=100,
            hard_end=len(paragraph_text),
        )
        sentence_boundary = chunking._choose_cn_boundary_with_scenes(
            sentence_text,
            start=0,
            target_length=100,
            hard_end=len(sentence_text),
        )

        assert paragraph_boundary == paragraph_text.rfind("\n\n") + 2
        assert sentence_boundary == sentence_text.rfind("。") + 1


# ============================================================
# RetrievalService 测试
# ============================================================


class TestRetrievalService:
    """测试混合检索服务"""

    @pytest.mark.asyncio
    async def test_hybrid_search(
        self,
        retrieval: RetrievalService,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """测试混合检索"""
        repo_local = RagChunkRepository()
        chunk1 = await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="艾伦在森林中迷失了方向，四周都是高耸的树木。",
                entity_ids=["e1"],
                character_ids=["c1"],
                importance=0.9,
            ),
        )
        chunk2 = await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=2,
                text="城堡的大门缓缓打开，发出沉重的声响。",
                entity_ids=["e2"],
                importance=0.5,
            ),
        )
        await db_with_project.flush()

        # 检索"森林"
        results = await retrieval.hybrid_search(
            db_with_project,
            sample_novel_id,
            "森林",
            top_k=5,
        )
        assert len(results) >= 1
        top_chunk, top_score = results[0]
        assert top_chunk.id == chunk1.id
        assert top_score > 0

        # 检索"城堡"
        results = await retrieval.hybrid_search(
            db_with_project,
            sample_novel_id,
            "城堡",
            top_k=5,
        )
        assert len(results) >= 1
        top_chunk, top_score = results[0]
        assert top_chunk.id == chunk2.id

    @pytest.mark.asyncio
    async def test_hybrid_search_with_filters(
        self,
        retrieval: RetrievalService,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """测试带过滤的混合检索"""
        repo_local = RagChunkRepository()
        await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在森林中探索。",
                entity_ids=["e1"],
                character_ids=["c1"],
            ),
        )
        await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在城堡中。",
                entity_ids=["e2"],
                character_ids=["c1"],
            ),
        )
        await db_with_project.flush()

        results = await retrieval.hybrid_search(
            db_with_project,
            sample_novel_id,
            "艾伦",
            entity_ids=["e1"],
            top_k=5,
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_extraction_mode_allows_relation_only_match(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """抽取模式下，明确人物过滤命中时不要求字段关键词也出现在正文。"""
        char_id = str(uuid.uuid4())
        await create_chunk(
            db_with_project,
            str(sample_novel_id),
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="周明瑞从梦中醒来，陌生的天花板映入眼帘。",
                character_ids=[char_id],
            ),
        )
        await db_with_project.flush()

        result = await retrieve(
            db_with_project,
            str(sample_novel_id),
            "克莱恩 欲望 目标 计划",
            character_ids=[char_id],
            mode="extraction",
        )

        assert result.total == 1
        assert result.chunks[0].character_ids == [char_id]
        assert result.degraded is False

    @pytest.mark.asyncio
    async def test_retrieve_expands_character_alias_terms(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """查询人物现名时，应召回正文里使用旧名/别名的 chunk。"""
        from modules.world.models import Character, CoreEntity

        char_id = uuid.uuid4()
        db_with_project.add(
            CoreEntity(
                id=char_id,
                novel_id=sample_novel_id,
                entity_type="character",
                name="克莱恩·莫雷蒂",
                content_json={"aliases": [{"alias": "周明瑞", "type": "original_name"}]},
                status="canonical",
            )
        )
        db_with_project.add(
            Character(
                entity_id=char_id,
                novel_id=sample_novel_id,
                name="克莱恩·莫雷蒂",
                aliases=[{"alias": "周明瑞", "type": "original_name"}],
                role="主角",
                status="canonical",
            )
        )
        await create_chunk(
            db_with_project,
            str(sample_novel_id),
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="周明瑞从梦中醒来，脑袋抽痛异常。",
                character_ids=[str(char_id)],
            ),
        )
        await db_with_project.flush()

        result = await retrieve(db_with_project, str(sample_novel_id), "克莱恩")

        assert result.total == 1
        assert "周明瑞" in result.chunks[0].text

    @pytest.mark.asyncio
    async def test_retrieve_recalls_unspaced_chinese_compound_query(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        await create_chunk(
            db_with_project,
            str(sample_novel_id),
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="森林里发现了失落令牌，守卫因此打开城门。",
            ),
        )
        await db_with_project.flush()

        result = await retrieve(db_with_project, str(sample_novel_id), "森林令牌")

        assert result.total == 1
        assert "失落令牌" in result.chunks[0].text

    @pytest.mark.asyncio
    async def test_retrieve_reports_degraded_when_query_embedding_fails(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """已有 embedding 时查询向量失败应降级并返回 warning。"""
        from unittest.mock import AsyncMock, patch

        repo_local = RagChunkRepository()
        chunk = await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="周明瑞在灰雾中醒来。",
            ),
        )
        chunk.embedding = [0.1] * 768  # type: ignore[assignment]
        await db_with_project.flush()

        with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.generate_embedding = AsyncMock(
                side_effect=Exception("embedding down")
            )
            mock_client_cls.return_value = mock_client

            async def _no_expand(*args, **kwargs) -> str:  # noqa: ANN002, ANN003
                return str(args[2])

            with patch(
                "modules.rag.query_expansion._expand_query_with_project_terms",
                side_effect=_no_expand,
            ):
                result = await retrieve(db_with_project, str(sample_novel_id), "灰雾")

        assert result.total == 1
        assert result.degraded is True
        assert result.warnings

    @pytest.mark.asyncio
    async def test_retrieve_reports_degraded_when_returned_chunk_embedding_failed(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """召回结果包含 failed embedding chunk 时应暴露顶层降级状态。"""
        from unittest.mock import patch

        repo_local = RagChunkRepository()
        await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="铜铃在雨夜响起。",
                embedding_status="failed",
                embedding_error="embedding down",
                index_warnings=["embedding 降级为关键词检索"],
            ),
        )
        await db_with_project.flush()

        async def _no_expand(*args, **kwargs) -> str:  # noqa: ANN002, ANN003
            return str(args[2])

        with patch(
            "modules.rag.query_expansion._expand_query_with_project_terms",
            side_effect=_no_expand,
        ):
            result = await retrieve(db_with_project, str(sample_novel_id), "铜铃")

        assert result.total == 1
        assert result.degraded is True
        assert "embedding 降级为关键词检索" in result.warnings

    @pytest.mark.asyncio
    async def test_score_computation(self) -> None:
        """测试评分计算"""
        score = compute_keyword_score(
            "艾伦在森林中行走",
            ["森林"],
        )
        assert score == 1.0

        score = compute_keyword_score("艾伦在城堡中", ["森林"])
        assert score == 0.0

        score = compute_keyword_score(
            "森林和城堡都在大陆上",
            ["森林", "城堡"],
        )
        assert score == 1.0

        score = compute_keyword_score("森林", [])
        assert score == 0.0


# ============================================================
# Facade 测试
# ============================================================


class TestRagFacade:
    """测试对外入口"""

    @pytest.mark.asyncio
    async def test_create_chunk(
        self,
        db_with_project: AsyncSession,
        sample_chunk_data: RagChunkCreate,
    ) -> None:
        """测试创建片段"""
        novel_id = str(uuid.uuid4())
        resp = await create_chunk(db_with_project, novel_id, sample_chunk_data)
        assert resp.id is not None
        assert resp.novel_id == novel_id
        assert resp.source_type == "chapter_text"
        assert resp.text == sample_chunk_data.text
        assert resp.created_at is not None

    @pytest.mark.asyncio
    async def test_list_chunks(
        self,
        db_with_project: AsyncSession,
        sample_chunk_data: RagChunkCreate,
        sample_chunk_data_2: RagChunkCreate,
    ) -> None:
        """测试列表"""
        novel_id = str(uuid.uuid4())
        await create_chunk(db_with_project, novel_id, sample_chunk_data)
        await create_chunk(db_with_project, novel_id, sample_chunk_data_2)

        items, total = await list_chunks(db_with_project, novel_id)
        assert total == 2
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_retrieve(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试检索"""
        novel_id = str(uuid.uuid4())

        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在森林中迷失了方向，四周都是高耸的树木。",
                importance=0.9,
            ),
        )
        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="城堡的大门紧闭，似乎已经很久没有人来过了。",
                importance=0.5,
            ),
        )
        await db_with_project.flush()

        result = await retrieve(db_with_project, novel_id, "森林")
        assert isinstance(result, RagResultBundle)
        assert result.total >= 1
        assert result.query == "森林"
        if result.chunks:
            assert "森林" in result.chunks[0].text

    @pytest.mark.asyncio
    async def test_retrieve_with_custom_top_k(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试自定义 top_k"""
        novel_id = str(uuid.uuid4())

        for i in range(5):
            await create_chunk(
                db_with_project,
                novel_id,
                RagChunkCreate(
                    source_type="chapter_text",
                    text=f"这是第{i + 1}个测试片段的内容。",
                    importance=0.5,
                ),
            )
        await db_with_project.flush()

        result = await retrieve(db_with_project, novel_id, "测试", top_k=3)
        assert result.total <= 3

    @pytest.mark.asyncio
    async def test_retrieve_visible_until_chapter_excludes_future_chunks(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())

        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="秘密线索在第一章出现。",
                importance=0.5,
            ),
        )
        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=2,
                text="秘密线索在第二章揭晓。",
                importance=0.9,
            ),
        )
        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="outline",
                text="秘密线索的无章节索引。",
                importance=0.7,
            ),
        )
        await db_with_project.flush()

        result = await retrieve(
            db_with_project,
            novel_id,
            "秘密线索",
            visible_until_chapter=1,
            top_k=10,
        )

        chapters = {chunk.chapter_index for chunk in result.chunks}
        assert 2 not in chapters
        assert 1 in chapters
        assert None in chapters

    @pytest.mark.asyncio
    async def test_retrieve_with_filters(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试带过滤的检索"""
        novel_id = str(uuid.uuid4())
        char_id = str(uuid.uuid4())

        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在森林中。",
                character_ids=[char_id],
            ),
        )
        await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="城堡大门紧闭。",
                character_ids=[],
            ),
        )
        await db_with_project.flush()

        result = await retrieve(
            db_with_project,
            novel_id,
            "艾伦",
            character_ids=[char_id],
        )
        if result.chunks:
            assert result.chunks[0].character_ids == [char_id]

    @pytest.mark.asyncio
    async def test_split_text_into_chunks_paragraph(self) -> None:
        """测试文本分割段落模式"""
        text = "第一段。\n\n第二段。\n\n第三段。"
        chunks = await split_text_into_chunks(text, method="paragraph")
        assert len(chunks) == 3

    @pytest.mark.asyncio
    async def test_split_text_into_chunks_length(self) -> None:
        """测试文本分割长度模式"""
        text = "这是一个测试文本。" * 30
        chunks = await split_text_into_chunks(
            text,
            method="length",
            chunk_size=50,
            overlap=10,
        )
        assert len(chunks) > 1

    @pytest.mark.asyncio
    async def test_retrieve_empty_result(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试空结果检索"""
        novel_id = str(uuid.uuid4())
        result = await retrieve(db_with_project, novel_id, "不存在的关键词")
        assert result.total == 0
        assert result.chunks == []

    @pytest.mark.asyncio
    async def test_create_chunk_with_defaults(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试使用默认值创建"""
        novel_id = str(uuid.uuid4())
        chunk = await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="测试内容",
            ),
        )
        assert chunk.importance == 0.5
        assert chunk.visibility == "author_only"
        assert chunk.entity_ids == []
        assert chunk.character_ids == []
        assert chunk.thread_ids == []
        assert chunk.meta == {}

    @pytest.mark.asyncio
    async def test_get_index_status_reports_indexed_embedding_dim_when_config_drifts(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """状态页应显示已索引向量实际维度，并提示配置漂移。"""
        from types import SimpleNamespace
        from unittest.mock import patch

        repo_local = RagChunkRepository()
        chunk = await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="周明瑞从绯红的梦境中醒来。",
                embedding_status="succeeded",
            ),
        )
        chunk.embedding = [0.1] * 768  # type: ignore[assignment]
        await db_with_project.flush()

        settings = SimpleNamespace(
            embedding_provider="bge_onnx",
            embedding_model="bge-base-zh-v1.5",
            embedding_dim=1024,
        )
        with patch("core.config.get_settings", return_value=settings):
            status = await get_index_status(db_with_project, str(sample_novel_id))

        assert status["embedding_dim"] == 768
        assert status["configured_embedding_dim"] == 1024
        assert status["indexed_embedding_dim"] == 768
        assert status["embedding_dimension_mismatch"] is True
        assert status["degraded"] is True
        assert any("EMBEDDING_DIM=1024" in warning for warning in status["warnings"])

    @pytest.mark.asyncio
    async def test_get_index_status_includes_runtime_and_retryable_count(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """状态页诊断应包含 runtime 快照和可重试 embedding 数。"""
        repo_local = RagChunkRepository()
        await repo_local.create(
            db_with_project,
            sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                chapter_index=1,
                text="失败片段",
                embedding_status="failed",
            ),
        )
        await db_with_project.flush()

        status = await get_index_status(db_with_project, str(sample_novel_id))

        assert status["retryable_embedding_count"] == 1
        assert status["embedding_runtime"]["started"] is False
        assert status["embedding_runtime"]["healthy"] is False
        assert "cache_stats" in status["embedding_runtime"]


@pytest.mark.asyncio
async def test_retry_embeddings_endpoint_enqueues_task() -> None:
    """API 层只校验请求并提交 rag_retry_embeddings 任务。"""
    from unittest.mock import patch

    from modules.rag.api import retry_embeddings
    from modules.rag.schemas import RagRetryEmbeddingsRequest

    request = RagRetryEmbeddingsRequest(
        novel_id=str(uuid.uuid4()),
        start_chapter=1,
        end_chapter=3,
        statuses=["failed"],
    )
    db = object()
    assert inspect.iscoroutinefunction(retry_embeddings)
    with (
        patch(
            "modules.rag.api._require_active_project",
            autospec=True,
        ) as guard,
        patch(
            "modules.rag.api.enqueue_task",
            autospec=True,
            return_value="task-rag-retry",
        ) as mocked,
    ):
        result = await retry_embeddings(db, request)

    guard.assert_awaited_once_with(db, request.novel_id)
    assert result == {"task_id": "task-rag-retry", "status": "pending"}
    mocked.assert_called_once_with(
        db,
        "rag_retry_embeddings",
        meta={
            "novel_id": request.novel_id,
            "start_chapter": 1,
            "end_chapter": 3,
            "statuses": ["failed"],
        },
    )


# ============================================================
# Contracts 测试
# ============================================================


class TestRagContracts:
    """测试契约类"""

    def test_rag_chunk_contract_defaults(self) -> None:
        """测试 RAG 片段契约默认值"""
        contract = RagChunkContract(
            id="test-id",
            novel_id="novel-id",
            source_type="chapter_text",
        )
        assert contract.entity_ids == []
        assert contract.character_ids == []
        assert contract.importance == 0.5
        assert contract.visibility == "author_only"

    def test_rag_query_contract(self) -> None:
        """测试 RAG 查询契约"""
        contract = RagQueryContract(query="测试")
        assert contract.query == "测试"
        assert contract.top_k == 12
        assert contract.entity_ids is None

    def test_rag_result_bundle(self) -> None:
        """测试 RAG 结果"""
        bundle = RagResultBundle()
        assert bundle.chunks == []
        assert bundle.total == 0
        assert bundle.query == ""

    def test_similar_entity(self) -> None:
        """测试相似实体"""
        entity = SimilarEntity(
            entity_id="test-id",
            name="测试实体",
            similarity_score=0.95,
        )
        assert entity.similarity_score == 0.95


# ============================================================
# 中文分词器测试
# ============================================================


class TestSmartTokenizeChinese:
    """测试 _smart_tokenize_chinese 分词器"""

    def test_space_separated(self) -> None:
        terms = smart_tokenize_chinese("克莱恩 渴望 目标")
        assert terms == ["克莱恩", "渴望", "目标"]

    def test_punctuation_separated(self) -> None:
        terms = smart_tokenize_chinese("克莱恩·莫雷蒂，渴望")
        assert "克莱恩" in terms
        assert "莫雷蒂" in terms
        assert "渴望" in terms

    def test_single_char_filtered(self) -> None:
        terms = smart_tokenize_chinese("一 的 人")
        assert terms == []

    def test_mixed_separators(self) -> None:
        terms = smart_tokenize_chinese("克莱恩·莫雷蒂 渴望，目标。动机！")
        assert "克莱恩" in terms
        assert "莫雷蒂" in terms
        assert "渴望" in terms
        assert "目标" in terms
        assert "动机" in terms

    def test_empty_query(self) -> None:
        assert smart_tokenize_chinese("") == []

    def test_single_term(self) -> None:
        terms = smart_tokenize_chinese("克莱恩")
        assert terms == ["克莱恩"]

    def test_mixed_chinese_english(self) -> None:
        terms = smart_tokenize_chinese("Klein 渴望")
        assert "klein" in terms
        assert "渴望" in terms

    def test_two_char_terms_preserved(self) -> None:
        terms = smart_tokenize_chinese("渴望 恐惧")
        assert terms == ["渴望", "恐惧"]


class TestKeywordProximityScore:
    """测试关键词邻近度评分"""

    def test_proximity_bonus_close_terms(self) -> None:
        score = compute_keyword_score_with_proximity(
            "克莱恩渴望力量",
            ["克莱恩", "渴望"],
        )
        assert score > 0.5

    def test_proximity_bonus_far_terms(self) -> None:
        score_far = compute_keyword_score_with_proximity(
            "克莱恩在很远很远的地方感受到了渴望",
            ["克莱恩", "渴望"],
        )
        score_close = compute_keyword_score_with_proximity(
            "克莱恩渴望力量",
            ["克莱恩", "渴望"],
        )
        assert score_close >= score_far

    def test_single_term_no_proximity(self) -> None:
        score = compute_keyword_score_with_proximity(
            "克莱恩在森林中",
            ["克莱恩"],
        )
        assert score == 1.0


# ============================================================
# 新增验收测试
# ============================================================


class TestRagRetrievalBoundaries:
    """检索边界行为测试"""

    @pytest.mark.asyncio
    async def test_retrieve_top_k_capped(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """top_k 超过 50 时应被截断为 50，返回结果数 ≤50。"""
        for i in range(60):
            await create_chunk(
                db_with_project,
                str(sample_novel_id),
                RagChunkCreate(
                    source_type="chapter_text",
                    text=f"这是第{i:03d}个包含关键词的测试片段。",
                    importance=0.5,
                ),
            )
        await db_with_project.flush()

        result = await retrieve(
            db_with_project,
            str(sample_novel_id),
            "关键词",
            top_k=100,
        )
        assert len(result.chunks) <= 50
        assert result.total >= len(result.chunks)
        assert result.total <= 60

    @pytest.mark.asyncio
    async def test_retrieve_cross_novel_isolation(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """在小说 A 创建 chunk，用小说 B 检索应返回空。"""
        novel_a = str(uuid.uuid4())
        novel_b = str(uuid.uuid4())

        await create_chunk(
            db_with_project,
            novel_a,
            RagChunkCreate(
                source_type="chapter_text",
                text="只属于小说 A 的内容。",
            ),
        )
        await db_with_project.flush()

        result = await retrieve(db_with_project, novel_b, "只属于小说 A")
        assert result.total == 0
        assert result.chunks == []

    @pytest.mark.asyncio
    async def test_retrieve_filter_by_chapter_index(
        self,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """按 chapter_index 过滤应只返回目标章节的 chunk。"""
        for idx, chapter in enumerate((1, 1, 2, 2, 3), start=1):
            await create_chunk(
                db_with_project,
                str(sample_novel_id),
                RagChunkCreate(
                    source_type="chapter_text",
                    chapter_index=chapter,
                    text=f"第{chapter}章第{idx}个片段。",
                ),
            )
        await db_with_project.flush()

        result = await retrieve(
            db_with_project,
            str(sample_novel_id),
            "第2章",
            chapter_index=2,
        )
        assert result.total >= 1
        assert all(c.chapter_index == 2 for c in result.chunks)

    @pytest.mark.asyncio
    async def test_chunk_create_with_scene_id(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """创建 chunk 时携带 scene_id 应可正确读取。"""
        novel_id = str(uuid.uuid4())
        scene_id = str(uuid.uuid4())

        resp = await create_chunk(
            db_with_project,
            novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="与 Scene 关联的片段内容。",
                scene_id=scene_id,
            ),
        )
        assert resp.scene_id == scene_id

        repo = RagChunkRepository()
        chunk = await repo.get(db_with_project, uuid.UUID(hex=resp.id))
        assert chunk is not None
        assert str(chunk.scene_id) == scene_id
