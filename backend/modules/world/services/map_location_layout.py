"""地点布局服务。

保存快速创建和用户拖拽后的地图布局节点；默认不修改世界事实。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.map_repositories import MapLocationLayoutRepository
from modules.world.map_schemas import (
    MapLocationLayoutListResponse,
    MapLocationLayoutReplaceRequest,
    MapLocationLayoutResponse,
)
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_context import MapContext


class MapLocationLayoutService:
    """地点布局节点服务。"""

    def __init__(
        self,
        *,
        layout_repo: MapLocationLayoutRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._layout_repo = layout_repo or MapLocationLayoutRepository()
        self._ctx = context or MapContext()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapLocationLayoutListResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        layouts = await self._layout_repo.get_by_map(db, nid, mid)
        return MapLocationLayoutListResponse(
            items=[
                MapLocationLayoutResponse.model_validate(layout) for layout in layouts
            ],
            total=len(layouts),
        )

    async def replace(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapLocationLayoutReplaceRequest,
    ) -> MapLocationLayoutListResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        seen: set[str] = set()
        location_entity_ids: list[str] = []
        values = []
        for item in data.layouts:
            if item.location_entity_id in seen:
                raise ValidationError(
                    "同一地点在同一地图只能有一个布局节点",
                    code="duplicate_location_layout",
                )
            seen.add(item.location_entity_id)
            location_entity_ids.append(item.location_entity_id)
            self._ctx.assert_hex_in_bounds(config, item.center_hex_q, item.center_hex_r)
        await self._ctx.require_entities(
            db,
            novel_id,
            location_entity_ids,
            allowed_types={"location"},
        )
        for item in data.layouts:
            values.append(
                {
                    "location_entity_id": parse_uuid(
                        item.location_entity_id, "location_entity_id"
                    ),
                    "center_hex_q": item.center_hex_q,
                    "center_hex_r": item.center_hex_r,
                    "occupy_radius": item.occupy_radius,
                    "locked": item.locked,
                    "layout_source": item.layout_source,
                    "layout_version": item.layout_version,
                    "sync_geo_setting": item.sync_geo_setting,
                    "meta": item.meta or {},
                }
            )
        layouts = await self._layout_repo.replace_for_map(db, nid, mid, values)
        return MapLocationLayoutListResponse(
            items=[
                MapLocationLayoutResponse.model_validate(layout) for layout in layouts
            ],
            total=len(layouts),
        )
