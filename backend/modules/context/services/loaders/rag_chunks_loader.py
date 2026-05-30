"""RAG 检索片段加载器"""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CONTEXT_BUDGET, StructureContextBundle
from modules.context.services.loaders.geo_filter import GeoReachabilityFilter
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class RagChunksLoader(Loader):
    """加载 RAG 检索片段"""

    def __init__(self, geo_filter: GeoReachabilityFilter | None = None) -> None:
        self._geo_filter = geo_filter or GeoReachabilityFilter()

    @property
    def name(self) -> str:
        return "rag_chunks"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        rag_limit = CONTEXT_BUDGET.get("rag_chunks", 8)

        rag_visibility: str | None = None
        if options.reveal_mode == "reader":
            rag_visibility = "reader_known"

        from modules.rag.facade import retrieve

        result = await retrieve(
            db, options.novel_id,
            query=options.task,
            entity_ids=options.entity_ids,
            character_ids=options.character_ids,
            chapter_index=options.chapter_index,
            visibility=rag_visibility,
            top_k=rag_limit,
            reference_chapter_index=options.chapter_index,
        )
        if result and result.chunks:
            bundle.rag_chunks = [
                c.model_dump() if hasattr(c, "model_dump") else asdict(c)
                for c in result.chunks
            ]

        # --- Character Knowledge Filter ---
        if (
            options.reveal_mode == "character"
            and options.viewpoint_character_id is not None
            and bundle.rag_chunks
        ):
            try:
                from modules.character.facade import get_unknown_target_ids

                unknown = await get_unknown_target_ids(
                    db, options.novel_id, options.viewpoint_character_id,
                )
                unknown_entity_set = set(unknown.get("entity_ids", []))
                unknown_char_set = set(unknown.get("character_ids", []))

                if unknown_entity_set or unknown_char_set:
                    filtered: list[dict] = []
                    removed_count = 0
                    for chunk in bundle.rag_chunks:
                        chunk_entities = set(chunk.get("entity_ids", []))
                        chunk_chars = set(chunk.get("character_ids", []))
                        if (chunk_entities & unknown_entity_set) or (
                            chunk_chars & unknown_char_set
                        ):
                            removed_count += 1
                            continue
                        filtered.append(chunk)

                    if removed_count > 0:
                        logger.debug(
                            "角色知识过滤：移除了 %d/%d 个 chunk（角色 %s）",
                            removed_count,
                            len(bundle.rag_chunks),
                            options.viewpoint_character_id,
                        )
                    bundle.rag_chunks = filtered
            except Exception as exc:
                logger.warning(
                    "角色知识过滤失败，使用未过滤结果: %s",
                    str(exc),
                )

        if (
            options.enable_geo_filter
            and options.character_ids
            and options.chapter_index is not None
            and bundle.rag_chunks
        ):
            entity_to_location = self._build_entity_to_location_map(bundle)
            try:
                bundle.rag_chunks = await self._geo_filter.filter_chunks(
                    db=db,
                    novel_id=options.novel_id,
                    chapter_index=options.chapter_index,
                    character_ids=options.character_ids,
                    chunks=bundle.rag_chunks,
                    entity_to_location_map=entity_to_location,
                )
                bundle.geo_filtered = True
            except Exception as exc:
                logger.warning("地缘过滤执行异常，跳过过滤: %s", str(exc))

        bundle.budget_used["rag_chunks"] = len(bundle.rag_chunks)

    @staticmethod
    def _build_entity_to_location_map(
        bundle: StructureContextBundle,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for loc_ctx in bundle.geo_locations:
            loc_data = loc_ctx.get("location") if isinstance(loc_ctx, dict) else None
            if loc_data is None:
                continue
            entity_id = RagChunksLoader._read_value(
                loc_data, "entity_id", "world_entity_id", "id",
            )
            location_id = RagChunksLoader._read_value(
                loc_data, "entity_id", "id",
            )
            if entity_id and location_id:
                mapping[str(entity_id)] = str(location_id)
        return mapping

    @staticmethod
    def _read_value(source: object, *keys: str) -> object | None:
        if isinstance(source, dict):
            for key in keys:
                value = source.get(key)
                if value:
                    return value
            return None
        for key in keys:
            value = getattr(source, key, None)
            if value:
                return value
        return None
