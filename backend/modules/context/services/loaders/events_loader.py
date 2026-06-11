"""事件加载器（原 timeline_events_loader — v3 重构重命名）"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class EventsLoader(Loader):
    """加载事件（替代旧的 TimelineEventsLoader）"""

    @property
    def name(self) -> str:
        return "events"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        tl_limit = CONTEXT_BUDGET.get("timeline", 8)

        from modules.world.facade import get_events_context

        entity_ids_for_tl = (
            options.entity_ids
            or [e.get("entity_id", e.get("id", "")) for e in bundle.world_entities]
            or None
        )

        ctx = await get_events_context(
            db,
            options.novel_id,
            limit=tl_limit,
        )
        if ctx and ctx.events:
            bundle.timeline_events = [
                e.model_dump() if hasattr(e, "model_dump") else e for e in ctx.events
            ]
        bundle.budget_used["timeline"] = len(bundle.timeline_events)
