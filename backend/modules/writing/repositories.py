"""
Writing 数据访问层

封装 writing_drafts 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.models import WritingDraft
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate


class WritingDraftRepository:
    """正文草稿数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: WritingDraftCreate,
    ) -> WritingDraft:
        """创建新草稿版本

        SELECT MAX + 唯一约束兜底实现原子版本号递增。
        """
        novel_id = uuid.UUID(hex=data.novel_id)

        next_version = await self._next_version_number(
            db,
            novel_id,
            data.chapter_index,
        )

        draft = WritingDraft(
            novel_id=novel_id,
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content,
            version_number=next_version,
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
        """暂存草稿（原地更新，不递增版本号）。返回更新后的对象。"""
        draft = await self.get(db, draft_id)
        if draft is None:
            return None

        update_values: dict[str, object] = {}
        for field in ("title", "content"):
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
    ) -> WritingDraft | None:
        """删除单个版本。返回被删除的 draft（用于后续重排版本号）。"""
        draft = await self.get(db, draft_id)
        if draft is None:
            return None

        # 删除该版本
        del_stmt = delete(WritingDraft).where(WritingDraft.id == draft_id)
        await db.execute(del_stmt)
        await db.flush()
        return draft

    async def renumber_versions_after_delete(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        deleted_version: int,
    ) -> None:
        """删除后重排高于被删版本的版本号（-1）。"""
        renumber_stmt = (
            update(WritingDraft)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
                WritingDraft.version_number > deleted_version,
            )
            .values(version_number=WritingDraft.version_number - 1)
        )
        await db.execute(renumber_stmt)
        await db.flush()

    async def count_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """返回某章版本总数"""
        stmt = select(func.count(WritingDraft.id)).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def delete_all_versions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """删除某章全部版本。返回删除的版本数。"""
        stmt = delete(WritingDraft).where(
            WritingDraft.novel_id == novel_id,
            WritingDraft.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0

    # ============================================================
    # 内部方法
    # ============================================================

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[int]:
        """列出该小说所有有草稿的章节索引（去重、升序）"""
        stmt = (
            select(WritingDraft.chapter_index)
            .where(WritingDraft.novel_id == novel_id)
            .distinct()
            .order_by(WritingDraft.chapter_index)
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]

    async def update_latest_content(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        title: str | None,
        content: str,
    ) -> WritingDraft:
        draft = await self.get_latest_by_chapter(db, novel_id, chapter_index)
        if draft is None:
            raise ValueError(f"No draft found for chapter {chapter_index}")
        draft.title = title
        draft.content = content
        db.add(draft)
        await db.flush()
        return draft

    async def shift_chapter_indices_from(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_index: int,
    ) -> None:
        stmt = (
            select(WritingDraft.chapter_index)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index >= start_index,
            )
            .distinct()
            .order_by(WritingDraft.chapter_index.desc())
        )
        result = await db.execute(stmt)
        indices = [row[0] for row in result.all()]
        for idx in indices:
            await db.execute(
                update(WritingDraft)
                .where(
                    WritingDraft.novel_id == novel_id,
                    WritingDraft.chapter_index == idx,
                )
                .values(chapter_index=idx + 1)
            )
        await db.flush()

    async def _next_version_number(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """获取下一个版本号 = max(当前版本号) + 1"""
        stmt = (
            select(WritingDraft.version_number)
            .where(
                WritingDraft.novel_id == novel_id,
                WritingDraft.chapter_index == chapter_index,
            )
            .order_by(WritingDraft.version_number.desc())
            .limit(1)
            .with_for_update()
        )
        result = await db.execute(stmt)
        max_ver = result.scalar_one_or_none() or 0
        return int(max_ver) + 1
