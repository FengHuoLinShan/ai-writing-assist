"""RAG 检索片段加载器"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CONTEXT_BUDGET,
    CompileOptions,
    StructureContextBundle,
    VisibilityContextContract,
)
from modules.context.services.protocol import Loader

logger = logging.getLogger(__name__)

_RetrieveFn = Callable[..., Awaitable[Any]]


async def _default_retrieve(*args: Any, **kwargs: Any) -> Any:
    from modules.rag.facade import retrieve

    return await retrieve(*args, **kwargs)


class RagChunksLoader(Loader):
    """加载 RAG 检索片段"""

    def __init__(self, retrieve_fn: _RetrieveFn = _default_retrieve) -> None:
        self._retrieve = retrieve_fn

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

        strict_scene_filter = (
            options.reveal_mode == "character" and options.scene_id is not None
        )
        # In character reveal, scene_id is both the current Scene anchor and the
        # RAG scene boundary. Full as-of-scene cursors are deferred to a later pass.
        visible_until_chapter = (
            options.visible_until_chapter
            if options.visible_until_chapter is not None
            else options.chapter_index
        )
        result = await self._retrieve(
            db,
            options.novel_id,
            query=options.task,
            content_mode=options.content_mode,
            entity_ids=options.entity_ids,
            character_ids=options.character_ids,
            chapter_index=options.chapter_index,
            scene_id=options.scene_id if strict_scene_filter else None,
            strict_scene_filter=strict_scene_filter,
            visibility=rag_visibility,
            top_k=rag_limit,
            reference_chapter_index=options.chapter_index,
            visible_until_chapter=visible_until_chapter,
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
            bundle.rag_chunks = await self._rehydrate_chunks(
                db,
                options,
                result.chunks[:rag_limit],
                bundle,
                visible_until_chapter=visible_until_chapter,
            )

        bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)

    async def _rehydrate_chunks(
        self,
        db: AsyncSession,
        options: CompileOptions,
        chunks: list,
        bundle: StructureContextBundle,
        *,
        visible_until_chapter: int | None,
    ) -> list[dict]:
        from modules.context.novel_evidence import NovelEvidenceService
        from modules.writing.facade import (
            build_manuscript_range_ref,
            list_manuscript_sources,
        )

        chapters = sorted(
            {
                int(chunk.chapter_index)
                for chunk in chunks
                if getattr(chunk, "chapter_index", None) is not None
            }
        )
        current_sources = await list_manuscript_sources(
            db,
            options.novel_id,
            chapters,
            content_mode=options.content_mode,
        )
        current_by_chapter = {source.chapter_index: source for source in current_sources}
        visibility = VisibilityContextContract(
            mode=(
                options.reveal_mode
                if options.reveal_mode in {"reader", "character"}
                else "author"
            ),
            cutoff_chapter=visible_until_chapter,
            cutoff_scene_id=options.visible_until_scene_id,
            cutoff_offset=options.visible_until_offset,
            character_id=options.viewpoint_character_id,
        )
        evidence = NovelEvidenceService()
        visibility, cursor_warnings = await evidence.resolve_visibility_cursor(
            db,
            novel_id=options.novel_id,
            content_mode=options.content_mode,
            visibility=visibility,
        )
        for warning in cursor_warnings:
            if warning not in bundle.warnings:
                bundle.warnings.append(warning)
        hydrated: list[dict] = []
        for chunk in chunks:
            source = current_by_chapter.get(getattr(chunk, "chapter_index", None))
            if (
                getattr(chunk, "source_type", None) != "chapter_text"
                or source is None
                or not getattr(chunk, "source_id", None)
                or not getattr(chunk, "source_content_hash", None)
                or source.id != chunk.source_id
                or source.content_hash != chunk.source_content_hash
                or chunk.start_offset is None
                or chunk.end_offset is None
            ):
                warning = "RAG 候选未匹配当前正文版本，已剔除"
                if warning not in bundle.warnings:
                    bundle.warnings.append(warning)
                continue
            try:
                source_ref = await build_manuscript_range_ref(
                    db,
                    options.novel_id,
                    draft_id=chunk.source_id,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    content_mode=options.content_mode,
                )
                read = await evidence.read(
                    db,
                    novel_id=options.novel_id,
                    source_ref=source_ref,
                    visibility=visibility,
                    before=0,
                    after=0,
                )
            except Exception:
                warning = "RAG 候选原文引用已失效，已剔除"
                if warning not in bundle.warnings:
                    bundle.warnings.append(warning)
                continue
            raw = chunk.model_dump() if hasattr(chunk, "model_dump") else asdict(chunk)
            raw["text"] = read["text"]
            raw["summary"] = None
            raw["source_ref"] = read["source_ref"]
            raw["scene_refs"] = read["scene_refs"]
            raw["object_refs"] = read["object_refs"]
            hydrated.append(raw)
        return hydrated
