from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import OutlineArcContract, PlotThreadContract
from modules.outline.repositories import OutlineArcRepository, PlotThreadRepository
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


class PlotThreadService:
    def __init__(self) -> None:
        self._repo = PlotThreadRepository()

    async def create(
        self, db: AsyncSession, novel_id: str, data: PlotThreadCreate,
    ) -> PlotThreadResponse:
        nid = parse_uuid(novel_id, "novel_id")
        thread = await self._repo.create(db, nid, data)
        return PlotThreadResponse.model_validate(thread)

    async def get(
        self, db: AsyncSession, thread_id: str, novel_id: str,
    ) -> PlotThreadResponse | None:
        tid = parse_uuid(thread_id, "thread_id")
        thread = await self._repo.get(db, tid)
        if thread is None or str(thread.novel_id) != novel_id:
            return None
        return PlotThreadResponse.model_validate(thread)

    async def list(
        self, db: AsyncSession, novel_id: str,
        *, skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> PlotThreadListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return PlotThreadListResponse(
            items=[PlotThreadResponse.model_validate(t) for t in items],
            total=total,
        )

    async def get_active(
        self, db: AsyncSession, novel_id: str, chapter_index: int,
    ) -> list[PlotThreadContract]:
        nid = parse_uuid(novel_id, "novel_id")
        threads = await self._repo.get_active(db, nid, chapter_index)
        return [
            PlotThreadContract(
                id=str(t.id), novel_id=str(t.novel_id),
                name=t.name, thread_type=t.thread_type,
                summary=t.summary, visible_goal=t.visible_goal,
                hidden_truth=t.hidden_truth,
                start_chapter=t.start_chapter,
                planned_payoff_chapter=t.planned_payoff_chapter,
                current_stage=t.current_stage,
                related_character_ids=t.related_character_ids or [],
                related_entity_ids=t.related_entity_ids or [],
                reader_known_state=t.reader_known_state,
                author_known_state=t.author_known_state,
                status=t.status,
            )
            for t in threads
        ]

    async def update(
        self, db: AsyncSession, thread_id: str, data: PlotThreadUpdate,
    ) -> PlotThreadResponse | None:
        tid = parse_uuid(thread_id, "thread_id")
        thread = await self._repo.update(db, tid, data)
        if thread is None:
            return None
        return PlotThreadResponse.model_validate(thread)

    async def delete(
        self, db: AsyncSession, thread_id: str, novel_id: str,
    ) -> bool:
        tid = parse_uuid(thread_id, "thread_id")
        thread = await self._repo.get(db, tid)
        if thread is None or str(thread.novel_id) != novel_id:
            return False
        return await self._repo.delete(db, tid)


class OutlineArcService:
    def __init__(self) -> None:
        self._repo = OutlineArcRepository()

    async def create(
        self, db: AsyncSession, novel_id: str, data: OutlineArcCreate,
    ) -> OutlineArcResponse:
        nid = parse_uuid(novel_id, "novel_id")
        arc = await self._repo.create(db, nid, data)
        return OutlineArcResponse.model_validate(arc)

    async def get(
        self, db: AsyncSession, arc_id: str, novel_id: str,
    ) -> OutlineArcResponse | None:
        aid = parse_uuid(arc_id, "arc_id")
        arc = await self._repo.get(db, aid)
        if arc is None or str(arc.novel_id) != novel_id:
            return None
        return OutlineArcResponse.model_validate(arc)

    async def list(
        self, db: AsyncSession, novel_id: str,
        *, skip: int = 0, limit: int = DEFAULT_PAGE_SIZE,
    ) -> OutlineArcListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return OutlineArcListResponse(
            items=[OutlineArcResponse.model_validate(a) for a in items],
            total=total,
        )

    async def get_by_chapter(
        self, db: AsyncSession, novel_id: str, chapter_index: int,
    ) -> OutlineArcContract | None:
        nid = parse_uuid(novel_id, "novel_id")
        arc = await self._repo.get_by_chapter(db, nid, chapter_index)
        if arc is None:
            return None
        return OutlineArcContract(
            id=str(arc.id), novel_id=str(arc.novel_id),
            title=arc.title, arc_index=arc.arc_index,
            start_chapter=arc.start_chapter, end_chapter=arc.end_chapter,
            arc_goal=arc.arc_goal, core_conflict=arc.core_conflict,
            main_opposition=arc.main_opposition, entry_hook=arc.entry_hook,
            midpoint_turn=arc.midpoint_turn, climax=arc.climax,
            result=arc.result, next_hook=arc.next_hook,
            related_thread_ids=arc.related_thread_ids or [],
            related_character_ids=arc.related_character_ids or [],
            related_entity_ids=arc.related_entity_ids or [],
            status=arc.status,
        )

    async def update(
        self, db: AsyncSession, arc_id: str, data: OutlineArcUpdate,
    ) -> OutlineArcResponse | None:
        aid = parse_uuid(arc_id, "arc_id")
        arc = await self._repo.update(db, aid, data)
        if arc is None:
            return None
        return OutlineArcResponse.model_validate(arc)

    async def delete(
        self, db: AsyncSession, arc_id: str, novel_id: str,
    ) -> bool:
        aid = parse_uuid(arc_id, "arc_id")
        arc = await self._repo.get(db, aid)
        if arc is None or str(arc.novel_id) != novel_id:
            return False
        return await self._repo.delete(db, aid)


class PlotStructureGenerator:
    """AI 剧情结构生成器"""

    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, Any]:
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest
        from modules.context.facade import compile_structure_context

        bundle = await compile_structure_context(
            db=db, novel_id=novel_id,
            task="生成剧情结构",
            scope="full",
            chapter_index=start_chapter,
            reveal_mode="author_only",
        )

        from core.config import get_settings
        settings = get_settings()

        context_md = ""

        if bundle.project:
            context_md += f"## 项目\n{bundle.project}\n\n"
        if bundle.world_entities:
            context_md += "## 世界对象\n"
            for e in bundle.world_entities:
                context_md += f"- {e.get('name', '?')} ({e.get('entity_type', '?')}): {e.get('summary', '')}\n"
        if bundle.characters:
            context_md += "\n## 人物\n"
            for c in bundle.characters:
                context_md += f"- {c.get('name', '?')} ({c.get('role', '?')}): {c.get('desire', '')}\n"

        system_prompt = load_prompt("structure_plot",
            world_context=context_md,
            user_intent="",
            target_scope=f"章节 {start_chapter}-{end_chapter}",
        )

        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请为章节 {start_chapter}-{end_chapter} 生成剧情结构和篇章大纲。"},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )

        from pydantic import BaseModel

        class _GeneratedThread(BaseModel):
            name: str
            thread_type: str
            summary: str | None = None
            visible_goal: str | None = None
            hidden_truth: str | None = None
            start_chapter: int | None = None
            planned_payoff_chapter: int | None = None
            current_stage: str | None = None
            related_character_names: list[str] = []
            related_entity_names: list[str] = []

        class _GeneratedArc(BaseModel):
            title: str
            arc_index: int | None = None
            start_chapter: int | None = None
            end_chapter: int | None = None
            arc_goal: str | None = None
            core_conflict: str | None = None
            main_opposition: str | None = None
            entry_hook: str | None = None
            midpoint_turn: str | None = None
            climax: str | None = None
            result: str | None = None
            next_hook: str | None = None

        class _GenerationOutput(BaseModel):
            plot_threads: list[_GeneratedThread] = []
            outline_arcs: list[_GeneratedArc] = []

        try:
            result = await LLMClient().generate_structured(request, _GenerationOutput)
        except Exception as exc:
            logger.warning("Plot structure generation failed: %s", exc)
            return {"total_threads": 0, "total_arcs": 0, "threads": [], "arcs": []}

        nid = parse_uuid(novel_id, "novel_id")

        created_threads: list[dict] = []
        for t in result.plot_threads:
            if not t.name:
                continue
            thread_data = PlotThreadCreate(
                name=t.name,
                thread_type=t.thread_type,
                summary=t.summary,
                visible_goal=t.visible_goal,
                hidden_truth=t.hidden_truth,
                start_chapter=t.start_chapter or start_chapter,
                planned_payoff_chapter=t.planned_payoff_chapter,
                current_stage=t.current_stage,
                status="draft",
            )
            try:
                thread = await PlotThreadRepository().create(db, nid, thread_data)
                created_threads.append({"id": str(thread.id), "name": thread.name, "thread_type": thread.thread_type})
            except Exception as exc:
                logger.warning("Failed to create thread '%s': %s", t.name, exc)

        created_arcs: list[dict] = []
        for a in result.outline_arcs:
            if not a.title:
                continue
            arc_data = OutlineArcCreate(
                title=a.title,
                arc_index=a.arc_index,
                start_chapter=a.start_chapter or start_chapter,
                end_chapter=a.end_chapter or end_chapter,
                arc_goal=a.arc_goal,
                core_conflict=a.core_conflict,
                main_opposition=a.main_opposition,
                entry_hook=a.entry_hook,
                midpoint_turn=a.midpoint_turn,
                climax=a.climax,
                result=a.result,
                next_hook=a.next_hook,
                status="draft",
            )
            try:
                arc = await OutlineArcRepository().create(db, nid, arc_data)
                created_arcs.append({"id": str(arc.id), "title": arc.title, "arc_index": arc.arc_index})
            except Exception as exc:
                logger.warning("Failed to create arc '%s': %s", a.title, exc)

        await db.flush()
        return {
            "total_threads": len(created_threads),
            "total_arcs": len(created_arcs),
            "threads": created_threads,
            "arcs": created_arcs,
        }
