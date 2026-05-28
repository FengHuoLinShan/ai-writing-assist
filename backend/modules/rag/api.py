"""
RAG API 路由

提供 RAG 片段的 CRUD 和检索 API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.rag.facade import (
    create_chunk,
    get_index_status,
    list_chunks,
    retrieve,
)
from modules.rag.schemas import (
    RagChunkCreate,
    RagChunkResponse,
    RagQuery,
    RagResult,
)
from modules.rag.services import ChunkingService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/rag", tags=["rag"])
_chunking = ChunkingService()


@router.post("/chunks", response_model=RagChunkResponse, status_code=201)
async def create_rag_chunk(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID (UUID hex string)"),
    data: RagChunkCreate = None,  # noqa: ANN401 — FastAPI body
) -> RagChunkResponse:
    """创建 RAG 片段

    将文本片段及其元信息存入 rag_chunks 表。
    """
    return await create_chunk(db, novel_id, data)


@router.get("/chunks", response_model=dict)
async def list_rag_chunks(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID (UUID hex string)"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> dict:
    """获取 RAG 片段列表"""
    items, total = await list_chunks(db, novel_id, skip=skip, limit=limit)
    status = await get_index_status(db, novel_id)
    return {"items": items, "total": total, **status}


@router.post("/retrieve", response_model=RagResult)
async def retrieve_chunks(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID (UUID hex string)"),
    query: RagQuery = None,  # noqa: ANN401 — FastAPI body
) -> RagResult:
    """混合检索 RAG 片段

    组合关键词匹配 + 关系匹配 + 重要性评分进行混合检索排序。
    """
    result = await retrieve(
        db,
        novel_id,
        query.query,
        entity_ids=query.entity_ids,
        character_ids=query.character_ids,
        thread_ids=query.thread_ids,
        chapter_index=query.chapter_index,
        visibility=query.visibility,
        mode=query.mode,
        top_k=query.top_k,
    )

    # 转为 API 响应格式
    chunks = [
        RagChunkResponse(
            id=c.id,
            novel_id=c.novel_id,
            source_type=c.source_type,
            source_id=c.source_id,
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


@router.post("/chunks/split", response_model=dict)
async def split_text(
    text: str = Query(..., description="要分割的文本"),
    method: str = Query(
        default="paragraph",
        description="分割方法 (paragraph / length)",
    ),
    chunk_size: int = Query(default=1000, ge=100, description="chunk 大小"),
    overlap: int = Query(default=100, ge=0, description="重叠字符数"),
) -> dict:
    """分割文本为 RAG 片段（工具接口，不写入数据库）"""
    chunks: list[str] = []

    if method == "paragraph":
        chunks = _chunking.split_by_paragraphs(text)
    elif method == "length":
        chunks = _chunking.split_by_length(text, chunk_size=chunk_size, overlap=overlap)
    else:
        chunks = [text]

    return {
        "chunks": chunks,
        "total": len(chunks),
        "method": method,
    }
