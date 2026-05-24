"""
RAG 模块测试

测试 CRUD、检索、分块和服务。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.contracts import RagChunkContract, RagQueryContract, RagResultBundle
from modules.rag.facade import (
    create_chunk,
    find_similar_entities,
    list_chunks,
    retrieve,
    split_text_into_chunks,
)
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import (
    RagChunkCreate,
    RagChunkResponse,
    RagQuery,
    RagResult,
    SimilarEntity,
)
from modules.rag.services import ChunkingService, EmbeddingService, RetrievalService


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

        items, total = await repo.get_multi(db_with_project, sample_novel_id, skip=0, limit=10)
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
            db_with_project, sample_novel_id, [0.1] * 10, top_k=5,
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


# ============================================================
# EmbeddingService 测试
# ============================================================

class TestEmbeddingService:
    """测试 Embedding 服务"""

    @pytest.mark.asyncio
    async def test_generate_embedding_returns_none(self) -> None:
        """测试生成 embedding 返回 None（预留接口）"""
        svc = EmbeddingService()
        result = await svc.generate_embedding("测试文本")
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch(self) -> None:
        """测试批量生成 embedding 返回 None 列表"""
        svc = EmbeddingService()
        results = await svc.generate_embeddings_batch(["a", "b", "c"])
        assert results == [None, None, None]


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
            db_with_project, sample_novel_id,
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
            db_with_project, sample_novel_id,
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
            db_with_project, sample_novel_id, "森林", top_k=5,
        )
        assert len(results) >= 1
        top_chunk, top_score = results[0]
        assert top_chunk.id == chunk1.id
        assert top_score > 0

        # 检索"城堡"
        results = await retrieval.hybrid_search(
            db_with_project, sample_novel_id, "城堡", top_k=5,
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
            db_with_project, sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在森林中探索。",
                entity_ids=["e1"],
                character_ids=["c1"],
            ),
        )
        await repo_local.create(
            db_with_project, sample_novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在城堡中。",
                entity_ids=["e2"],
                character_ids=["c1"],
            ),
        )
        await db_with_project.flush()

        results = await retrieval.hybrid_search(
            db_with_project, sample_novel_id, "艾伦",
            entity_ids=["e1"], top_k=5,
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_find_similar_entities_returns_empty(
        self,
        retrieval: RetrievalService,
        db_with_project: AsyncSession,
        sample_novel_id: uuid.UUID,
    ) -> None:
        """测试相似实体检索返回空列表（预留接口）"""
        results = await retrieval.find_similar_entities(
            db_with_project, sample_novel_id, [0.1] * 10,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_score_computation(self) -> None:
        """测试评分计算"""
        score = RetrievalService._compute_keyword_score(
            "艾伦在森林中行走", ["森林"],
        )
        assert score == 1.0

        score = RetrievalService._compute_keyword_score("艾伦在城堡中", ["森林"])
        assert score == 0.0

        score = RetrievalService._compute_keyword_score(
            "森林和城堡都在大陆上", ["森林", "城堡"],
        )
        assert score == 1.0

        score = RetrievalService._compute_keyword_score("森林", [])
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
            db_with_project, novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在森林中迷失了方向，四周都是高耸的树木。",
                importance=0.9,
            ),
        )
        await create_chunk(
            db_with_project, novel_id,
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
                db_with_project, novel_id,
                RagChunkCreate(
                    source_type="chapter_text",
                    text=f"这是第{i+1}个测试片段的内容。",
                    importance=0.5,
                ),
            )
        await db_with_project.flush()

        result = await retrieve(db_with_project, novel_id, "测试", top_k=3)
        assert result.total <= 3

    @pytest.mark.asyncio
    async def test_retrieve_with_filters(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试带过滤的检索"""
        novel_id = str(uuid.uuid4())
        char_id = str(uuid.uuid4())

        await create_chunk(
            db_with_project, novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="艾伦在森林中。",
                character_ids=[char_id],
            ),
        )
        await create_chunk(
            db_with_project, novel_id,
            RagChunkCreate(
                source_type="chapter_text",
                text="城堡大门紧闭。",
                character_ids=[],
            ),
        )
        await db_with_project.flush()

        result = await retrieve(
            db_with_project, novel_id, "艾伦", character_ids=[char_id],
        )
        if result.chunks:
            assert result.chunks[0].character_ids == [char_id]

    @pytest.mark.asyncio
    async def test_find_similar_entities(
        self,
        db_with_project: AsyncSession,
    ) -> None:
        """测试相似实体检索"""
        novel_id = str(uuid.uuid4())
        entities = await find_similar_entities(
            db_with_project, novel_id, [0.1] * 10,
        )
        assert entities == []

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
            text, method="length", chunk_size=50, overlap=10,
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
            db_with_project, novel_id,
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
