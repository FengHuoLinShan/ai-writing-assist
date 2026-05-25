"""剧情线加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class PlotThreadsLoader(Loader):
    """加载剧情线"""

    @property
    def name(self) -> str:
        return "plot_threads"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        from modules.outline.facade import get_active_threads

        threads = await get_active_threads(
            db, options.novel_id,
            chapter_index=options.chapter_index,
            limit=10,
        )
        if threads:
            bundle.plot_threads = [
                t.model_dump() if hasattr(t, "model_dump") else t
                for t in threads
            ]
