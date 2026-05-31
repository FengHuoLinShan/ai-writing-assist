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


def _is_rerank_enabled(mode: str) -> bool:
    """检查是否启用 LLM 重排序。extraction 模式且配置开启时生效。"""
    from core.config import get_settings

    if mode not in ("extraction",):
        return False
    return get_settings().reranker_enabled


def _deduplicate_by_embedding(
    scored_chunks: list[tuple],
    threshold: float = 0.9,
) -> list[tuple]:
    """对检索结果进行语义去重。

    利用 chunk 的 embedding 计算余弦相似度，相似度 > threshold 的两个 chunk
    仅保留 char_count 更大者。无 embedding 时跳过。
    """
    if len(scored_chunks) <= 1:
        return scored_chunks

    keep: list[tuple] = []
    removed_indices: set[int] = set()

    for i, (chunk_a, score_a) in enumerate(scored_chunks):
        if i in removed_indices:
            continue
        keep.append((chunk_a, score_a))

        emb_a = chunk_a.embedding
        if emb_a is None:
            continue
        if not isinstance(emb_a, list):
            continue

        for j, (chunk_b, _score_b) in enumerate(scored_chunks):
            if j <= i or j in removed_indices:
                continue

            emb_b = chunk_b.embedding
            if emb_b is None:
                continue
            if not isinstance(emb_b, list):
                continue
            if len(emb_a) != len(emb_b):
                continue

            sim = _retrieval._cosine_similarity(emb_a, emb_b)
            if sim > threshold:
                # 保留 char_count 更高的 chunk
                count_a = chunk_a.char_count or 0
                count_b = chunk_b.char_count or 0
                if count_a >= count_b:
                    removed_indices.add(j)
                else:
                    # chunk_b 更好，替换
                    keep.pop()
                    keep.append((chunk_b, _score_b))
                    removed_indices.add(i)
                    break

    return keep


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
    from core.config import get_settings

    nid = uuid.UUID(hex=novel_id)
    total = await _repo.count_by_novel(db, nid)
    embedding_failed_count = await _repo.count_embedding_failed(db, nid)
    pending_vectorization = await _repo.count_pending_vectorization(db, nid)
    settings = get_settings()

    warnings = []
    if pending_vectorization:
        warnings.append(
            f"有 {pending_vectorization} 个片段待重新向量化（维度迁移后），检索可能暂时不准确",
        )
    if embedding_failed_count:
        warnings.append(
            f"有 {embedding_failed_count} 个片段 embedding 失败，检索和抽取可能不准确",
        )

    return {
        "total": total,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
        "embedding_failed_count": embedding_failed_count,
        "pending_vectorization": pending_vectorization,
        "degraded": embedding_failed_count > 0 or pending_vectorization > 0,
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
        meta=chunk.meta or {},
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
    reference_chapter_index: int | None = None,
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
    import time as _time

    _t0 = _time.monotonic()
    nid = uuid.UUID(hex=novel_id)
    top_k = max(1, top_k)
    warnings: list[str] = []
    degraded = False
    query_embedding: list[float] | None = None

    # 尝试生成查询 embedding（带熔断保护）
    if await _repo.has_embeddings(db, nid):
        from modules.rag.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        if cb.allow_request():
            try:
                from infrastructure.llm.client import LLMClient

                embedding = await LLMClient().generate_embedding(query, is_query=True)
                if (
                    isinstance(embedding, list)
                    and embedding
                    and isinstance(embedding[0], float)
                ):
                    query_embedding = embedding  # type: ignore[assignment]
                    cb.record_success()
                else:
                    cb.record_failure()
                    degraded = True
                    warnings.append("embedding 返回格式异常，已降级")
            except Exception as exc:
                cb.record_failure()
                degraded = True
                warnings.append(f"embedding 生成失败，本次检索已降级，结果可能不准确: {exc}")
        else:
            degraded = True
            warnings.append("BGE 服务熔断中，本次检索已降级为关键词匹配")

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
        reference_chapter_index=reference_chapter_index,
    )

    # 语义去重：移除余弦相似度 > 0.9 的冗余 chunk，保留 char_count 更大者
    deduped_chunks = _deduplicate_by_embedding(scored_chunks, threshold=0.9)

    # LLM 重排序（可选，仅 extraction 模式或显式开启）
    rerank_enabled = _is_rerank_enabled(mode)
    if rerank_enabled and len(deduped_chunks) > top_k:
        try:
            from modules.rag.reranker import rerank_results

            deduped_chunks = await rerank_results(
                query, deduped_chunks, top_k=top_k,
            )
        except Exception as exc:
            warnings.append(f"重排序失败，使用原始排序: {exc}")

    chunk_contracts = [
        _to_chunk_contract(chunk, score)
        for chunk, score in deduped_chunks
    ]

    # 记录检索指标
    _latency_ms = (_time.monotonic() - _t0) * 1000
    from modules.rag.metrics import get_metrics

    get_metrics().record(
        latency_ms=_latency_ms,
        degraded=degraded,
        empty=len(chunk_contracts) == 0,
    )

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


async def index_chapter_incremental(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    old_content: str,
    new_content: str,
) -> RagIndexReport:
    """增量索引章节，仅重建变更区域。

    Args:
        old_content: 上次索引时的章节原文
        new_content: 当前的章节原文
    """
    nid = uuid.UUID(hex=novel_id)
    return await _indexing.index_chapter_incremental(
        db, nid, chapter_index, old_content, new_content,
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
