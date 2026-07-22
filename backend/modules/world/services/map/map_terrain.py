"""手绘地形服务。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
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
    MapTerrainLayerDeleteResponse,
    MapTerrainLayerResponse,
    MapTerrainLayerUpdate,
    MapTerrainPatchReplaceRequest,
    MapTerrainPatchResponse,
    MapTerrainRegionResponse,
    MapTerrainStateResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_revision import MapRevisionService


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
        self._layer_tree = MapLayerTreeService(
            terrain_repo=self._layer_repo,
            context=self._ctx,
        )
        self._revision = MapRevisionService()

    async def get_state(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        include_candidates: bool = False,
    ) -> MapTerrainStateResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        layers = await self._layer_repo.get_by_map(db, nid, mid)
        active_layer_ids = {layer.id for layer in layers}
        regions = [
            row
            for row in await self._region_repo.get_by_map(db, nid, mid)
            if row.layer_id in active_layer_ids
        ]
        active_region_ids = {region.id for region in regions}
        patches = [
            row
            for row in await self._patch_repo.get_by_map(db, nid, mid)
            if row.layer_id in active_layer_ids
        ]
        canonical_owner_bindings = (
            await self._binding_repo.get_by_map_for_entity_statuses(
                db,
                nid,
                mid,
                statuses=["canonical"],
            )
        )
        bindings = [
            binding
            for binding in canonical_owner_bindings
            if binding.review_state == "confirmed"
            and binding.region_id in active_region_ids
        ]
        candidate_bindings = []
        if include_candidates:
            pending_owner_bindings = (
                await self._binding_repo.get_by_map_for_entity_statuses(
                    db,
                    nid,
                    mid,
                    statuses=["draft", "candidate"],
                )
            )
            pending_owner_ids = {binding.id for binding in pending_owner_bindings}
            candidate_bindings = [
                binding
                for binding in [*canonical_owner_bindings, *pending_owner_bindings]
                if binding.region_id in active_region_ids
                and (
                    binding.review_state in {"candidate", "needs_review"}
                    or (
                        binding.id in pending_owner_ids
                        and binding.review_state != "ignored"
                    )
                )
            ]
        return MapTerrainStateResponse(
            layers=[MapTerrainLayerResponse.model_validate(layer) for layer in layers],
            regions=[
                MapTerrainRegionResponse.model_validate(region) for region in regions
            ],
            patches=[MapTerrainPatchResponse.model_validate(patch) for patch in patches],
            bindings=[
                MapTerrainBindingResponse.model_validate(binding) for binding in bindings
            ],
            candidate_bindings=[
                MapTerrainBindingResponse.model_validate(binding)
                for binding in candidate_bindings
            ],
        )

    async def replace_layer_patches(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
        data: MapTerrainPatchReplaceRequest,
        *,
        bump_revision: bool = True,
    ) -> MapTerrainStateResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
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
            await self._layer_tree.assert_writable(
                db, novel_id, map_id, layer_key="terrainOverlay"
            )
            layer = await self._layer_repo.create(
                db,
                nid,
                mid,
                {"id": lid, "status": "active", **data.layer.model_dump()},
            )
            lid = layer.id
            await self._layer_tree.create_terrain_leaf(db, novel_id, map_id, str(lid))
        else:
            if layer.status != "active":
                raise ConflictError(
                    "已归档地形图层不能编辑，请先恢复",
                    code="map_terrain_layer_archived",
                )
            await self._layer_tree.assert_writable(
                db,
                novel_id,
                map_id,
                terrain_layer_id=lid,
                error_code="map_terrain_layer_locked",
            )

        existing_regions = await self._region_repo.get_by_map(db, nid, mid)
        existing_regions_by_id = {region.id: region for region in existing_regions}
        region_ids = {region.id for region in existing_regions if region.layer_id == lid}
        region_values = []
        for region_data in data.regions:
            if parse_uuid(region_data.layer_id, "layer_id") != lid:
                raise ValidationError(
                    "region.layer_id 必须等于当前 layer_id",
                    code="invalid_terrain_region_layer",
                )
            region_id = (
                parse_uuid(region_data.id, "region_id") if region_data.id else None
            )
            if region_id is not None:
                existing_region = existing_regions_by_id.get(region_id)
                if existing_region is None:
                    foreign_region = await self._region_repo.get(db, region_id)
                    if foreign_region is not None:
                        raise NotFoundError(
                            f"地形区域 {region_data.id} 不存在",
                            code="map_terrain_region_not_found",
                        )
                elif existing_region.layer_id != lid:
                    await self._layer_tree.assert_writable(
                        db,
                        novel_id,
                        map_id,
                        terrain_layer_id=existing_region.layer_id,
                        error_code="map_terrain_layer_locked",
                    )
                    raise ValidationError(
                        "地形区域不能跨图层迁移",
                        code="invalid_terrain_region_layer",
                    )
            region_values.append(
                {
                    **({"id": region_id} if region_id else {}),
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
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return await self.get_state(db, novel_id, map_id)

    async def update_layer(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
        data: MapTerrainLayerUpdate,
        *,
        bump_revision: bool = True,
    ) -> MapTerrainLayerResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        if not bump_revision:
            await self._revision.lock_visual_write(db, map_id)
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(layer_id, "layer_id")
        layer = await self._layer_repo.get_in_map(db, nid, mid, lid)
        if layer is None:
            raise NotFoundError(
                f"地形图层 {layer_id} 不存在",
                code="map_terrain_layer_not_found",
            )
        if layer.status != "active":
            raise ConflictError(
                "已归档地形图层不能编辑，请先恢复",
                code="map_terrain_layer_archived",
            )
        values = data.model_dump(exclude_unset=True)
        explicit_unlock_only = values == {"locked": False}
        if not explicit_unlock_only:
            await self._layer_tree.assert_writable(
                db,
                novel_id,
                map_id,
                terrain_layer_id=lid,
                error_code="map_terrain_layer_locked",
            )
        layer_values = {
            key: value
            for key, value in values.items()
            if key in {"terrain_asset_key", "meta"}
        }
        if layer_values:
            await self._layer_repo.update(db, layer, layer_values)
        if any(
            key in values for key in {"name", "opacity", "z_index", "visible", "locked"}
        ):
            await self._layer_tree.update_terrain_leaf_from_legacy(
                db, novel_id, map_id, layer_id, values
            )
        updated = await self._layer_repo.get_in_map(db, nid, mid, lid)
        assert updated is not None
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return MapTerrainLayerResponse.model_validate(updated)

    async def delete_layer(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
        *,
        bump_revision: bool = True,
    ) -> MapTerrainLayerDeleteResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(layer_id, "layer_id")
        layer = await self._layer_repo.get_in_map(db, nid, mid, lid)
        if layer is None:
            raise NotFoundError(
                f"地形图层 {layer_id} 不存在",
                code="map_terrain_layer_not_found",
            )
        await self._layer_tree.assert_writable(
            db,
            novel_id,
            map_id,
            terrain_layer_id=lid,
            error_code="map_terrain_layer_locked",
        )
        regions = [
            region
            for region in await self._region_repo.get_by_map(db, nid, mid)
            if region.layer_id == lid
        ]
        region_ids = {region.id for region in regions}
        patches = [
            patch
            for patch in await self._patch_repo.get_by_map(db, nid, mid)
            if patch.layer_id == lid
        ]
        bindings = [
            binding
            for binding in await self._binding_repo.get_by_map(db, nid, mid)
            if binding.region_id in region_ids
        ]
        if layer.status == "archived":
            return MapTerrainLayerDeleteResponse(
                deleted_layer_id=str(lid),
                deleted_regions=len(regions),
                deleted_patches=len(patches),
                deleted_bindings=len(bindings),
            )
        meta = dict(layer.meta or {})
        meta["archive_state"] = {"visible": layer.visible}
        await self._layer_repo.update(
            db,
            layer,
            {
                "status": "archived",
                "archived_at": datetime.now(UTC),
                "meta": meta,
            },
        )
        await self._layer_tree.update_terrain_leaf_from_legacy(
            db,
            novel_id,
            map_id,
            layer_id,
            {"visible": False},
        )
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
                operation="terrain_layer_archive",
            )
        return MapTerrainLayerDeleteResponse(
            deleted_layer_id=str(lid),
            deleted_regions=len(regions),
            deleted_patches=len(patches),
            deleted_bindings=len(bindings),
        )

    async def restore_layer(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        layer_id: str,
        *,
        bump_revision: bool = True,
    ) -> MapTerrainLayerResponse:
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        lid = parse_uuid(layer_id, "layer_id")
        layer = await self._layer_repo.get_in_map(db, nid, mid, lid)
        if layer is None:
            raise NotFoundError(
                f"地形图层 {layer_id} 不存在",
                code="map_terrain_layer_not_found",
            )
        if layer.status == "active":
            return MapTerrainLayerResponse.model_validate(layer)
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
        await self._ctx.require_map(db, novel_id, map_id)
        await self._layer_tree.assert_writable(
            db,
            novel_id,
            map_id,
            layer_key="terrainOverlay",
        )
        regions = [
            row
            for row in await self._region_repo.get_by_map(db, nid, mid)
            if row.layer_id == lid
        ]
        region_ids = {row.id for row in regions}
        try:
            for binding in await self._binding_repo.get_by_map(db, nid, mid):
                if (
                    binding.region_id in region_ids
                    and binding.review_state == "confirmed"
                ):
                    await self._ctx.require_canonical_entity(
                        db,
                        novel_id,
                        str(binding.location_entity_id),
                        allowed_types={"location"},
                    )
        except (NotFoundError, ValidationError) as exc:
            raise ConflictError(
                "地形图层引用的地点已不可用，无法恢复",
                code="map_terrain_restore_dependency_conflict",
            ) from exc
        archive_state = dict((layer.meta or {}).get("archive_state") or {})
        visible = bool(archive_state.get("visible", True))
        next_meta = dict(layer.meta or {})
        next_meta.pop("archive_state", None)
        await self._layer_repo.update(
            db,
            layer,
            {
                "status": "active",
                "archived_at": None,
                "meta": next_meta,
            },
        )
        await self._layer_tree.update_terrain_leaf_from_legacy(
            db,
            novel_id,
            map_id,
            layer_id,
            {"visible": visible},
        )
        restored = await self._layer_repo.get_in_map(db, nid, mid, lid)
        assert restored is not None
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
                operation="terrain_layer_restore",
            )
        return MapTerrainLayerResponse.model_validate(restored)

    async def create_binding(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapTerrainBindingCreate,
        *,
        bump_revision: bool = True,
    ) -> MapTerrainBindingResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
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
        await self._layer_tree.assert_writable(
            db,
            novel_id,
            map_id,
            terrain_layer_id=region.layer_id,
            error_code="map_terrain_layer_locked",
        )
        require_location = (
            self._ctx.require_canonical_entity
            if data.review_state == "confirmed"
            else self._ctx.require_entity
        )
        await require_location(
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
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return MapTerrainBindingResponse.model_validate(binding)

    async def update_binding(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        binding_id: str,
        data: MapTerrainBindingUpdate,
        *,
        bump_revision: bool = True,
    ) -> MapTerrainBindingResponse:
        locked_config = (
            await self._revision.lock_active(db, novel_id, map_id)
            if bump_revision
            else None
        )
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
        region = await self._region_repo.get_in_map(db, nid, mid, existing.region_id)
        if region is None:
            raise NotFoundError("地形区域不存在", code="map_terrain_region_not_found")
        await self._layer_tree.assert_writable(
            db,
            novel_id,
            map_id,
            terrain_layer_id=region.layer_id,
            error_code="map_terrain_layer_locked",
        )
        next_review_state = data.review_state or existing.review_state
        if next_review_state == "confirmed":
            await self._ctx.require_canonical_entity(
                db,
                novel_id,
                str(existing.location_entity_id),
                allowed_types={"location"},
            )
        values = data.model_dump(exclude_unset=True)
        updated = await self._binding_repo.update(db, existing, values)
        assert updated is not None
        if bump_revision:
            await self._revision.bump(
                db,
                novel_id,
                map_id,
                locked_config=locked_config,
            )
        return MapTerrainBindingResponse.model_validate(updated)
