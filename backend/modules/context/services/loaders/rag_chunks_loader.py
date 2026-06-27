"""RAG 检索片段加载器"""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class RagChunksLoader(Loader):
    """加载 RAG 检索片段"""

    @property
    def name(self) -> str:
        return "rag_chunks"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        rag_limit = options.top_k or CONTEXT_BUDGET.get("rag_chunks", 8)

        rag_visibility: str | None = None
        if options.reveal_mode == "reader":
            rag_visibility = "reader_known"

        from modules.rag.facade import retrieve

        result = await retrieve(
            db,
            options.novel_id,
            query=options.task,
            entity_ids=options.entity_ids,
            character_ids=options.character_ids,
            chapter_index=options.chapter_index,
            visibility=rag_visibility,
            top_k=rag_limit,
            reference_chapter_index=options.chapter_index,
        )
        if result and result.chunks:
            capped = result.chunks[:rag_limit]
            bundle.rag_chunks = [
                c.model_dump() if hasattr(c, "model_dump") else asdict(c) for c in capped
            ]

        bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)
