from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.map_repositories import (
    MapLocationBindingRepository,
)
from modules.world.map_schemas import (
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationBindingUpdate,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext

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
        return await self.batch_create_many(db, novel_id, map_id, [data])

    async def batch_create_many(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        items: list[MapLocationBindingCreate],
    ) -> list[MapLocationBindingResponse]:
        if not items:
            return []
        config = await self._ctx.require_map(db, novel_id, map_id)
        mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")
        location_ids = [
            parse_uuid(item.location_entity_id, "location_entity_id")
            for item in items
        ]
        unique_location_ids = list(dict.fromkeys(location_ids))
        entities = await self._entity_repo.get_by_ids(db, nid, unique_location_ids)
        entities_by_id = {entity.id: entity for entity in entities}
        for location_id in unique_location_ids:
            entity = entities_by_id.get(location_id)
            if entity is None:
                raise NotFoundError(
                    f"实体 {location_id} 不存在",
                    code="entity_not_found",
                )
            if entity.entity_type != "location":
                raise ValidationError(
                    f"实体 {entity.name} 类型为 {entity.entity_type}，"
                    "只接受 location 类型",
                    code="invalid_entity_type",
                )

        center_location_ids: list[Any] = []
        bindings: list[dict[str, Any]] = []
        for item, location_id in zip(items, location_ids):
            for h in item.hexes:
                self._ctx.assert_hex_in_bounds(config, h.hex_q, h.hex_r)
                if h.is_center:
                    center_location_ids.append(location_id)
                bindings.append(
                    {
                        "location_entity_id": location_id,
                        "hex_q": h.hex_q,
                        "hex_r": h.hex_r,
                        "is_center": h.is_center,
                        "label_override": h.label_override,
                        "style_override": h.style_override or {},
                    }
                )

        # 中心点冲突：若新增含 is_center=true，先批量清旧中心
        await self._binding_repo.clear_centers(db, mid, center_location_ids)

        objs = await self._binding_repo.bulk_create_many(db, nid, mid, bindings)
        return [MapLocationBindingResponse.model_validate(o) for o in objs]

    async def clear_map(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> int:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        return await self._binding_repo.delete_for_map(db, nid, mid)

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
            raise NotFoundError(
                f"MapLocationBinding {binding_id} not found",
                code="map_binding_not_found",
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

        updated = await self._binding_repo.update(db, binding, values)
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
            raise NotFoundError(
                f"MapLocationBinding {binding_id} not found",
                code="map_binding_not_found",
            )
        await self._binding_repo.delete(db, bid)
