from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class PlotThreadsLoader(Loader):
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
        thread_svc = _container_get("outline.thread_service")
        threads = await thread_svc.get_active(
            db, options.novel_id, chapter,
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
