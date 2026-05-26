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
from shared.utils import parse_uuid


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
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return PlotThreadResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        thread_id: str,
        novel_id: str,
    ) -> PlotThreadResponse:
        """获取剧情线详情"""
        tid = parse_uuid(thread_id, "thread_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, tid)
        if entity is None or str(entity.novel_id) != str(nid):
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
        nid = parse_uuid(novel_id, "novel_id")
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
        nid = parse_uuid(novel_id, "novel_id")
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

    async def list_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """获取剧情线摘要列表（供 LLM 上下文注入使用）"""
        nid = parse_uuid(novel_id, "novel_id")
        items, _ = await self._repo.get_by_novel(db, nid, limit=limit)
        return [
            {
                "id": str(t.id), "name": t.name, "thread_type": t.thread_type,
                "summary": t.summary or "", "start_chapter": t.start_chapter,
                "planned_payoff_chapter": t.planned_payoff_chapter,
            }
            for t in items
        ]

    async def update(
        self,
        db: AsyncSession,
        thread_id: str,
        data: PlotThreadUpdate,
        novel_id: str,
    ) -> PlotThreadResponse:
        """更新剧情线"""
        tid = parse_uuid(thread_id, "thread_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, tid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"PlotThread {thread_id} not found",
            )
        entity = await self._repo.update(db, tid, data)
        return PlotThreadResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        thread_id: str,
        novel_id: str,
    ) -> None:
        """删除剧情线"""
        tid = parse_uuid(thread_id, "thread_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, tid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"PlotThread {thread_id} not found",
            )
        await self._repo.delete(db, tid)



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
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return OutlineArcResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        arc_id: str,
        novel_id: str,
    ) -> OutlineArcResponse:
        """获取篇章纲详情"""
        aid = parse_uuid(arc_id, "arc_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, aid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )
        return OutlineArcResponse.model_validate(entity)

    async def get_arc_context(
        self,
        db: AsyncSession,
        arc_id: str,
        novel_id: str,
    ) -> OutlineArcContext:
        """获取篇章纲上下文（供 facade 使用）"""
        aid = parse_uuid(arc_id, "arc_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, aid)
        if entity is None or str(entity.novel_id) != str(nid):
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
            midpoint_turn=entity.midpoint_turn,
            climax=entity.climax,
            result=entity.result,
            next_hook=entity.next_hook,
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
        nid = parse_uuid(novel_id, "novel_id")
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
        novel_id: str,
    ) -> OutlineArcResponse:
        """更新篇章纲"""
        aid = parse_uuid(arc_id, "arc_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, aid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )
        entity = await self._repo.update(db, aid, data)
        return OutlineArcResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        arc_id: str,
        novel_id: str,
    ) -> None:
        """删除篇章纲"""
        aid = parse_uuid(arc_id, "arc_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, aid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"OutlineArc {arc_id} not found",
            )
        await self._repo.delete(db, aid)

    async def list_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """获取篇章纲摘要列表（供 LLM 上下文注入使用）"""
        nid = parse_uuid(novel_id, "novel_id")
        items, _ = await self._repo.get_by_novel(db, nid, limit=limit)
        return [
            {
                "id": str(a.id), "title": a.title,
                "start_chapter": a.start_chapter, "end_chapter": a.end_chapter,
            }
            for a in items
        ]



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
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return ChapterCardResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        card_id: str,
        novel_id: str,
    ) -> ChapterCardResponse:
        """获取章节卡详情"""
        cid = parse_uuid(card_id, "card_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, cid)
        if entity is None or str(entity.novel_id) != str(nid):
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
        nid = parse_uuid(novel_id, "novel_id")
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
        nid = parse_uuid(novel_id, "novel_id")
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
        nid = parse_uuid(novel_id, "novel_id")
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
        先检查再创建，同时使用 try/except IntegrityError 处理并发竞争。
        返回所有成功创建的章节卡上下文。
        """
        from sqlalchemy.exc import IntegrityError

        nid = parse_uuid(novel_id, "novel_id")
        results: list[ChapterCardContext] = []

        for item in cards:
            # 先检查是否已存在
            existing = await self._repo.get_by_chapter_index(
                db, nid, item.chapter_index,
            )
            if existing is not None:
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
            try:
                entity = await self._repo.create(db, nid, create_data)
                results.append(self._to_chapter_card_context(entity))
            except IntegrityError:
                await db.rollback()
                # 同章节已存在（并发竞争），跳过
                continue

        return results

    async def update(
        self,
        db: AsyncSession,
        card_id: str,
        data: ChapterCardUpdate,
        novel_id: str,
    ) -> ChapterCardResponse:
        """更新章节卡"""
        cid = parse_uuid(card_id, "card_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, cid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ChapterCard {card_id} not found",
            )
        entity = await self._repo.update(db, cid, data)
        return ChapterCardResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        card_id: str,
        novel_id: str,
    ) -> None:
        """删除章节卡"""
        cid = parse_uuid(card_id, "card_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, cid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ChapterCard {card_id} not found",
            )
        await self._repo.delete(db, cid)

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
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return ForeshadowingPlanResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        plan_id: str,
        novel_id: str,
    ) -> ForeshadowingPlanResponse:
        """获取伏笔计划详情"""
        pid = parse_uuid(plan_id, "plan_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, pid)
        if entity is None or str(entity.novel_id) != str(nid):
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
        nid = parse_uuid(novel_id, "novel_id")
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
        novel_id: str,
    ) -> ForeshadowingPlanResponse:
        """更新伏笔计划"""
        pid = parse_uuid(plan_id, "plan_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, pid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ForeshadowingPlan {plan_id} not found",
            )
        entity = await self._repo.update(db, pid, data)
        return ForeshadowingPlanResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        plan_id: str,
        novel_id: str,
    ) -> None:
        """删除伏笔计划"""
        pid = parse_uuid(plan_id, "plan_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, pid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ForeshadowingPlan {plan_id} not found",
            )
        await self._repo.delete(db, pid)


# ============================================================
# PlotGenerationService
# ============================================================

class PlotGenerationService:
    """剧情结构生成服务

    读取章节正文，调用 LLM 生成剧情线和篇章纲，持久化结果。
    同时被 outline/tasks.py 和 imports/workflow.py 调用。
    """

    def __init__(self) -> None:
        self._thread_service = PlotThreadService()
        self._arc_service = OutlineArcService()

    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict:
        """读取章节 → 调用 LLM → 持久化 → 返回统计"""
        # 1. 读取章节正文
        from modules.writing.facade import get_latest_draft_for_chapter

        chapters = []
        for idx in range(start_chapter, end_chapter + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.content:
                chapters.append(f"--- 第{idx}章 ---\n{draft.content}")

        if not chapters:
            return {"total_threads": 0, "total_arcs": 0, "threads": [], "arcs": []}

        batch_text = "\n\n".join(chapters)

        # 2. 加载已有上下文
        existing_threads = await self._load_existing_threads(db, novel_id)
        existing_arcs = await self._load_existing_arcs(db, novel_id)
        existing_entities = await self._load_existing_entities(db, novel_id)

        # 3. LLM 输出 Schema
        from pydantic import BaseModel

        class _GeneratedThread(BaseModel):
            name: str
            thread_type: str
            summary: str
            visible_goal: str
            start_chapter: int | None = None
            planned_payoff_chapter: int | None = None
            existing_id: str | None = None

        class _GeneratedArc(BaseModel):
            title: str
            arc_index: int
            start_chapter: int
            end_chapter: int
            arc_goal: str
            core_conflict: str
            climax: str = ""
            result: str = ""
            existing_id: str | None = None

        class _PlotOutput(BaseModel):
            plot_threads: list[_GeneratedThread]
            outline_arcs: list[_GeneratedArc]

        # 4. 构建 Prompt
        context_note = ""
        if existing_threads or existing_arcs:
            context_note = (
                f"\n已有实体：{', '.join(e['name'] for e in existing_entities[:30])}\n"
                f"已有剧情线：\n" + "\n".join(
                    f"  - id={t['id']} name={t['name']} type={t['thread_type']} "
                    f"summary={t['summary'][:50]}"
                    for t in existing_threads
                ) + "\n"
                f"已有篇章纲：\n" + "\n".join(
                    f"  - id={a['id']} title={a['title']} chapters={a['start_chapter']}-{a['end_chapter']}"
                    for a in existing_arcs
                ) + "\n"
            )

        system_prompt = (
            "你是一个小说剧情结构分析助手。"
            "从章节正文中分析识别剧情线和篇章结构。"
            f"当前章节范围：第{start_chapter}章到第{end_chapter}章\n\n"
            "输出 JSON 对象，包含：\n"
            "- plot_threads: 剧情线数组，每项包含 name, thread_type (main/secondary/hidden), "
            "summary, visible_goal, start_chapter, planned_payoff_chapter, existing_id\n"
            "- outline_arcs: 篇章纲数组，每项包含 title, arc_index, start_chapter, end_chapter, "
            "arc_goal, core_conflict, climax, result, existing_id\n\n"
            f"{context_note}"
            "规则：只基于已有章节正文分析，不凭空创造未发生的内容。\n"
            "增量规则：\n"
            "- 已有记录通过 existing_id 标记（值为已有的 id），此时更新其字段\n"
            "- 新记录 existing_id 设为 null（不提供该字段）\n"
            "- 不修改不可变字段（name, thread_type, arc_index 等，即使提供了也忽略）\n"
            "- 对已有线程，如在新章节中有明确进展则更新 summary / planned_payoff_chapter\n"
            "- 对已有篇章，如边界扩展则更新 end_chapter\n"
            "start_chapter 和 planned_payoff_chapter 必须为正整数（≥1），不确定时写 null。"
            "climax 和 result 是 OutlineArc 必填字段，必须根据正文内容填写。"
        )

        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.schemas import LLMCallRequest

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": batch_text},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        llm = LLMClient()
        parsed = await llm.generate_structured(request, _PlotOutput)

        # 5. 持久化结果
        from modules.outline.schemas import (
            OutlineArcCreate,
            OutlineArcUpdate,
            PlotThreadCreate,
            PlotThreadUpdate,
        )

        import logging

        logger = logging.getLogger(__name__)
        created_threads = []
        created_arcs = []

        for pt in parsed.plot_threads:
            sc = pt.start_chapter if (pt.start_chapter is not None and pt.start_chapter >= 1) else None
            ppc = pt.planned_payoff_chapter if (pt.planned_payoff_chapter is not None and pt.planned_payoff_chapter >= 1) else None

            if pt.existing_id:
                updates: dict = {}
                if pt.summary:
                    updates["summary"] = pt.summary
                if pt.visible_goal:
                    updates["visible_goal"] = pt.visible_goal
                if ppc is not None:
                    updates["planned_payoff_chapter"] = ppc
                if updates:
                    try:
                        await self._thread_service.update(
                            db, pt.existing_id,
                            PlotThreadUpdate(**updates),
                            novel_id,
                        )
                    except Exception as exc:
                        logger.warning("Failed to update thread %s: %s", pt.existing_id, exc)
            else:
                data = PlotThreadCreate(
                    name=pt.name, thread_type=pt.thread_type,
                    summary=pt.summary, visible_goal=pt.visible_goal,
                    start_chapter=sc, planned_payoff_chapter=ppc,
                )
                try:
                    created = await self._thread_service.create(db, novel_id, data)
                    created_threads.append({"id": str(created.id), "name": created.name})
                except Exception as exc:
                    logger.warning("Failed to create thread %s: %s", pt.name, exc)

        for arc in parsed.outline_arcs:
            if arc.existing_id:
                updates: dict = {}
                if arc.arc_goal:
                    updates["arc_goal"] = arc.arc_goal
                if arc.core_conflict:
                    updates["core_conflict"] = arc.core_conflict
                if arc.climax:
                    updates["climax"] = arc.climax
                if arc.result:
                    updates["result"] = arc.result
                if arc.end_chapter:
                    updates["end_chapter"] = arc.end_chapter
                if updates:
                    try:
                        await self._arc_service.update(
                            db, arc.existing_id,
                            OutlineArcUpdate(**updates),
                            novel_id,
                        )
                    except Exception as exc:
                        logger.warning("Failed to update arc %s: %s", arc.existing_id, exc)
            else:
                data = OutlineArcCreate(
                    title=arc.title, arc_index=arc.arc_index,
                    start_chapter=arc.start_chapter, end_chapter=arc.end_chapter,
                    arc_goal=arc.arc_goal, core_conflict=arc.core_conflict,
                    climax=arc.climax, result=arc.result,
                )
                try:
                    created = await self._arc_service.create(db, novel_id, data)
                    created_arcs.append({"id": str(created.id), "title": created.title})
                except Exception as exc:
                    logger.warning("Failed to create arc %s: %s", arc.title, exc)

        await db.flush()

        logger.info(
            "Plot structure generated: %d threads, %d arcs",
            len(created_threads), len(created_arcs),
        )

        return {
            "total_threads": len(created_threads),
            "total_arcs": len(created_arcs),
            "threads": created_threads,
            "arcs": created_arcs,
        }

    async def _load_existing_threads(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[dict]:
        from modules.outline.facade import list_thread_summaries
        return await list_thread_summaries(db, novel_id)

    async def _load_existing_arcs(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[dict]:
        from modules.outline.facade import list_arc_summaries
        return await list_arc_summaries(db, novel_id)

    async def _load_existing_entities(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[dict]:
        from modules.world.facade import list_entities
        return await list_entities(db, novel_id)



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
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.create(db, nid, data)
        return RevealPlanResponse.model_validate(entity)

    async def get(
        self,
        db: AsyncSession,
        plan_id: str,
        novel_id: str,
    ) -> RevealPlanResponse:
        """获取揭示计划详情"""
        pid = parse_uuid(plan_id, "plan_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, pid)
        if entity is None or str(entity.novel_id) != str(nid):
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
        nid = parse_uuid(novel_id, "novel_id")
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
        novel_id: str,
    ) -> RevealPlanResponse:
        """更新揭示计划"""
        pid = parse_uuid(plan_id, "plan_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, pid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"RevealPlan {plan_id} not found",
            )
        entity = await self._repo.update(db, pid, data)
        return RevealPlanResponse.model_validate(entity)

    async def delete(
        self,
        db: AsyncSession,
        plan_id: str,
        novel_id: str,
    ) -> None:
        """删除揭示计划"""
        pid = parse_uuid(plan_id, "plan_id")
        nid = parse_uuid(novel_id, "novel_id")
        entity = await self._repo.get(db, pid)
        if entity is None or str(entity.novel_id) != str(nid):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"RevealPlan {plan_id} not found",
            )
        await self._repo.delete(db, pid)

