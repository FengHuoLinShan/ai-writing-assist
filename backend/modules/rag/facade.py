"""
RAG Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from modules.rag.contracts import RagChunkContract, RagResultBundle
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate, RagChunkResponse
from modules.rag.services import ChunkingService, RetrievalService

_repo = RagChunkRepository()
_chunking = ChunkingService()
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
    visibility: str | None = None,
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
    scored_chunks = await _retrieval.hybrid_search(
        db,
        nid,
        query,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        chapter_index=chapter_index,
        visibility=visibility,
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


async def index_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> int:
    """索引指定章节的正文到 RAG 库

    1. 读取该章节最新草稿
    2. 按段落分割为 chunk
    3. 文本匹配已有角色名，标记 character_ids
    4. 删除该章节旧 chunk（替换）
    5. 创建新 chunk

    Args:
        db: 数据库 session
        novel_id: 小说项目 ID (UUID hex string)
        chapter_index: 章节索引

    Returns:
        int — 创建的 chunk 数量（无草稿返回 0）
    """
    from modules.writing.facade import get_latest_draft_for_chapter

    draft = await get_latest_draft_for_chapter(db, novel_id, chapter_index)
    if not draft or not draft.content:
        return 0

    # 1. 分割为段落
    paragraphs = _chunking.split_by_paragraphs(draft.content)
    if not paragraphs:
        return 0

    # 2. 加载所有角色名（用于文本匹配）
    from modules.character.facade import list_characters as _list_chars

    chars_list, _ = await _list_chars(db, novel_id, limit=999)
    char_name_map: dict[str, str] = {}
    for c in chars_list:
        char_name_map[c.name] = str(c.id)

    nid = uuid.UUID(hex=novel_id)

    # 3. 删除旧 chunk
    await _repo.delete_by_chapter(db, nid, "chapter_text", chapter_index)

    # 4. 创建新 chunk（记录 ID 和文本用于批量 embedding）
    created = 0
    created_chunks: list[tuple[uuid.UUID, str]] = []
    for para in paragraphs:
        matched_char_ids: list[str] = []
        for name, cid in char_name_map.items():
            if name in para:
                matched_char_ids.append(cid)

        chunk_data = RagChunkCreate(
            source_type="chapter_text",
            chapter_index=chapter_index,
            text=para,
            character_ids=matched_char_ids,
            visibility="author_only",
            importance=0.5,
            meta={"chapter_index": chapter_index},
        )
        chunk = await _repo.create(db, nid, chunk_data)
        created_chunks.append((chunk.id, para))
        created += 1

    await db.flush()

    # 5. 批量生成 embedding
    if created_chunks:
        try:
            from infrastructure.llm.client import LLMClient

            llm = LLMClient()
            texts = [t for _, t in created_chunks]
            embeddings = await llm.generate_embedding(texts)
            if isinstance(embeddings, list) and len(embeddings) == len(created_chunks):
                for (chunk_id, _), emb in zip(created_chunks, embeddings):
                    await _repo.update_embedding(db, chunk_id, emb)
                await db.flush()
        except Exception as exc:
            logger.warning("Failed to generate embeddings for chapter %d: %s", chapter_index, exc)

    return created


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
