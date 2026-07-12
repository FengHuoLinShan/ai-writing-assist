"""EntityStatsService — 实体统计与自动入库查询服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid


class EntityStatsService:
    """提供实体数量统计与自动入库实体查询。

    从 entity_facade.py 提取，避免 facade 直接写 SQL/ORM。
    """

    def __init__(self, repo: CoreEntityRepository | None = None) -> None:
        self._repo = repo or CoreEntityRepository()

    async def count_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        """统计 novel 的 CoreEntity 数量。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.count_entities(
            db,
            nid,
            status_filter=status_filter,
        )

    async def list_auto_ingested_entities(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        limit: int = 10000,
        status_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """列出自动入库生成的实体，可选按来源章节范围过滤。"""
        nid = parse_uuid(novel_id, "novel_id")
        entities = await self._repo.list_by_novel(db, nid, limit=limit)

        items: list[dict[str, Any]] = []
        allowed_statuses = set(status_filter or ("canonical", "draft"))
        for entity in entities:
            if entity.status not in allowed_statuses:
                continue
            content_json = entity.content_json or {}
            meta = content_json.get("_meta") or {}
            if not meta.get("auto_ingested"):
                continue
            source = meta.get("source_chapter_index")
            if start_chapter is not None and end_chapter is not None:
                if source is None:
                    continue
                try:
                    source_index = int(source)
                except (ValueError, TypeError):
                    continue
                if not (start_chapter <= source_index <= end_chapter):
                    continue
            items.append(
                {
                    "id": str(entity.id),
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                    "summary": entity.summary,
                    "status": entity.status,
                    "content_json": content_json,
                }
            )
        return items

    async def deprecate_deep_import_entities_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Soft-deprecate auto-ingested entities created by one workflow."""
        nid = parse_uuid(novel_id, "novel_id")
        return await self._repo.deprecate_deep_import_entities_by_workflow(
            db,
            nid,
            workflow_id,
        )
