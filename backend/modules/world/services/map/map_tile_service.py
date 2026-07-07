from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapTileRepository,
)
from modules.world.map_schemas import (
    MapTileBatchUpdate,
    MapTileResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext

logger = logging.getLogger(__name__)


class MapTileService:
    """地形批量编辑服务。"""

    def __init__(
        self,
        tile_repo: MapTileRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._tile_repo = tile_repo or MapTileRepository()
        self._ctx = context or MapContext()

    async def batch_update(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTileBatchUpdate,
    ) -> list[MapTileResponse]:
        config = await self._ctx.require_map(db, novel_id, map_id)
        for change in data.changes:
            self._ctx.assert_hex_in_bounds(config, change.hex_q, change.hex_r)

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        changes = [
            {
                "hex_q": c.hex_q,
                "hex_r": c.hex_r,
                "terrain_type": c.terrain_type,
                "elevation": c.elevation,
            }
            for c in data.changes
        ]
        await self._tile_repo.bulk_upsert(db, nid, mid, changes)
        tiles = await self._tile_repo.get_by_map(db, nid, mid)
        return [MapTileResponse.model_validate(t) for t in tiles]
