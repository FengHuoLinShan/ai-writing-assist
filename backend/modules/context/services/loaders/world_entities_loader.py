"""世界对象加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import AUTHOR_ONLY_WARNING, CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class WorldEntitiesLoader(Loader):
    """加载世界对象，按重要性排序并受 budget 限制"""

    @property
    def name(self) -> str:
        return "world_entities"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        core_limit = CONTEXT_BUDGET.get("core_entities", 8)
        normal_limit = CONTEXT_BUDGET.get("normal_entities", 8)

        if options.entity_ids:
            from modules.world.facade import get_world_context

            all_limit = core_limit + normal_limit
            limited_ids = options.entity_ids[:all_limit]
            ctx = await get_world_context(
                db, options.novel_id,
                entity_ids=limited_ids,
                reveal_mode=options.reveal_mode,
                limit=all_limit,
            )
            entities = [e.model_dump() for e in ctx.entities] if ctx else []
            bundle.world_entities = entities
            bundle.budget_used["core_entities"] = min(len(entities), core_limit)
            bundle.budget_used["normal_entities"] = max(0, len(entities) - core_limit)
        else:
            from modules.world.facade import get_world_context

            ctx = await get_world_context(
                db, options.novel_id,
                reveal_mode=options.reveal_mode,
                limit=core_limit + normal_limit,
            )
            entities = [e.model_dump() for e in ctx.entities] if ctx else []
            entities.sort(key=lambda e: e.get("importance", 0.0), reverse=True)

            core_entities = [
                e for e in entities
                if e.get("importance_level") == "core"
                or e.get("importance", 0.0) >= 0.75
            ][:core_limit]
            normal_entities = [
                e for e in entities if e not in core_entities
            ][:normal_limit]

            bundle.world_entities = core_entities + normal_entities
            bundle.budget_used["core_entities"] = len(core_entities)
            bundle.budget_used["normal_entities"] = len(normal_entities)

        # Reveal 过滤
        if options.reveal_mode == "author_safe":
            for ent in bundle.world_entities:
                if ent.get("hidden_truth"):
                    ent["hidden_truth"] = f"{AUTHOR_ONLY_WARNING} {ent['hidden_truth']}"
