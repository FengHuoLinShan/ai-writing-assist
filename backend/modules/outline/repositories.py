from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import OutlineArc, PlotThread
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE


class PlotThreadRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: PlotThreadCreate,
    ) -> PlotThread:
        thread = PlotThread(
            novel_id=novel_id,
            name=data.name,
            thread_type=data.thread_type,
            summary=data.summary,
            visible_goal=data.visible_goal,
            hidden_truth=data.hidden_truth,
            start_chapter=data.start_chapter,
            planned_payoff_chapter=data.planned_payoff_chapter,
            current_stage=data.current_stage,
            related_character_ids=data.related_character_ids or [],
            related_entity_ids=data.related_entity_ids or [],
            related_memory_ids=data.related_memory_ids or [],
            reader_known_state=data.reader_known_state,
            author_known_state=data.author_known_state,
            status=data.status or "draft",
        )
        db.add(thread)
        await db.flush()
        return thread

    async def get(self, db: AsyncSession, thread_id: uuid.UUID) -> PlotThread | None:
        stmt = select(PlotThread).where(PlotThread.id == thread_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PlotThread], int]:
        conditions = [PlotThread.novel_id == novel_id]
        count_stmt = select(func.count(PlotThread.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(PlotThread)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(PlotThread.start_chapter, PlotThread.name)
        )
        result = await db.execute(stmt)
        items: Sequence[PlotThread] = result.scalars().all()
        return list(items), total

    async def get_active(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[PlotThread]:
        """获取某个章节时活跃的剧情线（start_chapter <= chapter_index，且未完结或 planned_payoff >= chapter）"""
        conditions = [
            PlotThread.novel_id == novel_id,
            PlotThread.status.in_(["draft", "canonical"]),
            PlotThread.start_chapter <= chapter_index,
        ]
        stmt = (
            select(PlotThread)
            .where(*conditions)
            .order_by(PlotThread.start_chapter)
        )
        result = await db.execute(stmt)
        items: Sequence[PlotThread] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        thread_id: uuid.UUID,
        data: PlotThreadUpdate,
    ) -> PlotThread | None:
        thread = await self.get(db, thread_id)
        if thread is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "name", "thread_type", "summary", "visible_goal", "hidden_truth",
            "start_chapter", "planned_payoff_chapter", "current_stage",
            "reader_known_state", "author_known_state", "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for json_field in ("related_character_ids", "related_entity_ids", "related_memory_ids"):
            value = getattr(data, json_field, None)
            if value is not None:
                update_values[json_field] = value

        if update_values:
            stmt = update(PlotThread).where(PlotThread.id == thread_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, thread_id)

    async def delete(self, db: AsyncSession, thread_id: uuid.UUID) -> bool:
        stmt = delete(PlotThread).where(PlotThread.id == thread_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


class OutlineArcRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: OutlineArcCreate,
    ) -> OutlineArc:
        arc = OutlineArc(
            novel_id=novel_id,
            title=data.title,
            arc_index=data.arc_index,
            start_chapter=data.start_chapter,
            end_chapter=data.end_chapter,
            arc_goal=data.arc_goal,
            core_conflict=data.core_conflict,
            main_opposition=data.main_opposition,
            entry_hook=data.entry_hook,
            midpoint_turn=data.midpoint_turn,
            climax=data.climax,
            result=data.result,
            next_hook=data.next_hook,
            related_thread_ids=data.related_thread_ids or [],
            related_character_ids=data.related_character_ids or [],
            related_entity_ids=data.related_entity_ids or [],
            status=data.status or "draft",
        )
        db.add(arc)
        await db.flush()
        return arc

    async def get(self, db: AsyncSession, arc_id: uuid.UUID) -> OutlineArc | None:
        stmt = select(OutlineArc).where(OutlineArc.id == arc_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[OutlineArc], int]:
        conditions = [OutlineArc.novel_id == novel_id]
        count_stmt = select(func.count(OutlineArc.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(OutlineArc)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(OutlineArc.arc_index)
        )
        result = await db.execute(stmt)
        items: Sequence[OutlineArc] = result.scalars().all()
        return list(items), total

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> OutlineArc | None:
        """获取指定章节所属的篇章"""
        stmt = (
            select(OutlineArc)
            .where(
                OutlineArc.novel_id == novel_id,
                OutlineArc.start_chapter <= chapter_index,
                OutlineArc.end_chapter >= chapter_index,
                OutlineArc.status.in_(["draft", "canonical"]),
            )
            .order_by(OutlineArc.arc_index)
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        arc_id: uuid.UUID,
        data: OutlineArcUpdate,
    ) -> OutlineArc | None:
        arc = await self.get(db, arc_id)
        if arc is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "title", "arc_index", "start_chapter", "end_chapter",
            "arc_goal", "core_conflict", "main_opposition", "entry_hook",
            "midpoint_turn", "climax", "result", "next_hook", "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for json_field in ("related_thread_ids", "related_character_ids", "related_entity_ids"):
            value = getattr(data, json_field, None)
            if value is not None:
                update_values[json_field] = value

        if update_values:
            stmt = update(OutlineArc).where(OutlineArc.id == arc_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, arc_id)

    async def delete(self, db: AsyncSession, arc_id: uuid.UUID) -> bool:
        stmt = delete(OutlineArc).where(OutlineArc.id == arc_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
