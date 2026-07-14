"""Soft archive and restore complete map subtrees."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.map_models import (
    MapFact,
    MapLayerNode,
    MapLocationBinding,
    MapLocationLayout,
    MapMarker,
    MapObservation,
    MapPath,
    MapPathLayer,
    MapPathNode,
    MapTerrainBinding,
    MapTerrainLayer,
    MapTerrainPatch,
    MapTerrainRegion,
    MapTerritoryTile,
    MapTile,
)
from modules.world.map_repositories import MapConfigRepository
from modules.world.map_schemas import (
    MapArchiveImpactResponse,
    MapArchiveResponse,
    MapConfigResponse,
    MapRestoreRequest,
    MapRestoreResponse,
)
from modules.world.services.common import parse_uuid


class MapArchiveService:
    _ASSETS = {
        "tiles": MapTile,
        "location_bindings": MapLocationBinding,
        "location_layouts": MapLocationLayout,
        "markers": MapMarker,
        "territories": MapTerritoryTile,
        "terrain_layers": MapTerrainLayer,
        "terrain_regions": MapTerrainRegion,
        "terrain_patches": MapTerrainPatch,
        "terrain_bindings": MapTerrainBinding,
        "layer_nodes": MapLayerNode,
        "path_layers": MapPathLayer,
        "paths": MapPath,
        "path_nodes": MapPathNode,
        "observations": MapObservation,
        "facts": MapFact,
    }

    def __init__(self, config_repo: MapConfigRepository | None = None) -> None:
        self._config_repo = config_repo or MapConfigRepository()

    async def _locked_subtree(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ):
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        await self._config_repo.lock_hierarchy(db, nid)
        subtree = await self._config_repo.lock_subtree(db, nid, mid)
        if not subtree:
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        return nid, mid, subtree

    async def impact(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapArchiveImpactResponse:
        nid, mid, subtree = await self._locked_subtree(db, novel_id, map_id)
        root = next(item for item in subtree if item.id == mid)
        if root.novel_id != nid:
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        map_ids = [item.id for item in subtree]
        counts: dict[str, int] = {}
        for key, model in self._ASSETS.items():
            counts[key] = int(
                (
                    await db.execute(
                        select(func.count(model.id)).where(
                            model.novel_id == nid,
                            model.map_id.in_(map_ids),
                        )
                    )
                ).scalar()
                or 0
            )
        return MapArchiveImpactResponse(
            root_map_id=str(mid),
            map_count=len(subtree),
            asset_counts=counts,
        )

    async def archive(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
    ) -> MapArchiveResponse:
        _, mid, subtree = await self._locked_subtree(db, novel_id, map_id)
        root = next(item for item in subtree if item.id == mid)
        if root.status != "active":
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        impact = await self.impact(db, novel_id, map_id)
        archived_at = datetime.now(UTC)
        for config in subtree:
            config.status = "archived"
            config.archived_at = archived_at
            db.add(config)
        await db.flush()
        return MapArchiveResponse(**impact.model_dump())

    async def restore(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        data: MapRestoreRequest,
    ) -> MapRestoreResponse:
        nid, mid, subtree = await self._locked_subtree(db, novel_id, map_id)
        by_id = {item.id: item for item in subtree}
        root = by_id[mid]
        if root.status != "archived":
            raise NotFoundError(f"归档地图 {map_id} 不存在", code="map_not_found")
        if any(item.status != "archived" for item in subtree):
            raise ConflictError(
                "归档子树状态不完整，不能单独恢复后代",
                code="map_archive_subtree_inconsistent",
            )

        if root.parent_map_id is not None and root.parent_map_id not in by_id:
            parent = await self._config_repo.get_in_novel(
                db, nid, root.parent_map_id, status="active", for_update=True
            )
            if parent is None:
                raise ConflictError(
                    "父地图仍在归档中，请先恢复父级子树",
                    code="map_restore_parent_archived",
                )

        next_names = {item.id: item.name for item in subtree}
        if data.root_name:
            next_names[root.id] = data.root_name
        for config in subtree:
            duplicate = await self._config_repo.get_by_name(
                db,
                nid,
                name=next_names[config.id],
                parent_map_id=config.parent_map_id,
            )
            if duplicate is not None and duplicate.id not in by_id:
                raise ConflictError(
                    f"同层级已存在名为 {next_names[config.id]!r} 的地图",
                    code="duplicate_map_name",
                    context={"map_id": str(config.id), "name": next_names[config.id]},
                )

        for config in subtree:
            config.name = next_names[config.id]
            config.status = "active"
            config.archived_at = None
            db.add(config)
        await db.flush()
        return MapRestoreResponse(
            root_map_id=str(root.id),
            restored_map_count=len(subtree),
            map=MapConfigResponse.model_validate(root),
        )
