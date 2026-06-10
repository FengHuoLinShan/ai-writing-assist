"""长期记忆加载器 — 基于事件溯源全景"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions
from modules.memory.services import MemoryService

logger = logging.getLogger(__name__)

_memory = MemoryService()


class MemoryRecordsLoader(Loader):
    """加载长期记忆（世界状态全景）"""

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
            panorama = await _memory.get_panorama(
                db, options.novel_id, chapter_index,
            )
            # 将全景数据注入 context bundle
            bundle.memory_records = panorama.model_dump()
            bundle.budget_used["memory"] = len(panorama.entities)
        except Exception:
            logger.warning("Failed to load memory panorama", exc_info=True)
            bundle.memory_records = []
            bundle.budget_used["memory"] = 0
