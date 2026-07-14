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
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_revision import MapRevisionService

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
        self._layer_tree = MapLayerTreeService(context=self._ctx)
        self._revision = MapRevisionService()

    async def batch_update(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTileBatchUpdate,
        *,
        bump_revision: bool = True,
    ) -> list[MapTileResponse]:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        config = await self._ctx.require_map(db, novel_id, map_id)
        await self._layer_tree.assert_writable(
            db, novel_id, map_id, layer_key="baseTerrain"
        )
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
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        tiles = await self._tile_repo.get_by_map(db, nid, mid)
        return [MapTileResponse.model_validate(t) for t in tiles]
