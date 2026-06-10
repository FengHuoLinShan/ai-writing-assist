from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions
from modules.outline.services import OutlineArcService

logger = logging.getLogger(__name__)


class OutlineArcLoader(Loader):
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
            return

        arc = await OutlineArcService().get_by_chapter(db, options.novel_id, chapter)
        if arc is not None:
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
                "status": arc.status,
            }
