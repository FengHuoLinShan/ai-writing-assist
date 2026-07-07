"""长期记忆加载器 — 基于事件溯源全景"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_GetMemoryPanoramaFn = Callable[[AsyncSession, str, int], Awaitable[Any]]


async def _default_get_memory_panorama(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> Any:
    from modules.memory.facade import get_memory_panorama

    return await get_memory_panorama(db, novel_id, chapter_index)


class MemoryRecordsLoader(Loader):
    """加载长期记忆（世界状态全景）"""

    def __init__(
        self,
        get_memory_panorama_fn: _GetMemoryPanoramaFn = _default_get_memory_panorama,
    ) -> None:
        self._get_memory_panorama = get_memory_panorama_fn

    @property
    def name(self) -> str:
        return "memory_records"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        chapter_index = options.chapter_index or 1
        try:
            panorama = await self._get_memory_panorama(
                db,
                options.novel_id,
                chapter_index,
            )
            # 将全景数据注入 context bundle
            bundle.memory_records = panorama.model_dump()
            bundle.budget_used["memory"] = len(panorama.entities)
        except Exception:
            logger.warning("Failed to load memory panorama", exc_info=True)
            bundle.memory_records = []
            bundle.budget_used["memory"] = 0
