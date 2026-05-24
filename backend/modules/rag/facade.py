"""
RAG Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.contracts import RagChunkContract, RagResultBundle
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate, RagChunkResponse, SimilarEntity
from modules.rag.services import ChunkingService, EmbeddingService, RetrievalService

_repo = RagChunkRepository()
_chunking = ChunkingService()
_embedding = EmbeddingService()
_retrieval = RetrievalService()


async def create_chunk(
    db: AsyncSession,
    novel_id: str,
    data: RagChunkCreate,
) -> RagChunkResponse:
    """创建 RAG 片段

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID (UUID hex string)
        data: 创建请求数据

    Returns:
        RagChunkResponse — 创建的片段
    """
    nid = uuid.UUID(hex=novel_id)
    chunk = await _repo.create(db, nid, data)
    return RagChunkResponse.model_validate(chunk)


async def list_chunks(
    db: AsyncSession,
    novel_id: str,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[RagChunkResponse], int]:
    """获取 RAG 片段列表

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID (UUID hex string)
        skip: 跳过的记录数
        limit: 每页条数

    Returns:
        (items, total) — 片段列表和总数
    """
    nid = uuid.UUID(hex=novel_id)
    items, total = await _repo.get_multi(db, nid, skip=skip, limit=limit)
    return [RagChunkResponse.model_validate(c) for c in items], total


async def retrieve(
    db: AsyncSession,
    novel_id: str,
    query: str,
    *,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
    chapter_index: int | None = None,
    top_k: int = 12,
) -> RagResultBundle:
    """混合检索 RAG 片段

    核心检索接口，用于 context compiler 或其他模块获取相关片段。

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID (UUID hex string)
        query: 检索查询文本
        entity_ids: 限制关联的世界对象 ID 列表
        character_ids: 限制关联的人物 ID 列表
        thread_ids: 限制关联的剧情线 ID 列表
        chapter_index: 限制关联章节索引
        top_k: 返回的最大结果数

    Returns:
        RagResultBundle — 检索结果
    """
    nid = uuid.UUID(hex=novel_id)
    scored_chunks = await _retrieval.hybrid_search(
        db,
        nid,
        query,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        chapter_index=chapter_index,
        top_k=top_k,
    )

    chunk_contracts = [
        RagChunkContract(
            id=str(chunk.id),
            novel_id=str(chunk.novel_id),
            source_type=chunk.source_type,
            source_id=str(chunk.source_id) if chunk.source_id else None,
            chapter_index=chunk.chapter_index,
            text=chunk.text,
            summary=chunk.summary,
            entity_ids=chunk.entity_ids or [],
            character_ids=chunk.character_ids or [],
            thread_ids=chunk.thread_ids or [],
            visibility=chunk.visibility,
            importance=chunk.importance,
            score=round(score, 4),
        )
        for chunk, score in scored_chunks
    ]

    return RagResultBundle(
        chunks=chunk_contracts,
        total=len(scored_chunks),
        query=query,
    )


async def find_similar_entities(
    db: AsyncSession,
    novel_id: str,
    candidate_embedding: list[float],
    entity_type: str | None = None,
    top_k: int = 8,
) -> list[SimilarEntity]:
    """查找语义相似的实体（预留接口）

    生产环境中通过 pgvector 查询 world_entities 表的 embedding 列。
    当前返回空列表，因为内存 SQLite 不支持 pgvector。

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID (UUID hex string)
        candidate_embedding: 候选对象的 embedding 向量
        entity_type: 可选的实体类型过滤
        top_k: 返回的最大结果数

    Returns:
        list[SimilarEntity] — 相似实体列表
    """
    nid = uuid.UUID(hex=novel_id)
    return await _retrieval.find_similar_entities(
        db,
        nid,
        candidate_embedding,
        entity_type=entity_type,
        top_k=top_k,
    )


async def split_text_into_chunks(
    text: str,
    method: str = "paragraph",
    **kwargs: object,
) -> list[str]:
    """将文本分割为片段

    供其他模块（如 import_text 流程）使用。

    Args:
        text: 要分割的文本
        method: 分割方法（paragraph / length）
        **kwargs: 传递给分割方法的参数

    Returns:
        list[str] — 分割后的文本片段列表
    """
    if method == "paragraph":
        max_length = kwargs.get("max_length")
        return _chunking.split_by_paragraphs(text, max_length=max_length)
    elif method == "length":
        chunk_size = int(kwargs.get("chunk_size", 1000))
        overlap = int(kwargs.get("overlap", 100))
        return _chunking.split_by_length(text, chunk_size=chunk_size, overlap=overlap)
    else:
        return [text]
