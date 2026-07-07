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

    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> list[MapTerritoryResponse]:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        territories = await self.repo.get_by_map(db, nid, mid)
        return [MapTerritoryResponse.model_validate(t) for t in territories]

    async def create(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTerritoryCreate,
    ) -> list[MapTerritoryResponse]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._ctx.require_entity(
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
        return [MapTerritoryResponse.model_validate(t) for t in tiles]

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
        data: MapTerritoryUpdate,
    ) -> MapTerritoryResponse:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = await self.repo.get(db, tid)
        if territory is None or territory.novel_id != nid:
            raise NotFoundError(
                f"MapTerritoryTile {territory_id} not found",
                code="map_territory_not_found",
            )

        values: dict[str, Any] = {}
        if data.style_override is not None:
            values["style_override"] = data.style_override

        updated = await self.repo.update(db, territory, values)
        assert updated is not None
        return MapTerritoryResponse.model_validate(updated)

    async def delete(
        self,
        db: AsyncSession,
        novel_id: str,
        territory_id: str,
    ) -> None:
        nid = parse_uuid(novel_id, "novel_id")
        tid = parse_uuid(territory_id, "territory_id")

        territory = await self.repo.get(db, tid)
        if territory is None or territory.novel_id != nid:
            raise NotFoundError(
                f"MapTerritoryTile {territory_id} not found",
                code="map_territory_not_found",
            )
        await self.repo.delete(db, tid)

    async def delete_by_faction(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        faction_entity_id: str,
    ) -> int:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        fid = parse_uuid(faction_entity_id, "faction_entity_id")

        return await self.repo.delete_by_faction(db, nid, mid, fid)
