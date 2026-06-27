"""时间线事件加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class TimelineEventsLoader(Loader):
    """加载时间线事件"""

    @property
    def name(self) -> str:
        return "timeline_events"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        tl_limit = CONTEXT_BUDGET.get("timeline", 8)

        from modules.timeline.facade import get_relevant_timeline_context

        entity_ids_for_tl = (
            options.entity_ids
            or [e.get("entity_id", e.get("id", "")) for e in bundle.world_entities]
            or None
        )

        events = await get_relevant_timeline_context(
            db,
            options.novel_id,
            chapter_index=options.chapter_index,
            related_entity_ids=entity_ids_for_tl,
            limit=tl_limit,
        )
        if events:
            bundle.timeline_events = [
                e.model_dump() if hasattr(e, "model_dump") else e for e in events
            ]
        bundle.budget_used["timeline"] = len(bundle.timeline_events)
