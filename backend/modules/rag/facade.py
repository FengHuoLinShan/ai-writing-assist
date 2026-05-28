"""
RAG Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.contracts import RagChunkContract, RagIndexReport, RagResultBundle
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate, RagChunkResponse
from modules.rag.services import ChunkingService, IndexingService, RetrievalService

_repo = RagChunkRepository()
_chunking = ChunkingService()
_retrieval = RetrievalService()
_indexing = IndexingService()


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


async def get_index_status(db: AsyncSession, novel_id: str) -> dict:
    """获取 RAG 索引诊断状态。"""
    nid = uuid.UUID(hex=novel_id)
    total = await _repo.count_by_novel(db, nid)
    embedding_failed_count = await _repo.count_embedding_failed(db, nid)
    warnings = []
    if embedding_failed_count:
        warnings.append(
            f"有 {embedding_failed_count} 个片段 embedding 失败，检索和抽取可能不准确",
        )
    return {
        "total": total,
        "embedding_failed_count": embedding_failed_count,
        "degraded": embedding_failed_count > 0,
        "warnings": warnings,
    }


def _to_chunk_contract(chunk, score: float | None = None) -> RagChunkContract:
    return RagChunkContract(
        id=str(chunk.id),
        novel_id=str(chunk.novel_id),
        source_type=chunk.source_type,
        source_id=str(chunk.source_id) if chunk.source_id else None,
        chapter_index=chunk.chapter_index,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        char_count=chunk.char_count,
        text=chunk.text,
        summary=chunk.summary,
        entity_ids=chunk.entity_ids or [],
        character_ids=chunk.character_ids or [],
        thread_ids=chunk.thread_ids or [],
        visibility=chunk.visibility,
        importance=chunk.importance,
        index_version=chunk.index_version,
        embedding_status=chunk.embedding_status,
        embedding_error=chunk.embedding_error,
        index_warnings=chunk.index_warnings or [],
        score=round(score, 4) if score is not None else None,
    )


async def get_ordered_chapter_chunks(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int | None = None,
) -> list[RagChunkContract]:
    """按章节范围读取有序 RAG chunks，供正文抽取链路使用。"""
    nid = uuid.UUID(hex=novel_id)
    chunks = await _repo.find_by_chapter_range(
        db,
        nid,
        start_chapter,
        end_chapter or start_chapter,
    )
    return [_to_chunk_contract(chunk) for chunk in chunks]


async def retrieve(
    db: AsyncSession,
    novel_id: str,
    query: str,
    *,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
    chapter_index: int | None = None,
    visibility: str | None = None,
    mode: str = "search",
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
        top_k: 返回的最大结果数（最小为 1）

    Returns:
        RagResultBundle — 检索结果
    """
    nid = uuid.UUID(hex=novel_id)
    top_k = max(1, top_k)
    warnings: list[str] = []
    degraded = False
    query_embedding: list[float] | None = None
    if await _repo.has_embeddings(db, nid):
        try:
            from infrastructure.llm.client import LLMClient

            embedding = await LLMClient().generate_embedding(query)
            if (
                isinstance(embedding, list)
                and embedding
                and isinstance(embedding[0], float)
            ):
                query_embedding = embedding  # type: ignore[assignment]
        except Exception as exc:
            degraded = True
            warnings.append(f"embedding 生成失败，本次检索已降级，结果可能不准确: {exc}")

    scored_chunks = await _retrieval.hybrid_search(
        db,
        nid,
        query,
        query_embedding=query_embedding,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        chapter_index=chapter_index,
        visibility=visibility,
        mode=mode,
        top_k=top_k,
    )

    chunk_contracts = [
        _to_chunk_contract(chunk, score)
        for chunk, score in scored_chunks
    ]

    return RagResultBundle(
        chunks=chunk_contracts,
        total=len(scored_chunks),
        query=query,
        warnings=warnings,
        degraded=degraded,
    )


async def index_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> int:
    """索引指定章节的正文到 RAG 库

    由 IndexingService 实现完整编排，facade 仅做类型转换与委托。

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID (UUID hex string)
        chapter_index: 章节索引

    Returns:
        int — 创建的 chunk 数量（无草稿返回 0）
    """
    nid = uuid.UUID(hex=novel_id)
    return await _indexing.index_chapter(db, nid, chapter_index)


async def index_chapter_with_report(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> RagIndexReport:
    """索引指定章节并返回诊断报告。"""
    nid = uuid.UUID(hex=novel_id)
    return await _indexing.index_chapter_with_report(db, nid, chapter_index)


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
