"""
Outline 数据访问层

封装 5 张表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import (
    ChapterCard,
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
)
from modules.outline.schemas import (
    ChapterCardCreate,
    ChapterCardUpdate,
    ForeshadowingPlanCreate,
    ForeshadowingPlanUpdate,
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE

# ============================================================
# PlotThreadRepository
# ============================================================


class PlotThreadRepository:
    """剧情线数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: PlotThreadCreate,
    ) -> PlotThread:
        """创建剧情线"""
        entity = PlotThread(
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
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        thread_id: uuid.UUID,
    ) -> PlotThread | None:
        """根据 ID 获取剧情线"""
        stmt = select(PlotThread).where(PlotThread.id == thread_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        thread_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PlotThread], int]:
        """获取小说的剧情线列表（分页），返回 (items, total)"""
        conditions = [PlotThread.novel_id == novel_id]
        if thread_type:
            conditions.append(PlotThread.thread_type == thread_type)
        if status:
            conditions.append(PlotThread.status == status)

        # 计数
        count_stmt = select(func.count(PlotThread.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        # 分页查询
        stmt = (
            select(PlotThread)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(PlotThread.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[PlotThread] = result.scalars().all()
        return list(items), total

    async def get_active_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        chapter_index: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[PlotThread]:
        """获取活跃剧情线（status=canonical，且在指定章节仍活跃）

        如果提供了 chapter_index，筛选 start_chapter <= chapter_index
        且 (planned_payoff_chapter IS NULL
        OR planned_payoff_chapter >= chapter_index) 的线。
        如未提供 chapter_index，返回所有 canonical 状态的线。
        """
        conditions = [
            PlotThread.novel_id == novel_id,
            PlotThread.status.in_(["canonical", "draft"]),
        ]

        if chapter_index is not None:
            conditions.append(
                or_(
                    PlotThread.start_chapter.is_(None),
                    PlotThread.start_chapter <= chapter_index,
                )
            )
            conditions.append(
                or_(
                    PlotThread.planned_payoff_chapter.is_(None),
                    PlotThread.planned_payoff_chapter >= chapter_index,
                )
            )

        stmt = (
            select(PlotThread)
            .where(*conditions)
            .limit(limit)
            .order_by(PlotThread.created_at.asc())
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
        """更新剧情线，返回更新后的对象（不存在返回 None）"""
        entity = await self.get(db, thread_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "name",
            "thread_type",
            "summary",
            "visible_goal",
            "hidden_truth",
            "start_chapter",
            "planned_payoff_chapter",
            "current_stage",
            "reader_known_state",
            "author_known_state",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for list_field in (
            "related_character_ids",
            "related_entity_ids",
            "related_memory_ids",
        ):
            value = getattr(data, list_field, None)
            if value is not None:
                update_values[list_field] = value

        if update_values:
            stmt = (
                update(PlotThread)
                .where(PlotThread.id == thread_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            entity = await self.get(db, thread_id)

        return entity

    async def delete(
        self,
        db: AsyncSession,
        thread_id: uuid.UUID,
    ) -> bool:
        """删除剧情线，返回是否成功删除"""
        stmt = delete(PlotThread).where(PlotThread.id == thread_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# OutlineArcRepository
# ============================================================


class OutlineArcRepository:
    """篇章纲数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: OutlineArcCreate,
    ) -> OutlineArc:
        """创建篇章纲"""
        entity = OutlineArc(
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
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        arc_id: uuid.UUID,
    ) -> OutlineArc | None:
        """根据 ID 获取篇章纲"""
        stmt = select(OutlineArc).where(OutlineArc.id == arc_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[OutlineArc], int]:
        """获取小说的篇章纲列表（分页），返回 (items, total)"""
        conditions = [OutlineArc.novel_id == novel_id]
        if status:
            conditions.append(OutlineArc.status == status)

        count_stmt = select(func.count(OutlineArc.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(OutlineArc)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(OutlineArc.arc_index.asc().nullslast())
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
        """通过章节索引查找所在篇章"""
        stmt = select(OutlineArc).where(
            OutlineArc.novel_id == novel_id,
            OutlineArc.start_chapter <= chapter_index,
            OutlineArc.end_chapter >= chapter_index,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        arc_id: uuid.UUID,
        data: OutlineArcUpdate,
    ) -> OutlineArc | None:
        """更新篇章纲"""
        entity = await self.get(db, arc_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "title",
            "arc_index",
            "start_chapter",
            "end_chapter",
            "arc_goal",
            "core_conflict",
            "main_opposition",
            "entry_hook",
            "midpoint_turn",
            "climax",
            "result",
            "next_hook",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for list_field in (
            "related_thread_ids",
            "related_character_ids",
            "related_entity_ids",
        ):
            value = getattr(data, list_field, None)
            if value is not None:
                update_values[list_field] = value

        if update_values:
            stmt = (
                update(OutlineArc).where(OutlineArc.id == arc_id).values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            entity = await self.get(db, arc_id)

        return entity

    async def delete(
        self,
        db: AsyncSession,
        arc_id: uuid.UUID,
    ) -> bool:
        """删除篇章纲"""
        stmt = delete(OutlineArc).where(OutlineArc.id == arc_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# ChapterCardRepository
# ============================================================


class ChapterCardRepository:
    """章节卡数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: ChapterCardCreate,
    ) -> ChapterCard:
        """创建章节卡"""
        entity = ChapterCard(
            novel_id=novel_id,
            chapter_index=data.chapter_index,
            title=data.title,
            arc_id=data.arc_id,
            chapter_goal=data.chapter_goal,
            main_conflict=data.main_conflict,
            emotional_point=data.emotional_point,
            plot_function=data.plot_function,
            must_happen=data.must_happen or [],
            must_not_happen=data.must_not_happen or [],
            involved_character_ids=data.involved_character_ids or [],
            involved_entity_ids=data.involved_entity_ids or [],
            related_thread_ids=data.related_thread_ids or [],
            visible_progress=data.visible_progress or [],
            hidden_progress=data.hidden_progress or [],
            offscreen_progress=data.offscreen_progress or [],
            foreshadowing_actions=data.foreshadowing_actions or [],
            ending_hook=data.ending_hook,
            scene_cards=data.scene_cards or [],
            status=data.status or "draft",
        )
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
    ) -> ChapterCard | None:
        """根据 ID 获取章节卡"""
        stmt = select(ChapterCard).where(ChapterCard.id == card_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_chapter_index(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> ChapterCard | None:
        """根据章节索引获取章节卡"""
        stmt = select(ChapterCard).where(
            ChapterCard.novel_id == novel_id,
            ChapterCard.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        arc_id: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[ChapterCard], int]:
        """获取小说的章节卡列表（分页），返回 (items, total)"""
        conditions = [ChapterCard.novel_id == novel_id]
        if arc_id:
            conditions.append(ChapterCard.arc_id == arc_id)
        if status:
            conditions.append(ChapterCard.status == status)

        count_stmt = select(func.count(ChapterCard.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(ChapterCard)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(ChapterCard.chapter_index.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[ChapterCard] = result.scalars().all()
        return list(items), total

    async def get_range_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> list[ChapterCard]:
        """获取指定章节范围内的章节卡"""
        stmt = (
            select(ChapterCard)
            .where(
                ChapterCard.novel_id == novel_id,
                ChapterCard.chapter_index >= start_chapter,
                ChapterCard.chapter_index <= end_chapter,
            )
            .order_by(ChapterCard.chapter_index.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[ChapterCard] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
        data: ChapterCardUpdate,
    ) -> ChapterCard | None:
        """更新章节卡"""
        entity = await self.get(db, card_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "chapter_index",
            "title",
            "arc_id",
            "chapter_goal",
            "main_conflict",
            "emotional_point",
            "plot_function",
            "ending_hook",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for list_field in (
            "must_happen",
            "must_not_happen",
            "involved_character_ids",
            "involved_entity_ids",
            "related_thread_ids",
            "visible_progress",
            "hidden_progress",
            "offscreen_progress",
            "foreshadowing_actions",
            "scene_cards",
        ):
            value = getattr(data, list_field, None)
            if value is not None:
                update_values[list_field] = value

        if update_values:
            stmt = (
                update(ChapterCard)
                .where(ChapterCard.id == card_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            entity = await self.get(db, card_id)

        return entity

    async def delete(
        self,
        db: AsyncSession,
        card_id: uuid.UUID,
    ) -> bool:
        """删除章节卡"""
        stmt = delete(ChapterCard).where(ChapterCard.id == card_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def merge_involved_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        character_ids: list[str],
        entity_ids: list[str],
    ) -> None:
        stmt = (
            select(ChapterCard)
            .where(
                ChapterCard.novel_id == novel_id,
                ChapterCard.chapter_index == chapter_index,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        card = result.scalar_one_or_none()
        if card is None:
            return

        existing_chars = list(card.involved_character_ids or [])
        existing_entities = list(card.involved_entity_ids or [])

        merged_chars = list(set(existing_chars + character_ids))
        merged_entities = list(set(existing_entities + entity_ids))

        card.involved_character_ids = merged_chars
        card.involved_entity_ids = merged_entities
        await db.flush()


# ============================================================
# ForeshadowingPlanRepository
# ============================================================


class ForeshadowingPlanRepository:
    """伏笔计划数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: ForeshadowingPlanCreate,
    ) -> ForeshadowingPlan:
        """创建伏笔计划"""
        entity = ForeshadowingPlan(
            novel_id=novel_id,
            name=data.name,
            summary=data.summary,
            surface_meaning=data.surface_meaning,
            hidden_meaning=data.hidden_meaning,
            planned_seed_chapter=data.planned_seed_chapter,
            planned_reinforce_chapters=data.planned_reinforce_chapters or [],
            planned_payoff_chapter=data.planned_payoff_chapter,
            related_entity_ids=data.related_entity_ids or [],
            related_thread_ids=data.related_thread_ids or [],
            status=data.status or "draft",
        )
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
    ) -> ForeshadowingPlan | None:
        """根据 ID 获取伏笔计划"""
        stmt = select(ForeshadowingPlan).where(ForeshadowingPlan.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[ForeshadowingPlan], int]:
        """获取小说的伏笔计划列表（分页）"""
        conditions = [ForeshadowingPlan.novel_id == novel_id]
        if status:
            conditions.append(ForeshadowingPlan.status == status)

        count_stmt = select(func.count(ForeshadowingPlan.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(ForeshadowingPlan)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(ForeshadowingPlan.planned_seed_chapter.asc().nullslast())
        )
        result = await db.execute(stmt)
        items: Sequence[ForeshadowingPlan] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: ForeshadowingPlanUpdate,
    ) -> ForeshadowingPlan | None:
        """更新伏笔计划"""
        entity = await self.get(db, plan_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "name",
            "summary",
            "surface_meaning",
            "hidden_meaning",
            "planned_seed_chapter",
            "planned_payoff_chapter",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for list_field in (
            "planned_reinforce_chapters",
            "related_entity_ids",
            "related_thread_ids",
        ):
            value = getattr(data, list_field, None)
            if value is not None:
                update_values[list_field] = value

        if update_values:
            stmt = (
                update(ForeshadowingPlan)
                .where(ForeshadowingPlan.id == plan_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            entity = await self.get(db, plan_id)

        return entity

    async def delete(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
    ) -> bool:
        """删除伏笔计划"""
        stmt = delete(ForeshadowingPlan).where(ForeshadowingPlan.id == plan_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# RevealPlanRepository
# ============================================================


class RevealPlanRepository:
    """揭示计划数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: RevealPlanCreate,
    ) -> RevealPlan:
        """创建揭示计划"""
        entity = RevealPlan(
            novel_id=novel_id,
            target_type=data.target_type,
            target_id=uuid.UUID(hex=data.target_id)
            if isinstance(data.target_id, str)
            else data.target_id,
            secret_summary=data.secret_summary,
            reveal_stages=data.reveal_stages or [],
            status=data.status or "draft",
        )
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
    ) -> RevealPlan | None:
        """根据 ID 获取揭示计划"""
        stmt = select(RevealPlan).where(RevealPlan.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        target_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[RevealPlan], int]:
        """获取小说的揭示计划列表（分页）"""
        conditions = [RevealPlan.novel_id == novel_id]
        if target_type:
            conditions.append(RevealPlan.target_type == target_type)
        if status:
            conditions.append(RevealPlan.status == status)

        count_stmt = select(func.count(RevealPlan.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            select(RevealPlan)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(RevealPlan.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[RevealPlan] = result.scalars().all()
        return list(items), total

    async def get_by_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target_type: str,
        target_id: str,
    ) -> list[RevealPlan]:
        stmt = select(RevealPlan).where(
            RevealPlan.novel_id == novel_id,
            RevealPlan.target_type == target_type,
            RevealPlan.target_id == uuid.UUID(hex=target_id)
            if isinstance(target_id, str)
            else target_id,
        )
        result = await db.execute(stmt)
        items: Sequence[RevealPlan] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: RevealPlanUpdate,
    ) -> RevealPlan | None:
        """更新揭示计划"""
        entity = await self.get(db, plan_id)
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "target_type",
            "secret_summary",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.target_id is not None:
            tid = data.target_id
            update_values["target_id"] = (
                uuid.UUID(hex=tid) if isinstance(tid, str) else tid
            )

        if data.reveal_stages is not None:
            update_values["reveal_stages"] = data.reveal_stages

        if update_values:
            stmt = (
                update(RevealPlan).where(RevealPlan.id == plan_id).values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            entity = await self.get(db, plan_id)

        return entity

    async def delete(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
    ) -> bool:
        """删除揭示计划"""
        stmt = delete(RevealPlan).where(RevealPlan.id == plan_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
