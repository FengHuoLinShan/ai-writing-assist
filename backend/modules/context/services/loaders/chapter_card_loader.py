"""章节卡加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class ChapterCardLoader(Loader):
    """加载章节卡"""

    @property
    def name(self) -> str:
        return "chapter_card"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        if options.chapter_index is not None:
            from modules.outline.facade import get_chapter_card

            card = await get_chapter_card(db, options.novel_id, options.chapter_index)
            if card:
                bundle.chapter_card = (
                    card.model_dump() if hasattr(card, "model_dump") else card
                )
