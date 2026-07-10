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
    MapLocationLayoutRepository,
    MapMarkerRepository,
    MapTerrainBindingRepository,
    MapTerrainLayerRepository,
    MapTerrainPatchRepository,
    MapTerrainRegionRepository,
    MapTerritoryRepository,
    MapTileRepository,
)
from modules.world.map_schemas import (
    MapConfigResponse,
    MapDynamicStateResponse,
    MapLocationBindingResponse,
    MapLocationLayoutResponse,
    MapMarkerResponse,
    MapStateResponse,
    MapTerrainBindingResponse,
    MapTerrainLayerResponse,
    MapTerrainPatchResponse,
    MapTerrainRegionResponse,
    MapTerritoryResponse,
    MapTileResponse,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext

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
        layout_repo: MapLocationLayoutRepository | None = None,
        marker_repo: MapMarkerRepository | None = None,
        territory_repo: MapTerritoryRepository | None = None,
        terrain_layer_repo: MapTerrainLayerRepository | None = None,
        terrain_region_repo: MapTerrainRegionRepository | None = None,
        terrain_patch_repo: MapTerrainPatchRepository | None = None,
        terrain_binding_repo: MapTerrainBindingRepository | None = None,
        entity_repo: CoreEntityRepository | None = None,
        ctx: MapContext | None = None,
        scene_lookup: SceneLookup | None = None,
    ) -> None:
        self._config_repo = config_repo or MapConfigRepository()
        self._tile_repo = tile_repo or MapTileRepository()
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._layout_repo = layout_repo or MapLocationLayoutRepository()
        self._marker_repo = marker_repo or MapMarkerRepository()
        self._territory_repo = territory_repo or MapTerritoryRepository()
        self._terrain_layer_repo = terrain_layer_repo or MapTerrainLayerRepository()
        self._terrain_region_repo = terrain_region_repo or MapTerrainRegionRepository()
        self._terrain_patch_repo = terrain_patch_repo or MapTerrainPatchRepository()
        self._terrain_binding_repo = (
            terrain_binding_repo or MapTerrainBindingRepository()
        )
        self._entity_repo = entity_repo or CoreEntityRepository()
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
        layouts = await self._layout_repo.get_by_map(db, nid, mid)
        territories = await self._territory_repo.get_by_map(db, nid, mid)
        terrain_layers = await self._terrain_layer_repo.get_by_map(db, nid, mid)
        terrain_regions = await self._terrain_region_repo.get_by_map(db, nid, mid)
        terrain_patches = await self._terrain_patch_repo.get_by_map(db, nid, mid)
        terrain_bindings = await self._terrain_binding_repo.get_by_map(db, nid, mid)

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
        statuses = await self._load_entity_statuses(
            db,
            nid,
            [
                *(b.location_entity_id for b in bindings),
                *(layout.location_entity_id for layout in layouts),
                *(m.entity_id for m in markers),
                *(t.faction_entity_id for t in territories),
                *(binding.location_entity_id for binding in terrain_bindings),
            ],
        )
        canonical_bindings, candidate_bindings = self._split_by_status(
            bindings, statuses, "location_entity_id"
        )
        canonical_markers, candidate_markers = self._split_by_status(
            markers, statuses, "entity_id"
        )
        canonical_layouts, candidate_layouts = self._split_by_status(
            layouts, statuses, "location_entity_id"
        )
        canonical_territories, candidate_territories = self._split_by_status(
            territories, statuses, "faction_entity_id"
        )
        canonical_owner_terrain, candidate_owner_terrain = self._split_by_status(
            terrain_bindings,
            statuses,
            "location_entity_id",
        )
        canonical_terrain_bindings = [
            binding
            for binding in canonical_owner_terrain
            if binding.review_state == "confirmed"
        ]
        candidate_terrain_bindings = [
            binding
            for binding in canonical_owner_terrain
            if binding.review_state in {"candidate", "needs_review"}
        ] + [
            binding
            for binding in candidate_owner_terrain
            if binding.review_state != "ignored"
        ]

        return MapStateResponse(
            map=MapConfigResponse.model_validate(config),
            breadcrumbs=[MapConfigResponse.model_validate(b) for b in breadcrumbs],
            tiles=[MapTileResponse.model_validate(t) for t in tiles],
            location_bindings=[
                MapLocationBindingResponse.model_validate(b) for b in canonical_bindings
            ],
            location_layouts=[
                MapLocationLayoutResponse.model_validate(layout)
                for layout in canonical_layouts
            ],
            markers=[MapMarkerResponse.model_validate(m) for m in canonical_markers],
            territories=[
                MapTerritoryResponse.model_validate(t) for t in canonical_territories
            ],
            terrain_layers=[
                MapTerrainLayerResponse.model_validate(layer)
                for layer in terrain_layers
            ],
            terrain_regions=[
                MapTerrainRegionResponse.model_validate(region)
                for region in terrain_regions
            ],
            terrain_patches=[
                MapTerrainPatchResponse.model_validate(patch)
                for patch in terrain_patches
            ],
            terrain_bindings=[
                MapTerrainBindingResponse.model_validate(binding)
                for binding in canonical_terrain_bindings
            ],
            candidate_location_bindings=[
                MapLocationBindingResponse.model_validate(b) for b in candidate_bindings
            ],
            candidate_location_layouts=[
                MapLocationLayoutResponse.model_validate(layout)
                for layout in candidate_layouts
            ],
            candidate_markers=[
                MapMarkerResponse.model_validate(m) for m in candidate_markers
            ],
            candidate_territories=[
                MapTerritoryResponse.model_validate(t) for t in candidate_territories
            ],
            candidate_terrain_bindings=[
                MapTerrainBindingResponse.model_validate(binding)
                for binding in candidate_terrain_bindings
            ],
            scene=scene_info,
        )

    async def assemble_dynamic(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        scene_id: str | None = None,
    ) -> MapDynamicStateResponse:
        """Aggregate only Scene-sensitive dynamic map layers."""
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")

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

        candidate_bindings = await self._binding_repo.get_by_map_for_entity_statuses(
            db,
            nid,
            mid,
            statuses=["draft", "candidate"],
        )
        canonical_markers = (
            await self._marker_repo.get_by_map_and_scene_for_entity_statuses(
                db,
                nid,
                mid,
                scene_id=sid,
                scene_index=scene_index,
                statuses=["canonical"],
            )
        )
        candidate_markers = (
            await self._marker_repo.get_by_map_and_scene_for_entity_statuses(
                db,
                nid,
                mid,
                scene_id=sid,
                scene_index=scene_index,
                statuses=["draft", "candidate"],
            )
        )
        canonical_territories = (
            await self._territory_repo.get_by_map_for_entity_statuses(
                db,
                nid,
                mid,
                statuses=["canonical"],
            )
        )
        candidate_territories = (
            await self._territory_repo.get_by_map_for_entity_statuses(
                db,
                nid,
                mid,
                statuses=["draft", "candidate"],
            )
        )

        return MapDynamicStateResponse(
            markers=[MapMarkerResponse.model_validate(m) for m in canonical_markers],
            territories=[
                MapTerritoryResponse.model_validate(t) for t in canonical_territories
            ],
            candidate_location_bindings=[
                MapLocationBindingResponse.model_validate(b) for b in candidate_bindings
            ],
            candidate_markers=[
                MapMarkerResponse.model_validate(m) for m in candidate_markers
            ],
            candidate_territories=[
                MapTerritoryResponse.model_validate(t) for t in candidate_territories
            ],
            scene=scene_info,
        )

    async def _load_entity_statuses(
        self,
        db: AsyncSession,
        novel_id: Any,
        entity_ids: list[Any],
    ) -> dict[Any, str]:
        unique_ids = [
            entity_id for entity_id in set(entity_ids) if entity_id is not None
        ]
        entities = await self._entity_repo.get_by_ids(db, novel_id, unique_ids)
        return {entity.id: entity.status for entity in entities}

    def _split_by_status(
        self,
        rows: list[Any],
        statuses: dict[Any, str],
        entity_attr: str,
    ) -> tuple[list[Any], list[Any]]:
        canonical: list[Any] = []
        candidate: list[Any] = []
        for row in rows:
            status = statuses.get(getattr(row, entity_attr))
            if status == "canonical":
                canonical.append(row)
            elif status in {"draft", "candidate"}:
                candidate.append(row)
        return canonical, candidate
