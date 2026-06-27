"""地缘可达性过滤器 — 根据角色位置和地理拓扑过滤 RAG chunk"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class GeoReachabilityFilter:
    """地缘可达性过滤器

    根据 Context Compiler 的编译选项，对 RAG 检索到的 chunk
    执行地缘可达性过滤。不可达的 chunk 降权而非删除，
    保留作者视角上下文。
    """

    UNREACHABLE_WEIGHT_FACTOR: float = 0.3

    async def filter_chunks(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int | None,
        character_ids: list[str],
        chunks: list[dict[str, Any]],
        entity_to_location_map: dict[str, str],
    ) -> list[dict[str, Any]]:
        """对 chunks 执行地缘过滤

        Args:
            db: 数据库 session
            novel_id: 小说项目 ID
            chapter_index: 当前章节索引（None 时跳过过滤）
            character_ids: 关注的人物 ID 列表
            chunks: RAG 检索到的 chunk 列表
            entity_to_location_map: world_entity_id → location_id 映射

        Returns:
            过滤后的 chunk 列表（不可达 chunk 降权）
        """
        if not character_ids or chapter_index is None:
            return chunks

        from modules.character.facade import get_character_location_id

        char_location_id = await get_character_location_id(
            db,
            novel_id,
            character_ids[0],
        )

        if not char_location_id:
            return chunks

        from modules.geo.facade import calculate_route

        filtered: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_entity_ids = chunk.get("entity_ids", [])
            if not chunk_entity_ids:
                filtered.append(chunk)
                continue

            location_ids_to_check = [
                entity_to_location_map[eid]
                for eid in chunk_entity_ids
                if eid in entity_to_location_map
            ]

            if not location_ids_to_check:
                filtered.append(chunk)
                continue

            is_reachable = True
            for target_loc_id in location_ids_to_check:
                if target_loc_id == char_location_id:
                    continue
                try:
                    route = await calculate_route(
                        db,
                        novel_id,
                        char_location_id,
                        target_loc_id,
                        chapter_index,
                    )
                    if not route.is_reachable:
                        is_reachable = False
                        break
                except Exception as exc:
                    logger.warning(
                        "地缘可达性计算异常，保留 chunk: %s",
                        str(exc),
                    )
                    break

            if is_reachable:
                filtered.append(chunk)
            else:
                downweighted = dict(chunk)
                downweighted["importance"] = (
                    chunk.get("importance", 0.5) * self.UNREACHABLE_WEIGHT_FACTOR
                )
                downweighted["geo_filtered"] = True
                filtered.append(downweighted)

        return filtered
