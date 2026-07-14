from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.map_repositories import (
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    MapTerritoryCreate,
    MapTerritoryResponse,
    MapTerritoryUpdate,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_revision import MapRevisionService

logger = logging.getLogger(__name__)


class MapTerritoryService:
    """势力范围服务（P2）。"""

    def __init__(
        self,
        territory_repo: MapTerritoryRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self.repo = territory_repo or MapTerritoryRepository()
        self._ctx = context or MapContext()
        self._layer_tree = MapLayerTreeService(context=self._ctx)
        self._revision = MapRevisionService()

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> list[MapTerritoryResponse]:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        territories = await self.repo.get_by_map_for_entity_statuses(
            db,
            nid,
            mid,
            statuses=["canonical"],
        )
        return [MapTerritoryResponse.model_validate(t) for t in territories]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTerritoryCreate,
        *,
        bump_revision: bool = True,
    ) -> list[MapTerritoryResponse]:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._layer_tree.assert_writable(
            db, novel_id, map_id, layer_key="territory"
        )
        await self._ctx.require_canonical_entity(
            db, novel_id, data.faction_entity_id, allowed_types={"organization"}
        )
        for h in data.hexes:
            self._ctx.assert_hex_in_bounds(config, h.hex_q, h.hex_r)

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(data.faction_entity_id, "faction_entity_id")
        hexes = [
            {
                "hex_q": h.hex_q,
                "hex_r": h.hex_r,
                "style_override": h.style_override or {},
            }
            for h in data.hexes
        ]
        tiles = await self.repo.create_batch(db, nid, mid, fid, hexes)
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return [MapTerritoryResponse.model_validate(t) for t in tiles]

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
        data: MapTerritoryUpdate,
        *,
        map_id: str | None = None,
        bump_revision: bool = True,
    ) -> MapTerritoryResponse:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = (
            await self.repo.get_in_map(
                db,
                nid,
                parse_uuid(map_id, "map_id"),
                tid,
            )
            if map_id
            else await self.repo.get(db, tid)
        )
        if territory is None or territory.novel_id != nid:
            raise NotFoundError(
                f"MapTerritoryTile {territory_id} not found",
                code="map_territory_not_found",
            )
        resolved_map_id = map_id or str(territory.map_id)
        locked_config = (
            await self._revision.lock_active(db, novel_id, resolved_map_id)
            if bump_revision
            else None
        )
        await self._ctx.require_canonical_entity(
            db,
            novel_id,
            str(territory.faction_entity_id),
            allowed_types={"organization"},
        )
        await self._layer_tree.assert_writable(
            db, novel_id, resolved_map_id, layer_key="territory"
        )

        values: dict[str, Any] = {}
        if data.style_override is not None:
            values["style_override"] = data.style_override

        updated = await self.repo.update(db, territory, values)
        assert updated is not None
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                resolved_map_id,
                locked_config=locked_config,
            )
        return MapTerritoryResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
        *,
        map_id: str | None = None,
        bump_revision: bool = True,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = (
            await self.repo.get_in_map(
                db,
                nid,
                parse_uuid(map_id, "map_id"),
                tid,
            )
            if map_id
            else await self.repo.get(db, tid)
        )
        if territory is None or territory.novel_id != nid:
            raise NotFoundError(
                f"MapTerritoryTile {territory_id} not found",
                code="map_territory_not_found",
            )
        resolved_map_id = map_id or str(territory.map_id)
        locked_config = (
            await self._revision.lock_active(db, novel_id, resolved_map_id)
            if bump_revision
            else None
        )
        await self._layer_tree.assert_writable(
            db, novel_id, resolved_map_id, layer_key="territory"
        )
        await self.repo.delete(db, tid)
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                resolved_map_id,
                locked_config=locked_config,
            )

    async def delete_by_faction(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        faction_entity_id: str,
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
            db, novel_id, map_id, layer_key="territory"
        )
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(faction_entity_id, "faction_entity_id")

        deleted = await self.repo.delete_by_faction(db, nid, mid, fid)
        if bump_revision and deleted:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return deleted
