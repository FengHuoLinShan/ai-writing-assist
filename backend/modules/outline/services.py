"""
Outline 业务逻辑层

组装 repository 完成业务操作。服务层可包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import (
    ChapterCard,
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
)
from modules.outline.repositories import (
    ChapterCardRepository,
    ForeshadowingPlanRepository,
    OutlineArcRepository,
    PlotThreadRepository,
    RevealPlanRepository,
)
from modules.outline.schemas import (
    ChapterCardCandidateItem,
    ChapterCardContext,
    ChapterCardCreate,
    ChapterCardListResponse,
    ChapterCardResponse,
    ChapterCardUpdate,
    ForeshadowingPlanCreate,
    ForeshadowingPlanListResponse,
    ForeshadowingPlanResponse,
    ForeshadowingPlanUpdate,
    OutlineArcContext,
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadContext,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanListResponse,
    RevealPlanResponse,
    RevealPlanUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


# ============================================================
# PlotThreadService
# ============================================================

class PlotThreadService:
    """剧情线业务服务"""

    def __init__(self) -> None:
        self._repo = PlotThreadRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: PlotThreadCreate,
    ) -> PlotThreadResponse:
        """创建剧情线"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return PlotThreadResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        thread_id: str,
    ) -> PlotThreadResponse:
        """获取剧情线详情"""
        tid = self._parse_uuid(thread_id, "thread_id")
        entity = await self._repo.get(db, tid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"PlotThread {thread_id} not found",
            )
        return PlotThreadResponse.model_validate(entity)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        thread_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> PlotThreadListResponse:
        """获取剧情线列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            thread_type=thread_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        return PlotThreadListResponse(
            items=[PlotThreadResponse.model_validate(e) for e in items],
            total=total,
        )

    async def get_active_threads(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[PlotThreadContext]:
        """获取活跃剧情线上下文（供 facade 使用）"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        threads = await self._repo.get_active_by_novel(
            db, nid,
            chapter_index=chapter_index,
            limit=limit,
        )
        return [
            PlotThreadContext(
                thread_id=str(t.id),
                name=t.name,
                thread_type=t.thread_type,
                summary=t.summary,
                visible_goal=t.visible_goal,
                current_stage=t.current_stage,
                start_chapter=t.start_chapter,
                planned_payoff_chapter=t.planned_payoff_chapter,
                related_character_ids=t.related_character_ids or [],
                related_entity_ids=t.related_entity_ids or [],
                status=t.status,
            )
            for t in threads
        ]

    async def update(
        self,
        db: AsyncSession,
        thread_id: str,
        data: PlotThreadUpdate,
    ) -> PlotThreadResponse:
        """更新剧情线"""
        tid = self._parse_uuid(thread_id, "thread_id")
        entity = await self._repo.update(db, tid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"PlotThread {thread_id} not found",
            )
        return PlotThreadResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        thread_id: str,
    ) -> None:
        """删除剧情线"""
        tid = self._parse_uuid(thread_id, "thread_id")
        deleted = await self._repo.delete(db, tid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"PlotThread {thread_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# OutlineArcService
# ============================================================

class OutlineArcService:
    """篇章纲业务服务"""

    def __init__(self) -> None:
        self._repo = OutlineArcRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: OutlineArcCreate,
    ) -> OutlineArcResponse:
        """创建篇章纲"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return OutlineArcResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        arc_id: str,
    ) -> OutlineArcResponse:
        """获取篇章纲详情"""
        aid = self._parse_uuid(arc_id, "arc_id")
        entity = await self._repo.get(db, aid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )
        return OutlineArcResponse.model_validate(entity)

    async def get_arc_context(
        self,
        db: AsyncSession,
        arc_id: str,
    ) -> OutlineArcContext:
        """获取篇章纲上下文（供 facade 使用）"""
        aid = self._parse_uuid(arc_id, "arc_id")
        entity = await self._repo.get(db, aid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )
        return self._to_outline_arc_context(entity)

    @staticmethod
    def _to_outline_arc_context(entity: OutlineArc) -> OutlineArcContext:
        """将 ORM 模型转为上下文对象"""
        return OutlineArcContext(
            arc_id=str(entity.id),
            title=entity.title,
            arc_index=entity.arc_index,
            start_chapter=entity.start_chapter,
            end_chapter=entity.end_chapter,
            arc_goal=entity.arc_goal,
            core_conflict=entity.core_conflict,
            main_opposition=entity.main_opposition,
            entry_hook=entity.entry_hook,
            climax=entity.climax,
            result=entity.result,
            related_thread_ids=entity.related_thread_ids or [],
            related_character_ids=entity.related_character_ids or [],
            related_entity_ids=entity.related_entity_ids or [],
            status=entity.status,
        )

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> OutlineArcListResponse:
        """获取篇章纲列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            status=status,
            skip=skip,
            limit=limit,
        )
        return OutlineArcListResponse(
            items=[OutlineArcResponse.model_validate(e) for e in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        arc_id: str,
        data: OutlineArcUpdate,
    ) -> OutlineArcResponse:
        """更新篇章纲"""
        aid = self._parse_uuid(arc_id, "arc_id")
        entity = await self._repo.update(db, aid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )
        return OutlineArcResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        arc_id: str,
    ) -> None:
        """删除篇章纲"""
        aid = self._parse_uuid(arc_id, "arc_id")
        deleted = await self._repo.delete(db, aid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# ChapterCardService
# ============================================================

class ChapterCardService:
    """章节卡业务服务"""

    def __init__(self) -> None:
        self._repo = ChapterCardRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: ChapterCardCreate,
    ) -> ChapterCardResponse:
        """创建章节卡"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return ChapterCardResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        card_id: str,
    ) -> ChapterCardResponse:
        """获取章节卡详情"""
        cid = self._parse_uuid(card_id, "card_id")
        entity = await self._repo.get(db, cid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ChapterCard {card_id} not found",
            )
        return ChapterCardResponse.model_validate(entity)

    async def get_by_chapter_index(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> ChapterCardResponse | None:
        """按章节索引获取章节卡"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get_by_chapter_index(db, nid, chapter_index)
        if entity is None:
            return None
        return ChapterCardResponse.model_validate(entity)

    async def get_chapter_card_context(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> ChapterCardContext | None:
        """获取章节卡上下文（供 facade 使用）"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get_by_chapter_index(db, nid, chapter_index)
        if entity is None:
            return None
        return self._to_chapter_card_context(entity)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        arc_id: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ChapterCardListResponse:
        """获取章节卡列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            arc_id=arc_id,
            status=status,
            skip=skip,
            limit=limit,
        )
        return ChapterCardListResponse(
            items=[ChapterCardResponse.model_validate(e) for e in items],
            total=total,
        )

    async def create_from_candidate(
        self,
        db: AsyncSession,
        novel_id: str,
        cards: list[ChapterCardCandidateItem],
    ) -> list[ChapterCardContext]:
        """从候选批量创建章节卡（供 facade 使用）

        对每个候选创建 ChapterCardCreate，如果同章节已存在则跳过。
        返回所有成功创建的章节卡上下文。
        """
        nid = self._parse_uuid(novel_id, "novel_id")
        results: list[ChapterCardContext] = []

        for item in cards:
            # 检查是否已存在
            existing = await self._repo.get_by_chapter_index(
                db, nid, item.chapter_index,
            )
            if existing is not None:
                # 已存在则跳过
                continue

            create_data = ChapterCardCreate(
                chapter_index=item.chapter_index,
                title=item.title,
                arc_id=item.arc_id,
                chapter_goal=item.chapter_goal,
                main_conflict=item.main_conflict,
                emotional_point=item.emotional_point,
                plot_function=item.plot_function,
                must_happen=item.must_happen,
                must_not_happen=item.must_not_happen,
                involved_character_ids=item.involved_character_ids,
                involved_entity_ids=item.involved_entity_ids,
                related_thread_ids=item.related_thread_ids,
                visible_progress=item.visible_progress,
                hidden_progress=item.hidden_progress,
                offscreen_progress=item.offscreen_progress,
                foreshadowing_actions=item.foreshadowing_actions,
                ending_hook=item.ending_hook,
                scene_cards=item.scene_cards,
                status="candidate",
            )
            entity = await self._repo.create(db, nid, create_data)
            results.append(self._to_chapter_card_context(entity))

        return results

    async def update(
        self,
        db: AsyncSession,
        card_id: str,
        data: ChapterCardUpdate,
    ) -> ChapterCardResponse:
        """更新章节卡"""
        cid = self._parse_uuid(card_id, "card_id")
        entity = await self._repo.update(db, cid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ChapterCard {card_id} not found",
            )
        return ChapterCardResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        card_id: str,
    ) -> None:
        """删除章节卡"""
        cid = self._parse_uuid(card_id, "card_id")
        deleted = await self._repo.delete(db, cid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ChapterCard {card_id} not found",
            )

    def _to_chapter_card_context(
        self,
        entity: ChapterCard,
    ) -> ChapterCardContext:
        """将 ORM 模型转为上下文对象"""
        return ChapterCardContext(
            card_id=str(entity.id),
            chapter_index=entity.chapter_index,
            title=entity.title,
            arc_id=entity.arc_id,
            chapter_goal=entity.chapter_goal,
            main_conflict=entity.main_conflict,
            emotional_point=entity.emotional_point,
            plot_function=entity.plot_function,
            must_happen=entity.must_happen or [],
            must_not_happen=entity.must_not_happen or [],
            involved_character_ids=entity.involved_character_ids or [],
            involved_entity_ids=entity.involved_entity_ids or [],
            related_thread_ids=entity.related_thread_ids or [],
            visible_progress=entity.visible_progress or [],
            hidden_progress=entity.hidden_progress or [],
            offscreen_progress=entity.offscreen_progress or [],
            foreshadowing_actions=entity.foreshadowing_actions or [],
            ending_hook=entity.ending_hook,
            scene_cards=entity.scene_cards or [],
            status=entity.status,
        )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# ForeshadowingPlanService
