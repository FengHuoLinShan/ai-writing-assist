"""人物信息加载器（含知识边界过滤）"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class CharactersLoader(Loader):
    """加载人物信息，对首个人物执行知识边界过滤"""

    @property
    def name(self) -> str:
        return "characters"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        char_limit = CONTEXT_BUDGET.get("characters", 6)

        if options.character_ids:
            limited_ids = options.character_ids[:char_limit]
        else:
            limited_ids = await self._infer_character_ids(db, options, char_limit)

        if limited_ids:
            from modules.character.facade import get_characters_context

            ctx = await get_characters_context(
                db,
                options.novel_id,
                character_ids=limited_ids,
                reveal_mode=options.reveal_mode,
            )
            if ctx:
                bundle.characters = [c.model_dump() for c in ctx.characters]

        # 知识边界过滤
        if limited_ids and bundle.world_entities and options.scope != "project":
            from modules.character.facade import filter_context_by_character_knowledge

            try:
                filtered = await filter_context_by_character_knowledge(
                    db,
                    options.novel_id,
                    limited_ids[0],
                    bundle.world_entities,
                )
                if filtered is not None:
                    bundle.world_entities = filtered
            except Exception:
                pass

        bundle.budget_used["characters"] = len(bundle.characters)

    async def _infer_character_ids(
        self,
        db: AsyncSession,
        options: CompileOptions,
        limit: int,
    ) -> list[str]:
        """推断相关人物 ID"""
        char_ids: list[str] = []

        if options.chapter_index is not None:
            from modules.outline.facade import get_chapter_card

            card = await get_chapter_card(db, options.novel_id, options.chapter_index)
            if card and card.involved_character_ids:
                char_ids.extend(card.involved_character_ids)

        if not char_ids and options.arc_id is not None:
            from modules.outline.facade import get_arc_context

            try:
                arc = await get_arc_context(db, options.novel_id, options.arc_id)
                if arc and arc.related_character_ids:
                    char_ids.extend(arc.related_character_ids)
            except Exception:
                pass

        return char_ids[:limit]
