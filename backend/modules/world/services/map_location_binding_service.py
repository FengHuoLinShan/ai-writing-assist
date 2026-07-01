from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapLocationBindingRepository,
)
from modules.world.map_schemas import (
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationBindingUpdate,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_context import MapContext

logger = logging.getLogger(__name__)


class MapLocationBindingService:
    """地点绑定服务：批量创建 + 中心点唯一性 + 单条 CRUD。"""

    def __init__(
        self,
        binding_repo: MapLocationBindingRepository | None = None,
        entity_repo: CoreEntityRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._ctx = context or MapContext()

    async def batch_create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapLocationBindingCreate,
    ) -> list[MapLocationBindingResponse]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._ctx.require_entity(
            db, novel_id, data.location_entity_id, allowed_types={"location"}
        )
        for h in data.hexes:
            self._ctx.assert_hex_in_bounds(config, h.hex_q, h.hex_r)

        eid = parse_uuid(data.location_entity_id, "location_entity_id")
        mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")

        # 中心点冲突：若新增含 is_center=true，先清旧中心
        has_new_center = any(h.is_center for h in data.hexes)
        if has_new_center:
            await self._binding_repo.clear_center(db, mid, eid)

        hexes = [
            {
                "hex_q": h.hex_q,
                "hex_r": h.hex_r,
                "is_center": h.is_center,
                "label_override": h.label_override,
                "style_override": h.style_override or {},
            }
            for h in data.hexes
        ]
        objs = await self._binding_repo.bulk_create(db, nid, mid, eid, hexes)
        return [MapLocationBindingResponse.model_validate(o) for o in objs]

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        binding_id: str,
        data: MapLocationBindingUpdate,
    ) -> MapLocationBindingResponse:
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")

        binding = await self._binding_repo.get(db, bid)
        if binding is None or binding.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapLocationBinding {binding_id} not found",
            )

        # 切换中心点：清同 location 的其他中心
        if data.is_center is True and not binding.is_center:
            await self._binding_repo.clear_center(
                db, binding.map_id, binding.location_entity_id
            )

        values: dict[str, Any] = {}
        for field in ("is_center", "label_override", "style_override"):
            value = getattr(data, field, None)
            if value is not None:
                values[field] = value

        updated = await self._binding_repo.update(db, bid, values)
        assert updated is not None
        return MapLocationBindingResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        binding_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")

        binding = await self._binding_repo.get(db, bid)
        if binding is None or binding.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapLocationBinding {binding_id} not found",
            )
        await self._binding_repo.delete(db, bid)