# ============================================================

class ForeshadowingPlanService:
    """伏笔计划业务服务"""

    def __init__(self) -> None:
        self._repo = ForeshadowingPlanRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: ForeshadowingPlanCreate,
    ) -> ForeshadowingPlanResponse:
        """创建伏笔计划"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return ForeshadowingPlanResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> ForeshadowingPlanResponse:
        """获取伏笔计划详情"""
        pid = self._parse_uuid(plan_id, "plan_id")
        entity = await self._repo.get(db, pid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ForeshadowingPlan {plan_id} not found",
            )
        return ForeshadowingPlanResponse.model_validate(entity)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ForeshadowingPlanListResponse:
        """获取伏笔计划列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            status=status,
            skip=skip,
            limit=limit,
        )
        return ForeshadowingPlanListResponse(
            items=[ForeshadowingPlanResponse.model_validate(e) for e in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        plan_id: str,
        data: ForeshadowingPlanUpdate,
    ) -> ForeshadowingPlanResponse:
        """更新伏笔计划"""
        pid = self._parse_uuid(plan_id, "plan_id")
        entity = await self._repo.update(db, pid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ForeshadowingPlan {plan_id} not found",
            )
        return ForeshadowingPlanResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> None:
        """删除伏笔计划"""
        pid = self._parse_uuid(plan_id, "plan_id")
        deleted = await self._repo.delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ForeshadowingPlan {plan_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )


# ============================================================
# RevealPlanService
# ============================================================

class RevealPlanService:
    """揭示计划业务服务"""

    def __init__(self) -> None:
        self._repo = RevealPlanRepository()

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        data: RevealPlanCreate,
    ) -> RevealPlanResponse:
        """创建揭示计划"""
        nid = self._parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return RevealPlanResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> RevealPlanResponse:
        """获取揭示计划详情"""
        pid = self._parse_uuid(plan_id, "plan_id")
        entity = await self._repo.get(db, pid)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"RevealPlan {plan_id} not found",
            )
        return RevealPlanResponse.model_validate(entity)

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        target_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> RevealPlanListResponse:
        """获取揭示计划列表"""
        nid = self._parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(
            db, nid,
            target_type=target_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        return RevealPlanListResponse(
            items=[RevealPlanResponse.model_validate(e) for e in items],
            total=total,
        )

    async def update(
        self,
        db: AsyncSession,
        plan_id: str,
        data: RevealPlanUpdate,
    ) -> RevealPlanResponse:
        """更新揭示计划"""
        pid = self._parse_uuid(plan_id, "plan_id")
        entity = await self._repo.update(db, pid, data)
        if entity is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"RevealPlan {plan_id} not found",
            )
        return RevealPlanResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        plan_id: str,
    ) -> None:
        """删除揭示计划"""
        pid = self._parse_uuid(plan_id, "plan_id")
        deleted = await self._repo.delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"RevealPlan {plan_id} not found",
            )

    @staticmethod
    def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
        try:
            return uuid.UUID(hex=value)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid {field_name}: {value}",
            )
