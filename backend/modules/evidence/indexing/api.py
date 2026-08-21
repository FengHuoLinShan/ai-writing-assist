"""
RAG API 路由

提供 RAG 片段的 CRUD 和检索 API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from infrastructure.tasks.enqueuer import enqueue_task
from modules.evidence.indexing.facade import (
    create_chunk,
    get_index_status,
    get_metrics_status,
    list_chunks,
    prewarm_embedding_runtime,
    retrieve,
    split_text_into_chunks,
)
from modules.evidence.indexing.schemas import (
    RagChunkCreate,
    RagChunkResponse,
    RagQuery,
    RagRebuildRequest,
    RagResult,
    RagRetryEmbeddingsRequest,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/rag", tags=["rag"])


async def _require_active_project(db: DbSession, novel_id: str) -> None:
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)


@router.post("/chunks", response_model=RagChunkResponse, status_code=201)
async def create_rag_chunk(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    data: RagChunkCreate,
) -> RagChunkResponse:
    """创建 RAG 片段

    将文本片段及其元信息存入 rag_chunks 表。
    """
    await _require_active_project(db, novel_id)
    return await create_chunk(db, novel_id, data)


@router.get("/chunks", response_model=dict)
async def list_rag_chunks(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> dict:
    """获取 RAG 片段列表"""
    await _require_active_project(db, novel_id)
    items, total = await list_chunks(db, novel_id, skip=skip, limit=limit)
    status = await get_index_status(db, novel_id)
    return {
        "items": items,
        "total": total,
        **status,
    }


@router.post("/retrieve", response_model=RagResult)
async def retrieve_chunks(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    query: RagQuery,
) -> RagResult:
    """混合检索 RAG 片段

    组合关键词匹配 + 关系匹配 + 重要性评分进行混合检索排序。
    """
    await _require_active_project(db, novel_id)
    result = await retrieve(
        db,
        novel_id,
        query.query,
        content_mode=query.content_mode,
        entity_ids=query.entity_ids,
        character_ids=query.character_ids,
        thread_ids=query.thread_ids,
        chapter_index=query.chapter_index,
        visible_until_chapter=query.visible_until_chapter,
        scene_id=query.scene_id,
        strict_scene_filter=query.strict_scene_filter,
        visibility=query.visibility,
        mode=query.mode,
        top_k=query.top_k,
        retrieval_purpose="manual_search",
    )

    # 转为 API 响应格式
    chunks = [
        RagChunkResponse(
            id=c.id,
            novel_id=c.novel_id,
            source_type=c.source_type,
            source_id=c.source_id,
            content_mode=c.content_mode,
            source_content_hash=c.source_content_hash,
            chapter_index=c.chapter_index,
            chunk_index=c.chunk_index,
            start_offset=c.start_offset,
            end_offset=c.end_offset,
            char_count=c.char_count,
            text=c.text,
            summary=c.summary,
            entity_ids=c.entity_ids,
            character_ids=c.character_ids,
            thread_ids=c.thread_ids,
            scene_id=c.scene_id,
            scene_span_id=c.scene_span_id,
            visibility=c.visibility,
            importance=c.importance,
            index_version=c.index_version,
            embedding_status=c.embedding_status,
            embedding_error=c.embedding_error,
            index_warnings=c.index_warnings,
            score=c.score,
        )
        for c in result.chunks
    ]

    return RagResult(
        chunks=chunks,
        total=result.total,
        query=result.query,
        warnings=result.warnings,
        degraded=result.degraded,
    )


@router.get("/metrics", response_model=dict)
async def get_rag_metrics() -> dict:
    """获取 RAG 检索运行时指标。"""
    return await get_metrics_status()


@router.post("/prewarm", response_model=dict)
async def prewarm_rag_embedding() -> dict:
    """预热 RAG embedding worker。"""
    try:
        return await prewarm_embedding_runtime()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="embedding worker prewarm failed",
        ) from exc


@router.post("/rebuild", response_model=dict)
async def rebuild_rag_index(
    db: DbSession,
    request: RagRebuildRequest,
) -> dict:
    """按章节范围重建 RAG 索引

    入队异步任务 `rag_reindex_novel`，由 worker 逐章重建。
    """
    await _require_active_project(db, request.novel_id)
    task_id = enqueue_task(
        db,
        "rag_reindex_novel",
        meta={
            "novel_id": request.novel_id,
            "start_chapter": request.start_chapter,
            "end_chapter": request.end_chapter,
            "content_mode": request.content_mode,
        },
        novel_id=request.novel_id,
    )
    return {"task_id": task_id, "status": "pending"}


@router.post("/retry-embeddings", response_model=dict)
async def retry_embeddings(
    db: DbSession,
    request: RagRetryEmbeddingsRequest,
) -> dict:
    """提交失败 embedding 重试任务。"""
    await _require_active_project(db, request.novel_id)
    task_id = enqueue_task(
        db,
        "rag_retry_embeddings",
        meta={
            "novel_id": request.novel_id,
            "start_chapter": request.start_chapter,
            "end_chapter": request.end_chapter,
            "statuses": list(request.statuses),
        },
        novel_id=request.novel_id,
    )
    return {"task_id": task_id, "status": "pending"}


@router.post("/chunks/split", response_model=dict)
async def split_text(
    text: Annotated[
        str,
        Query(max_length=200_000, description="要分割的文本"),
    ],
    method: Annotated[
        str,
        Query(description="分割方法 (paragraph / length)"),
    ] = "paragraph",
    chunk_size: Annotated[
        int,
        Query(ge=100, le=100_000, description="chunk 大小"),
    ] = 1000,
    overlap: Annotated[
        int,
        Query(ge=0, le=99_999, description="重叠字符数"),
    ] = 100,
) -> dict:
    """分割文本为 RAG 片段（工具接口，不写入数据库）"""
    if overlap >= chunk_size:
        raise HTTPException(
            status_code=422,
            detail="overlap must be smaller than chunk_size",
        )
    chunks = await split_text_into_chunks(
        text,
        method=method,
        chunk_size=chunk_size,
        overlap=overlap,
    )

    return {
        "chunks": chunks,
        "total": len(chunks),
        "method": method,
    }
