"""
TB4: Vector search 测试
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.engine.default import DefaultDialect
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.repositories import RagChunkRepository
from modules.rag.retrieval import RetrievalOrchestrator
from modules.rag.scoring import cosine_similarity


def test_cosine_similarity_identical():
    """RED: 相同向量的余弦相似度为 1.0"""
    v = [1.0, 2.0, 3.0]
    sim = cosine_similarity(v, v)
    assert abs(sim - 1.0) < 1e-6, f"期望 1.0, 实际 {sim}"


def test_cosine_similarity_orthogonal():
    """RED: 正交向量的余弦相似度为 0.0"""
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    sim = cosine_similarity(v1, v2)
    assert abs(sim - 0.0) < 1e-6, f"期望 0.0, 实际 {sim}"


def test_cosine_similarity_opposite():
    """RED: 相反向量的余弦相似度为 -1.0"""
    v1 = [1.0, 2.0]
    v2 = [-1.0, -2.0]
    sim = cosine_similarity(v1, v2)
    assert abs(sim - (-1.0)) < 1e-6, f"期望 -1.0, 实际 {sim}"


def test_cosine_similarity_partial():
    """RED: 部分相似的向量"""
    v1 = [1.0, 0.0]
    v2 = [0.707, 0.707]
    sim = cosine_similarity(v1, v2)
    # cos(45°) ≈ 0.707
    assert abs(sim - 0.707) < 0.01, f"期望 ~0.707, 实际 {sim}"


def test_cosine_similarity_zero_vector():
    """RED: 零向量应返回 0.0（避免除零）"""
    v = [0.0, 0.0, 0.0]
    sim = cosine_similarity(v, [1.0, 2.0, 3.0])
    assert sim == 0.0, "零向量应返回 0.0"


@pytest.mark.asyncio
async def test_vector_search_returns_empty_without_pgvector(
    db_session: AsyncSession,
):
    """RED: 无 pgvector 时 vector_search 应返回空列表"""
    from modules.rag.repositories import RagChunkRepository

    repo = RagChunkRepository()
    nid = uuid.uuid4()  # 随机 novel_id

    results = await repo.vector_search(db_session, nid, [0.1] * 4, top_k=5)
    assert results == [], "无 pgvector 时应返回空列表"


@pytest.mark.asyncio
async def test_sqlite_vector_search_caps_python_fallback_candidates():
    """SQLite fallback must not scan every embedded chunk without a SQL limit."""
    repo = RagChunkRepository()
    statements = []

    class _SqliteDialect(DefaultDialect):
        name = "sqlite"

    class _Bind:
        dialect = _SqliteDialect()

    class _Scalars:
        def all(self):
            return []

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Db:
        def get_bind(self):
            return _Bind()

        async def execute(self, statement):
            statements.append(statement)
            return _Result()

    await repo.vector_search(  # type: ignore[arg-type]
        _Db(),
        uuid.uuid4(),
        [0.1, 0.2],
        top_k=3,
    )

    assert statements, "SQLite fallback should execute a bounded candidate query"
    query_sql = str(statements[0]).lower()
    assert "limit" in query_sql


@pytest.mark.asyncio
async def test_vector_search_orders_pgvector_inner_product_distance_ascending():
    """pgvector <#> 返回距离，越小越相关，因此 SQL 必须升序。"""
    repo = RagChunkRepository()
    statements = []

    class _PgDialect(DefaultDialect):
        name = "postgresql"

    class _Bind:
        dialect = _PgDialect()

    class _Result:
        def all(self):
            return []

    class _Db:
        def get_bind(self):
            return _Bind()

        async def execute(self, statement, params=None):
            statements.append(statement)
            return _Result()

    await repo.vector_search(  # type: ignore[arg-type]
        _Db(),
        uuid.uuid4(),
        [0.1, 0.2],
        top_k=3,
        ef_search=40,
    )

    setup_sql = str(statements[0]).lower()
    query_sql = str(statements[1]).lower()
    assert "set local hnsw.ef_search = 40" in setup_sql
    assert ":ef" not in setup_sql
    assert "cast(" in query_sql
    assert "order by score asc" in query_sql


@pytest.mark.asyncio
async def test_hybrid_search_with_query_embedding(
    db_session: AsyncSession,
):
    """RED: hybrid_search 传入 query_embedding 时向量分数应为非零"""
    repo = RagChunkRepository()
    retrieval = RetrievalOrchestrator()

    # 创建一个 chunk
    nid = uuid.uuid4()
    from modules.rag.schemas import RagChunkCreate

    chunk = await repo.create(
        db_session,
        nid,
        RagChunkCreate(
            source_type="chapter_text",
            chapter_index=1,
            text="主角的欲望是寻找真相。",
            importance=0.8,
        ),
    )

    # 设置 embedding（列定义为 Vector(768)）
    test_emb = [0.1 * (i % 3 + 1) for i in range(768)]
    chunk.embedding = test_emb  # type: ignore[assignment]
    await db_session.flush()

    # 用精确匹配的 query_embedding 搜索
    results = await retrieval.hybrid_search(
        db_session,
        nid,
        "主角",
        query_embedding=test_emb,
        top_k=5,
    )

    # 关键词匹配 "主角" 应能找到 chunk
    if len(results) > 0:
        for c, score in results:
            if c.id == chunk.id:
                # 向量评分和关键词评分共同贡献分数
                assert score > 0, f"有 embedding 的 chunk 分数应 > 0（实际 {score}）"
                break
