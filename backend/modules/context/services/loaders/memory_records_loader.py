"""长期记忆加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class MemoryRecordsLoader(Loader):
    """加载长期记忆"""

    @property
    def name(self) -> str:
        return "memory_records"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        mem_limit = CONTEXT_BUDGET.get("memory", 10)

        from modules.memory.facade import get_recent_story_memory

        records = await get_recent_story_memory(
            db,
            options.novel_id,
            before_chapter_index=options.chapter_index,
            limit=mem_limit,
        )
        if records:
            bundle.memory_records = [
                r.model_dump() if hasattr(r, "model_dump") else r for r in records
            ]
        bundle.budget_used["memory"] = len(bundle.memory_records)
