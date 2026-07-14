from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
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
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_revision import MapRevisionService

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
        self._ctx = context or MapContext(entity_repo=self._entity_repo)
        self._layer_tree = MapLayerTreeService(context=self._ctx)
        self._revision = MapRevisionService()

    async def batch_create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapLocationBindingCreate,
        *,
        bump_revision: bool = True,
    ) -> list[MapLocationBindingResponse]:
        return await self.batch_create_many(
            db,
            novel_id,
            map_id,
            [data],
            bump_revision=bump_revision,
        )

    async def batch_create_many(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        items: list[MapLocationBindingCreate],
        *,
        bump_revision: bool = True,
    ) -> list[MapLocationBindingResponse]:
        if not items:
            return []
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._layer_tree.assert_writable(
            db, novel_id, map_id, layer_key="location"
        )
        mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")
        location_ids = [
            parse_uuid(item.location_entity_id, "location_entity_id") for item in items
        ]
        unique_location_ids = list(dict.fromkeys(location_ids))
        await self._ctx.require_canonical_entities(
            db,
            novel_id,
            [str(location_id) for location_id in unique_location_ids],
            allowed_types={"location"},
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
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return [MapLocationBindingResponse.model_validate(o) for o in objs]

    async def clear_map(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        bump_revision: bool = True,
    ) -> int:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        await self._ctx.require_map(db, novel_id, map_id)
        await self._layer_tree.assert_writable(
            db, novel_id, map_id, layer_key="location"
        )
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        deleted = await self._binding_repo.delete_for_map(db, nid, mid)
        if bump_revision and deleted:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return deleted

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        binding_id: str,
        data: MapLocationBindingUpdate,
        *,
        map_id: str | None = None,
        bump_revision: bool = True,
    ) -> MapLocationBindingResponse:
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")

        binding = (
            await self._binding_repo.get_in_map(
                db,
                nid,
                parse_uuid(map_id, "map_id"),
                bid,
            )
            if map_id
            else await self._binding_repo.get(db, bid)
        )
        if binding is None or binding.novel_id != nid:
            raise NotFoundError(
                f"MapLocationBinding {binding_id} not found",
                code="map_binding_not_found",
            )
        resolved_map_id = map_id or str(binding.map_id)
        locked_config = (
            await self._revision.lock_active(db, novel_id, resolved_map_id)
            if bump_revision
            else None
        )
        await self._ctx.require_canonical_entity(
            db,
            novel_id,
            str(binding.location_entity_id),
            allowed_types={"location"},
        )
        await self._layer_tree.assert_writable(
            db, novel_id, resolved_map_id, layer_key="location"
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
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                resolved_map_id,
                locked_config=locked_config,
            )
        return MapLocationBindingResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        binding_id: str,
        *,
        map_id: str | None = None,
        bump_revision: bool = True,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")

        binding = (
            await self._binding_repo.get_in_map(
                db,
                nid,
                parse_uuid(map_id, "map_id"),
                bid,
            )
            if map_id
            else await self._binding_repo.get(db, bid)
        )
        if binding is None or binding.novel_id != nid:
            raise NotFoundError(
                f"MapLocationBinding {binding_id} not found",
                code="map_binding_not_found",
            )
        resolved_map_id = map_id or str(binding.map_id)
        locked_config = (
            await self._revision.lock_active(db, novel_id, resolved_map_id)
            if bump_revision
            else None
        )
        await self._layer_tree.assert_writable(
            db, novel_id, resolved_map_id, layer_key="location"
        )
        await self._binding_repo.delete(db, bid)
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                resolved_map_id,
                locked_config=locked_config,
            )
