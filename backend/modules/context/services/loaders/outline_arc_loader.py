from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetArcByChapterFn = Callable[[AsyncSession, str, int], Awaitable[Any]]


async def _default_get_arc_by_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter: int,
) -> Any:
    from core.container import get

    arc_svc = get("outline.arc_service")
    return await arc_svc.get_by_chapter(db, novel_id, chapter)


class OutlineArcLoader(Loader):
    def __init__(
        self,
        get_arc_by_chapter_fn: _GetArcByChapterFn = _default_get_arc_by_chapter,
    ) -> None:
        self._get_arc_by_chapter = get_arc_by_chapter_fn

    @property
    def name(self) -> str:
        return "outline_arc"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        chapter = options.chapter_index
        if chapter is None:
            bundle.budget_used["outline_arc"] = 0
            return

        arc = await self._get_arc_by_chapter(
            db,
            options.novel_id,
            chapter,
        )
        if arc is None:
            bundle.budget_used["outline_arc"] = 0
            return

        bundle.outline_arc = {
            "id": arc.id,
            "title": arc.title,
            "arc_index": arc.arc_index,
            "start_chapter": arc.start_chapter,
            "end_chapter": arc.end_chapter,
            "arc_goal": arc.arc_goal,
            "core_conflict": arc.core_conflict,
            "main_opposition": arc.main_opposition,
            "entry_hook": arc.entry_hook,
            "midpoint_turn": arc.midpoint_turn,
            "climax": arc.climax,
            "result": arc.result,
            "next_hook": arc.next_hook,
            "related_thread_ids": list(getattr(arc, "related_thread_ids", None) or []),
            "related_character_ids": list(
                getattr(arc, "related_character_ids", None) or []
            ),
            "related_entity_ids": list(
                getattr(arc, "related_entity_ids", None) or []
            ),
            "status": arc.status,
        }
        bundle.budget_used["outline_arc"] = 1
