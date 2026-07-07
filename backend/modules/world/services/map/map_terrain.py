"""手绘地形服务。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.world.map_repositories import (
    MapTerrainBindingRepository,
    MapTerrainLayerRepository,
    MapTerrainPatchRepository,
    MapTerrainRegionRepository,
)
from modules.world.map_schemas import (
    MapTerrainBindingCreate,
    MapTerrainBindingResponse,
    MapTerrainBindingUpdate,
    MapTerrainLayerResponse,
    MapTerrainPatchReplaceRequest,
    MapTerrainPatchResponse,
    MapTerrainRegionResponse,
    MapTerrainStateResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext


class MapTerrainService:
    """手绘地形图层、patch 与绑定服务。"""

    def __init__(
        self,
        *,
        layer_repo: MapTerrainLayerRepository | None = None,
        region_repo: MapTerrainRegionRepository | None = None,
        patch_repo: MapTerrainPatchRepository | None = None,
        binding_repo: MapTerrainBindingRepository | None = None,
        context: MapContext | None = None,
    ) -> None:
        self._layer_repo = layer_repo or MapTerrainLayerRepository()
        self._region_repo = region_repo or MapTerrainRegionRepository()
        self._patch_repo = patch_repo or MapTerrainPatchRepository()
        self._binding_repo = binding_repo or MapTerrainBindingRepository()
        self._ctx = context or MapContext()

    async def get_state(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapTerrainStateResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        layers = await self._layer_repo.get_by_map(db, nid, mid)
        regions = await self._region_repo.get_by_map(db, nid, mid)
        patches = await self._patch_repo.get_by_map(db, nid, mid)
        bindings = await self._binding_repo.get_by_map(db, nid, mid)
        return MapTerrainStateResponse(
            layers=[MapTerrainLayerResponse.model_validate(layer) for layer in layers],
            regions=[
                MapTerrainRegionResponse.model_validate(region) for region in regions
            ],
            patches=[MapTerrainPatchResponse.model_validate(patch) for patch in patches],
            bindings=[
                MapTerrainBindingResponse.model_validate(binding)
                for binding in bindings
            ],
        )

    async def replace_layer_patches(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
        data: MapTerrainPatchReplaceRequest,
    ) -> MapTerrainStateResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(layer_id, "layer_id")
        layer = await self._layer_repo.get_in_map(db, nid, mid, lid)
        if layer is None:
            if data.layer is None:
                raise NotFoundError(
                    f"地形图层 {layer_id} 不存在",
                    code="map_terrain_layer_not_found",
                )
            layer = await self._layer_repo.create(
                db,
                nid,
                mid,
                {"id": lid, **data.layer.model_dump()},
            )
            lid = layer.id

        existing_regions = await self._region_repo.get_by_map(db, nid, mid)
        region_ids = {region.id for region in existing_regions if region.layer_id == lid}
        region_values = []
        for region_data in data.regions:
            if parse_uuid(region_data.layer_id, "layer_id") != lid:
                raise ValidationError(
                    "region.layer_id 必须等于当前 layer_id",
                    code="invalid_terrain_region_layer",
                )
            region_values.append(
                {
                    **(
                        {"id": parse_uuid(region_data.id, "region_id")}
                        if region_data.id
                        else {}
                    ),
                    "layer_id": lid,
                    "name": region_data.name,
                    "region_status": region_data.region_status,
                    "meta": region_data.meta or {},
                },
            )
        for region in await self._region_repo.upsert_many(
            db,
            nid,
            mid,
            region_values,
        ):
            region_ids.add(region.id)

        patch_values = []
        for patch in data.patches:
            rid = parse_uuid(patch.region_id, "region_id")
            if rid not in region_ids:
                raise ValidationError(
                    f"地形区域 {patch.region_id} 不属于当前图层",
                    code="invalid_terrain_region",
                )
            self._ctx.assert_hex_in_bounds(config, patch.hex_q, patch.hex_r)
            patch_values.append(
                {
                    "region_id": rid,
                    "hex_q": patch.hex_q,
                    "hex_r": patch.hex_r,
                    "strength": patch.strength,
                    "brush_source": patch.brush_source,
                }
            )
        await self._patch_repo.replace_for_layer(db, nid, mid, lid, patch_values)
        return await self.get_state(db, novel_id, map_id)

    async def create_binding(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTerrainBindingCreate,
    ) -> MapTerrainBindingResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        rid = parse_uuid(data.region_id, "region_id")
        region = await self._region_repo.get_in_map(db, nid, mid, rid)
        if region is None:
            raise NotFoundError(
                f"地形区域 {data.region_id} 不存在",
                code="map_terrain_region_not_found",
            )
        await self._ctx.require_entity(
            db,
            novel_id,
            data.location_entity_id,
            allowed_types={"location"},
        )
        binding = await self._binding_repo.create(
            db,
            nid,
            mid,
            {
                "region_id": rid,
                "location_entity_id": parse_uuid(
                    data.location_entity_id, "location_entity_id"
                ),
                "binding_type": data.binding_type,
                "review_state": data.review_state,
                "source": data.source,
                "meta": data.meta or {},
            },
        )
        return MapTerrainBindingResponse.model_validate(binding)

    async def update_binding(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        binding_id: str,
        data: MapTerrainBindingUpdate,
    ) -> MapTerrainBindingResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        bid = parse_uuid(binding_id, "binding_id")
        mid = parse_uuid(map_id, "map_id")
        existing = await self._binding_repo.get(db, bid)
        if existing is None or existing.novel_id != nid or existing.map_id != mid:
            raise NotFoundError(
                f"地形绑定 {binding_id} 不存在",
                code="map_terrain_binding_not_found",
            )
        values = data.model_dump(exclude_unset=True)
        updated = await self._binding_repo.update(db, existing, values)
        assert updated is not None
        return MapTerrainBindingResponse.model_validate(updated)
