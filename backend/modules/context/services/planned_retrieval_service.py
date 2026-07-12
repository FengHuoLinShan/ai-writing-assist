"""Focused context planner execution for non-compiler consumers."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader


class PlannedContextRetrievalService:
    def __init__(self, loader: RagChunksLoader | None = None) -> None:
        self._loader = loader or RagChunksLoader()

    async def retrieve(
        self,
        db: AsyncSession,
        options: CompileOptions,
    ) -> StructureContextBundle:
        bundle = StructureContextBundle(
            novel_id=options.novel_id,
            task=options.task,
            scope=options.scope,
            chapter_index=options.chapter_index,
            budget_used={key: 0 for key in CONTEXT_BUDGET},
        )
        await self._loader.load(db, options, bundle)
        return bundle
