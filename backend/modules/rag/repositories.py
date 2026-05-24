"""
RAG 数据访问层

封装 rag_chunks 表的所有数据库操作和多种检索方式。
提供精确检索、关键词检索和向量检索（预留接口）。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.models import RagChunk
from modules.rag.schemas import RagChunkCreate
from shared.constants import DEFAULT_PAGE_SIZE


class RagChunkRepository:
    """RAG 片段数据访问"""

    # ============================================================
    # 基础 CRUD
    # ============================================================

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: RagChunkCreate,
    ) -> RagChunk:
        """创建 RAG 片段"""
        chunk = RagChunk(
            novel_id=novel_id,
            source_type=data.source_type,
            source_id=uuid.UUID(hex=data.source_id) if data.source_id else None,
            chapter_index=data.chapter_index,
            text=data.text,
            summary=data.summary,
            entity_ids=data.entity_ids or [],
            character_ids=data.character_ids or [],
            thread_ids=data.thread_ids or [],
            visibility=data.visibility or "author_only",
            importance=data.importance if data.importance is not None else 0.5,
            meta=data.meta or {},
        )
        db.add(chunk)
        await db.flush()
        return chunk

    async def get(
        self,
        db: AsyncSession,
        chunk_id: uuid.UUID,
    ) -> RagChunk | None:
        """根据 ID 获取片段"""
        stmt = select(RagChunk).where(RagChunk.id == chunk_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[RagChunk], int]:
        """获取片段列表（分页），返回 (items, total)"""
        # 获取总数
        count_stmt = (
            select(func.count(RagChunk.id))
            .where(RagChunk.novel_id == novel_id)
        )
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()

        # 获取分页数据
        stmt = (
            select(RagChunk)
            .where(RagChunk.novel_id == novel_id)
            .offset(skip)
            .limit(limit)
            .order_by(RagChunk.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[RagChunk] = result.scalars().all()
        return list(items), total

    async def delete(
        self,
        db: AsyncSession,
        chunk_id: uuid.UUID,
    ) -> bool:
        """删除片段，返回是否成功删除"""
        stmt = delete(RagChunk).where(RagChunk.id == chunk_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def delete_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """删除小说项目的所有片段，返回删除数"""
        stmt = delete(RagChunk).where(RagChunk.novel_id == novel_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    # ============================================================
    # 精确检索
    # ============================================================

    async def find_by_source(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_type: str,
        source_id: uuid.UUID | None = None,
    ) -> list[RagChunk]:
        """按来源类型和 ID 精确检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.source_type == source_type,
        ]
        if source_id is not None:
            conditions.append(RagChunk.source_id == source_id)

        stmt = select(RagChunk).where(and_(*conditions))
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: str,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按关联的世界对象 ID 检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.entity_ids.contains([entity_id]),
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(RagChunk.importance.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: str,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按关联的人物 ID 检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.character_ids.contains([character_id]),
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(RagChunk.importance.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_thread(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        thread_id: str,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按关联的剧情线 ID 检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.thread_ids.contains([thread_id]),
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(RagChunk.importance.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def find_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        visibility: str | None = None,
    ) -> list[RagChunk]:
        """按章节索引检索"""
        conditions = [
            RagChunk.novel_id == novel_id,
            RagChunk.chapter_index == chapter_index,
        ]
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .order_by(RagChunk.importance.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # 关键词检索（文本匹配）
    # ============================================================

    async def keyword_search(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query: str,
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        visibility: str | None = None,
        limit: int = 20,
    ) -> list[RagChunk]:
        """关键词检索 — 使用简单的 SQL LIKE 文本匹配

        不依赖 PostgreSQL full-text search，保持 SQLite 兼容。
        返回按匹配度粗略排序的结果。
        """
        conditions = [RagChunk.novel_id == novel_id]

        # 构建关键词条件（OR 逻辑，匹配任意关键词即返回）
        query_terms = [q.strip() for q in query.split() if q.strip()]
        if query_terms:
            keyword_conditions = []
            for term in query_terms:
                pattern = f"%{term}%"
                keyword_conditions.append(RagChunk.text.ilike(pattern))
            conditions.append(or_(*keyword_conditions))

        # metadata 过滤
        if entity_ids:
            conditions.append(RagChunk.entity_ids.contains(entity_ids))
        if character_ids:
            conditions.append(RagChunk.character_ids.contains(character_ids))
        if thread_ids:
            conditions.append(RagChunk.thread_ids.contains(thread_ids))
        if chapter_index is not None:
            conditions.append(RagChunk.chapter_index == chapter_index)
        if visibility is not None:
            conditions.append(RagChunk.visibility == visibility)

        stmt = (
            select(RagChunk)
            .where(and_(*conditions))
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # ============================================================
    # 向量检索（预留接口）
    # ============================================================

    async def vector_search(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        embedding: list[float],
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        top_k: int = 12,
    ) -> list[RagChunk]:
        """向量检索（预留接口）

        此接口在使用 pgvector 的生产环境中启用。
        当前实现返回空列表，因为内存 SQLite 不支持 pgvector。
        当检测到 pgvector 可用时，应使用:
          - embeddingvector 类型列
          - cosine 距离: embedding <=> :query_embedding
          - ORDER BY embedding <=> :query_embedding
          - LIMIT top_k
        """
        # 预留：生产环境中替换为 pgvector 余弦距离查询
        # SELECT id, 1 - (embedding <=> :query_embedding) AS similarity
        # FROM rag_chunks
        # WHERE novel_id = :novel_id
        #   AND embedding IS NOT NULL
        # ORDER BY embedding <=> :query_embedding
        # LIMIT :top_k
        return []

    # ============================================================
    # 统计
    # ============================================================

    async def count_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """统计小说项目的片段总数"""
        stmt = (
            select(func.count(RagChunk.id))
            .where(RagChunk.novel_id == novel_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one()
