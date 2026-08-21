from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetThreadsForContextFn = Callable[..., Awaitable[Any]]


async def _default_get_threads_for_context(
    db: AsyncSession,
    novel_id: str,
    *,
    thread_ids: list[str] | None = None,
    chapter_index: int | None = None,
) -> Any:
    from modules.outline.facade import get_plot_threads_for_context

    return await get_plot_threads_for_context(
        db,
        novel_id,
        thread_ids=thread_ids,
        chapter_index=chapter_index,
    )


class PlotThreadsLoader(Loader):
    def __init__(
        self,
        get_threads_for_context_fn: _GetThreadsForContextFn = (
            _default_get_threads_for_context
        ),
    ) -> None:
        self._get_threads_for_context = get_threads_for_context_fn

    @property
    def name(self) -> str:
        return "plot_threads"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        selected_ids = list(dict.fromkeys(str(item) for item in options.thread_ids or []))
        scene = bundle.scene if isinstance(bundle.scene, dict) else {}
        chapter_index = options.chapter_index or scene.get("chapter_index")
        if chapter_index is None and not selected_ids:
            bundle.plot_threads = []
            bundle.budget_used["plot_threads"] = 0
            return
        threads = await self._get_threads_for_context(
            db,
            options.novel_id,
            thread_ids=selected_ids,
            chapter_index=chapter_index,
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
                "related_character_ids": list(t.related_character_ids or []),
                "related_entity_ids": list(t.related_entity_ids or []),
                "reader_known_state": t.reader_known_state,
                "author_known_state": t.author_known_state,
                "status": t.status,
            }
            for t in threads
        ]
        bundle.budget_used["plot_threads"] = len(bundle.plot_threads)
