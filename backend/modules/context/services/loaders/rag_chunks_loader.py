"""RAG 检索片段加载器"""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
)
from modules.context.services.protocol import Loader

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

        strict_scene_filter = (
            options.reveal_mode == "character" and options.scene_id is not None
        )
        # In character reveal, scene_id is both the current Scene anchor and the
        # RAG scene boundary. Full as-of-scene cursors are deferred to a later pass.
        result = await retrieve(
            db,
            options.novel_id,
            query=options.task,
            entity_ids=options.entity_ids,
            character_ids=options.character_ids,
            chapter_index=options.chapter_index,
            scene_id=options.scene_id if strict_scene_filter else None,
            strict_scene_filter=strict_scene_filter,
            visibility=rag_visibility,
            top_k=rag_limit,
            reference_chapter_index=options.chapter_index,
        )
        if strict_scene_filter:
            warning = (
                "RAG 已按当前 Scene 严格过滤；无 Scene 标注或其它 Scene 的片段"
                "不会进入角色视角上下文"
            )
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)
        for warning in getattr(result, "warnings", []) or []:
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)
        if getattr(result, "degraded", False) and "RAG 检索降级" not in bundle.warnings:
            bundle.warnings.append("RAG 检索降级")
        if result and result.chunks:
            capped = result.chunks[:rag_limit]
            bundle.rag_chunks = [
                c.model_dump() if hasattr(c, "model_dump") else asdict(c) for c in capped
            ]

        bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)
