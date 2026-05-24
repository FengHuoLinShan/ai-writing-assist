"""
Writing 数据访问层

封装 writing_drafts 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.models import WritingDraft
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate


class WritingDraftRepository:
    """正文草稿数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
        chapter_card_id: uuid.UUID | None = None,
    ) -> WritingDraft:
        """创建新草稿

        自动确定下一个版本号：查询该章节当前最大版本号并 +1。
        """
        novel_id = uuid.UUID(hex=data.novel_id)
        cid: uuid.UUID | None = None
        if data.chapter_card_id is not None:
            cid = uuid.UUID(hex=data.chapter_card_id)
        elif chapter_card_id is not None:
            cid = chapter_card_id

        # 获取当前最大版本号
        latest = await self._get_latest_version(
            db, novel_id, data.chapter_index,
        )
        next_version = (latest.version_number + 1) if latest else 1

        draft = WritingDraft(
            novel_id=novel_id,
            chapter_index=data.chapter_index,
            chapter_card_id=cid,
            title=data.title,
            content=data.content,
            version_number=next_version,
            status="draft",
        )
        db.add(draft)
        await db.flush()
        return draft

    async def get(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
    ) -> WritingDraft | None:
        """根据 ID 获取草稿"""
        stmt = select(WritingDraft).where(WritingDraft.id == draft_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> WritingDraft | None:
        """获取指定章节的最新草稿（版本号最大）"""
        stmt = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_version_history(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> Sequence[WritingDraft]:
        """获取指定章节的所有版本（按版本号降序）"""
        stmt = (
            select(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
            )
            .order_by(WritingDraft.version_number.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def update(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
        data: WritingDraftUpdate,
    ) -> WritingDraft | None:
        """更新草稿，返回更新后的对象（不存在返回 None）"""
        draft = await self.get(db, draft_id)
        if draft is None:
            return None

        update_values: dict[str, object] = {}
        for field in ("title", "content", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            stmt = (
                update(WritingDraft)
                .where(WritingDraft.id == draft_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            draft = await self.get(db, draft_id)

        return draft

    async def delete(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
    ) -> bool:
        """删除草稿，返回是否成功删除"""
        stmt = delete(WritingDraft).where(WritingDraft.id == draft_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    # ============================================================
    # 内部方法
    # ============================================================

    async def _get_latest_version(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> WritingDraft | None:
        """获取指定章节的最新版本草稿"""
        return await self.get_latest_by_chapter(db, novel_id, chapter_index)
