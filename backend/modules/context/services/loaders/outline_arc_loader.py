"""篇章纲加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class OutlineArcLoader(Loader):
    """加载篇章纲"""

    @property
    def name(self) -> str:
        return "outline_arc"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        arc_id = options.arc_id
        if not arc_id and options.chapter_index is not None:
            from modules.outline.facade import get_chapter_card

            card = await get_chapter_card(db, options.novel_id, options.chapter_index)
            if card and card.arc_id:
                arc_id = card.arc_id

        if arc_id:
            from modules.outline.facade import get_arc_context

            try:
                arc = await get_arc_context(db, options.novel_id, arc_id)
                bundle.outline_arc = (
                    arc.model_dump() if hasattr(arc, "model_dump") else arc
                )
            except Exception:
                pass
