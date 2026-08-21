"""事件加载器（原 timeline_events_loader — v3 重构重命名）"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.evidence.compilation.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetEventsContextFn = Callable[..., Awaitable[Any]]


async def _default_get_events_context(*args: Any, **kwargs: Any) -> Any:
    from modules.world.facade import get_events_context

    return await get_events_context(*args, **kwargs)


class EventsLoader(Loader):
    """加载事件（替代旧的 TimelineEventsLoader）"""

    def __init__(
        self,
        get_events_context_fn: _GetEventsContextFn = _default_get_events_context,
    ) -> None:
        self._get_events_context = get_events_context_fn

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

        ctx = await self._get_events_context(
            db,
            options.novel_id,
            limit=tl_limit,
        )
        if ctx and ctx.events:
            bundle.timeline_events = [
                e.model_dump() if hasattr(e, "model_dump") else e for e in ctx.events
            ]
        bundle.budget_used["timeline"] = len(bundle.timeline_events)
