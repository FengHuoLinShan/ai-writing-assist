"""Map state assembly.

Concentrates the aggregate map state shape behind one internal module so map
rules do not leak into API routes or cross-module callers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapConfigRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapTerritoryRepository,
    MapTileRepository,
)
from modules.world.map_schemas import (
    MapConfigResponse,
    MapLocationBindingResponse,
    MapMarkerResponse,
    MapStateResponse,
    MapTerritoryResponse,
    MapTileResponse,
)
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_context import MapContext

SceneLookup = Callable[[AsyncSession, str, str], Awaitable[Any | None]]


async def _default_scene_lookup(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> Any | None:
    from modules.outline.facade import get_scene_contract

    return await get_scene_contract(db, novel_id, scene_id)


class MapStateAssembler:
    """Build the stable map-state response used by the frontend map view."""

    def __init__(
        self,
        *,
        config_repo: MapConfigRepository | None = None,
        tile_repo: MapTileRepository | None = None,
        binding_repo: MapLocationBindingRepository | None = None,
        marker_repo: MapMarkerRepository | None = None,
        territory_repo: MapTerritoryRepository | None = None,
        ctx: MapContext | None = None,
        scene_lookup: SceneLookup | None = None,
    ) -> None:
        self._config_repo = config_repo or MapConfigRepository()
        self._tile_repo = tile_repo or MapTileRepository()
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._marker_repo = marker_repo or MapMarkerRepository()
        self._territory_repo = territory_repo or MapTerritoryRepository()
        self._ctx = ctx or MapContext()
        self._scene_lookup = scene_lookup or _default_scene_lookup

    async def assemble(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        filter_types: str = "all",
        scene_id: str | None = None,
    ) -> MapStateResponse:
        """Aggregate map, tiles, bindings, markers, territories, and Scene info."""
        del filter_types  # Kept for the public service/API contract.

        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

        breadcrumbs = await self._config_repo.get_breadcrumbs(db, mid)
        tiles = await self._tile_repo.get_by_map(db, nid, mid)
        bindings = await self._binding_repo.get_by_map(db, nid, mid)
        territories = await self._territory_repo.get_by_map(db, nid, mid)

        sid = parse_uuid(scene_id, "scene_id") if scene_id else None
        scene_info = None
        scene_index = None
        if scene_id:
            scene = await self._scene_lookup(db, novel_id, scene_id)
            if scene is not None:
                scene_index = scene.scene_index
                scene_info = {
                    "id": str(scene.id),
                    "index": scene.scene_index,
                    "title": scene.title,
                    "chapter_title": None,
                }

        markers = await self._marker_repo.get_by_map_and_scene(
            db, nid, mid, scene_id=sid, scene_index=scene_index
        )

        return MapStateResponse(
            map=MapConfigResponse.model_validate(config),
            breadcrumbs=[MapConfigResponse.model_validate(b) for b in breadcrumbs],
            tiles=[MapTileResponse.model_validate(t) for t in tiles],
            location_bindings=[
                MapLocationBindingResponse.model_validate(b) for b in bindings
            ],
            markers=[MapMarkerResponse.model_validate(m) for m in markers],
            territories=[MapTerritoryResponse.model_validate(t) for t in territories],
            scene=scene_info,
        )
