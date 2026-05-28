"""
Timeline 数据访问层

封装 timeline_events 表的所有数据库操作。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.timeline.models import TimelineEvent
from modules.timeline.schemas import TimelineEventCreate, TimelineEventUpdate
from shared.constants import DEFAULT_PAGE_SIZE


class TimelineEventRepository:
    """时间线事件数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: TimelineEventCreate,
    ) -> TimelineEvent:
        """创建新的时间线事件"""
        event = TimelineEvent(
            novel_id=novel_id,
            title=data.title,
            summary=data.summary,
            order_index=data.order_index,
            chapter_index=data.chapter_index,
            event_type=data.event_type,
            related_character_ids=data.related_character_ids or [],
            related_entity_ids=data.related_entity_ids or [],
            related_thread_ids=data.related_thread_ids or [],
            related_location_ids=data.related_location_ids or [],
            geo_effects=data.geo_effects or [],
            visibility=data.visibility or "author_only",
            known_by_character_ids=data.known_by_character_ids or [],
            status=data.status or "candidate",
        )
        db.add(event)
        await db.flush()
        return event

    async def get(
        self,
        db: AsyncSession,
        event_id: uuid.UUID,
    ) -> TimelineEvent | None:
        """根据 ID 获取时间线事件"""
        stmt = select(TimelineEvent).where(TimelineEvent.id == event_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        status: str | None = None,
        event_type: str | None = None,
        before_chapter_index: int | None = None,
        character_id: str | None = None,
        entity_ids: list[str] | None = None,
    ) -> tuple[list[TimelineEvent], int]:
        """获取时间线事件列表（支持过滤和分页）

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            skip: 跳过数量
            limit: 最大返回条数
            status: 按状态过滤
            event_type: 按事件类型过滤
            before_chapter_index: 只返回该章节之前的事件
            character_id: 按关联角色过滤（JSONB contains）
            entity_ids: 按关联实体过滤（JSONB overlaps）

        Returns:
            (items, total)
        """
        conditions = [TimelineEvent.novel_id == novel_id]

        if status:
            conditions.append(TimelineEvent.status == status)
        if event_type:
            conditions.append(TimelineEvent.event_type == event_type)
        if before_chapter_index is not None:
            conditions.append(
                TimelineEvent.chapter_index <= before_chapter_index
            )
        if character_id:
            conditions.append(
                TimelineEvent.related_character_ids.contains([character_id])
            )
        if entity_ids:
            if len(entity_ids) == 1:
                conditions.append(
                    TimelineEvent.related_entity_ids.contains([entity_ids[0]])
                )
            else:
                conditions.append(
                    TimelineEvent.related_entity_ids.overlap(entity_ids)
                )

        # 计数
        count_stmt = select(func.count(TimelineEvent.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        # 分页排序（按 order_index 升序，同 order_index 按 created_at 升序确保确定性）
        stmt = (
            select(TimelineEvent)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(TimelineEvent.order_index.asc(), TimelineEvent.created_at.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[TimelineEvent] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        event_id: uuid.UUID,
        data: TimelineEventUpdate,
    ) -> TimelineEvent | None:
        """更新时间线事件"""
        event = await self.get(db, event_id)
        if event is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "title",
            "summary",
            "order_index",
            "chapter_index",
            "event_type",
            "visibility",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for list_field in (
            "related_character_ids",
            "related_entity_ids",
            "related_thread_ids",
            "related_location_ids",
            "known_by_character_ids",
        ):
            value = getattr(data, list_field, None)
            if value is not None:
                update_values[list_field] = value

        if data.geo_effects is not None:
            update_values["geo_effects"] = data.geo_effects

        if update_values:
            stmt = (
                update(TimelineEvent)
                .where(TimelineEvent.id == event_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            event = await self.get(db, event_id)

        return event

    async def delete(
        self,
        db: AsyncSession,
        event_id: uuid.UUID,
    ) -> bool:
        """删除时间线事件"""
        stmt = delete(TimelineEvent).where(TimelineEvent.id == event_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def get_max_order_index(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        """获取当前最大 order_index"""
        stmt = (
            select(TimelineEvent.order_index)
            .where(TimelineEvent.novel_id == novel_id)
            .order_by(TimelineEvent.order_index.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        max_order: int | None = result.scalar_one_or_none()
        return max_order if max_order is not None else -1

    async def get_geo_effects_up_to_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[TimelineEvent]:
        stmt = (
            select(TimelineEvent)
            .where(
                TimelineEvent.novel_id == novel_id,
                TimelineEvent.status == "canonical",
                or_(
                    TimelineEvent.chapter_index <= chapter_index,
                    TimelineEvent.chapter_index.is_(None),
                ),
            )
            .order_by(TimelineEvent.order_index.asc(), TimelineEvent.created_at.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[TimelineEvent] = result.scalars().all()
        return [e for e in items if isinstance(e.geo_effects, list) and len(e.geo_effects) > 0]

    async def get_all_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        status: str | None = None,
    ) -> list[TimelineEvent]:
        """获取某项目的全部时间线事件（用于冲突检查）

        Args:
            db: 数据库 session
            novel_id: 项目 ID
            status: 可选状态过滤

        Returns:
            按 order_index 排序的事件列表
        """
        conditions = [TimelineEvent.novel_id == novel_id]
        if status:
            conditions.append(TimelineEvent.status == status)

        stmt = (
            select(TimelineEvent)
            .where(*conditions)
            .order_by(TimelineEvent.order_index.asc(), TimelineEvent.created_at.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[TimelineEvent] = result.scalars().all()
        return list(items)
