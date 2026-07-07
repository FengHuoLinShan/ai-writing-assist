from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetActiveThreadsFn = Callable[[AsyncSession, str, int], Awaitable[Any]]


async def _default_get_active_threads(
    db: AsyncSession,
    novel_id: str,
    chapter: int,
) -> Any:
    from core.container import get

    thread_svc = get("outline.thread_service")
    return await thread_svc.get_active(db, novel_id, chapter)


class PlotThreadsLoader(Loader):
    def __init__(
        self,
        get_active_threads_fn: _GetActiveThreadsFn = _default_get_active_threads,
    ) -> None:
        self._get_active_threads = get_active_threads_fn

    @property
    def name(self) -> str:
        return "plot_threads"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        chapter = options.chapter_index or 1
        threads = await self._get_active_threads(
            db,
            options.novel_id,
            chapter,
        )
        bundle.plot_threads = [
            {
                "id": t.id,
                "name": t.name,
                "thread_type": t.thread_type,
                "summary": t.summary,
                "visible_goal": t.visible_goal,
                "hidden_truth": t.hidden_truth,
                "start_chapter": t.start_chapter,
                "planned_payoff_chapter": t.planned_payoff_chapter,
                "current_stage": t.current_stage,
                "reader_known_state": t.reader_known_state,
                "author_known_state": t.author_known_state,
                "status": t.status,
            }
            for t in threads
        ]
        bundle.budget_used["plot_threads"] = len(bundle.plot_threads)
