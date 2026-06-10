from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import OutlineArc, PlotThread, Scene
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
    SceneCreate,
    SceneUpdate,
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
            .order_by(PlotThread.start_chapter, PlotThread.name, PlotThread.id)
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
            or_(
                PlotThread.planned_payoff_chapter.is_(None),
                PlotThread.planned_payoff_chapter >= chapter_index,
            ),
        ]
        stmt = (
            select(PlotThread)
            .where(*conditions)
            .order_by(PlotThread.start_chapter)
        )
        result = await db.execute(stmt)
        items: Sequence[PlotThread] = result.scalars().all()
        return list(items)

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        """统计与 [start_chapter, end_chapter] 范围重叠的剧情线数量。

        使用范围重叠检测（与 OutlineArc 版本一致），
        而非仅检查 start_chapter 是否在区间内。
        """
        conditions = [
            PlotThread.novel_id == novel_id,
            PlotThread.start_chapter <= end_chapter,
            # 线程没有 end_chapter 字段，用 planned_payoff_chapter 估算范围上限
            or_(
                PlotThread.planned_payoff_chapter.is_(None),
                PlotThread.planned_payoff_chapter >= start_chapter,
            ),
        ]
        stmt = select(func.count(PlotThread.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

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

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        """统计章节范围 [start, end] 内重叠的篇章数。"""
        conditions = [
            OutlineArc.novel_id == novel_id,
            OutlineArc.start_chapter <= end_chapter,
            or_(
                OutlineArc.end_chapter.is_(None),
                OutlineArc.end_chapter >= start_chapter,
            ),
        ]
        stmt = select(func.count(OutlineArc.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

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


class SceneRepository:
    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: SceneCreate,
    ) -> Scene:
        scene = Scene(
            novel_id=novel_id,
            scene_index=data.scene_index,
            title=data.title,
            goal=data.goal,
            core_conflict=data.core_conflict,
            emotional_beat=data.emotional_beat,
            must_happen=data.must_happen,
            must_not_happen=data.must_not_happen,
            narrative_tag=data.narrative_tag or "draft",
            source=data.source or "manual",
            scene_chunks=data.scene_chunks or [],
            chapter_ids=data.chapter_ids or [],
            pov_character_id=data.pov_character_id,
            status=data.status or "draft",
        )
        db.add(scene)
        await db.flush()
        return scene

    async def get(self, db: AsyncSession, scene_id: uuid.UUID) -> Scene | None:
        stmt = select(Scene).where(Scene.id == scene_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Scene], int]:
        conditions = [Scene.novel_id == novel_id]
        count_stmt = select(func.count(Scene.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(Scene)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Scene.scene_index, Scene.id)
        )
        result = await db.execute(stmt)
        items: Sequence[Scene] = result.scalars().all()
        return list(items), total

    async def get_by_novel_ordered(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[Scene]:
        stmt = (
            select(Scene)
            .where(
                Scene.novel_id == novel_id,
                Scene.status.in_(["draft", "canonical"]),
            )
            .order_by(Scene.scene_index)
        )
        result = await db.execute(stmt)
        items: Sequence[Scene] = result.scalars().all()
        return list(items)

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[Scene]:
        conditions = [
            Scene.novel_id == novel_id,
            Scene.status.in_(["draft", "canonical"]),
        ]
        stmt = (
            select(Scene)
            .where(*conditions)
            .order_by(Scene.scene_index)
        )
        result = await db.execute(stmt)
        all_scenes: Sequence[Scene] = result.scalars().all()
        matching = [
            s for s in all_scenes
            if s.chapter_ids
            and str(chapter_index) in s.chapter_ids
        ]
        return matching

    async def update(
        self,
        db: AsyncSession,
        scene_id: uuid.UUID,
        data: SceneUpdate,
    ) -> Scene | None:
        scene = await self.get(db, scene_id)
        if scene is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "scene_index", "title", "goal", "core_conflict",
            "emotional_beat", "must_happen", "must_not_happen",
            "narrative_tag", "source", "pov_character_id", "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for json_field in ("scene_chunks", "chapter_ids"):
            value = getattr(data, json_field, None)
            if value is not None:
                update_values[json_field] = value

        if update_values:
            stmt = update(Scene).where(Scene.id == scene_id).values(**update_values)
            await db.execute(stmt)
            await db.flush()

        return await self.get(db, scene_id)

    async def delete(self, db: AsyncSession, scene_id: uuid.UUID) -> bool:
        stmt = delete(Scene).where(Scene.id == scene_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def reorder(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_ids: list[uuid.UUID],
    ) -> int:
        """批量重排 scene_index，按 scene_ids 顺序从 0 开始重新编号"""
        updated = 0
        for idx, sid in enumerate(scene_ids):
            stmt = (
                update(Scene)
                .where(Scene.id == sid, Scene.novel_id == novel_id)
                .values(scene_index=idx)
            )
            result = await db.execute(stmt)
            updated += result.rowcount
        await db.flush()
        return updated
