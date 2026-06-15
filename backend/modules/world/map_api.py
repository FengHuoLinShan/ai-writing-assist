"""
World 动态地图 API 路由 — PRD docs/PRD-动态地图功能.md

独立 router（prefix=/api/world/maps），由 app.main include。
满足 PRD §7.1 "注册到 /api/world 命名空间" 要求，同时保持 map_*.py 文件独立性。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.world.map_schemas import (
    MapConfigCreate,
    MapConfigListResponse,
    MapConfigResponse,
    MapConfigUpdate,
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationBindingUpdate,
    MapMarkerCreate,
    MapMarkerResponse,
    MapMarkerUpdate,
    MapStateResponse,
    MapTileBatchUpdate,
    MapTileResponse,
)
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
    MapMarkerService,
    MapTileService,
)

router = APIRouter(prefix="/api/world/maps", tags=["world-map"])

_map_config_service = MapConfigService()
_map_tile_service = MapTileService()
_map_binding_service = MapLocationBindingService()
_marker_service = MapMarkerService()


# ============================================================
# 地图管理（PRD §6.1）
# ============================================================


@router.get("", response_model=MapConfigListResponse)
async def list_maps(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    parent_map_id: str | None = Query(None, description="父地图 ID（空=顶层）"),
) -> MapConfigListResponse:
    return await _map_config_service.list(db, novel_id, parent_map_id=parent_map_id)


@router.post("", response_model=MapConfigResponse, status_code=201)
async def create_map(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: MapConfigCreate = ...,
) -> MapConfigResponse:
    return await _map_config_service.create(db, novel_id, data)


@router.get("/{map_id}", response_model=MapConfigResponse)
async def get_map(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> MapConfigResponse:
    return await _map_config_service.get(db, map_id, novel_id=novel_id)


@router.patch("/{map_id}", response_model=MapConfigResponse)
async def update_map(
    db: DbSession,
    map_id: str,
    data: MapConfigUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> MapConfigResponse:
    return await _map_config_service.update(db, map_id, data, novel_id=novel_id)


@router.delete("/{map_id}", status_code=204)
async def delete_map(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _map_config_service.delete(db, map_id, novel_id=novel_id)


@router.post("/{map_id}/generate", response_model=MapStateResponse)
async def generate_map_terrain(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> MapStateResponse:
    """快速生成详图地形（中心 city + 外 road + 随机 grassland/forest）。"""
    return await _map_config_service.generate(db, novel_id, map_id)


# ============================================================
# 地图状态聚合（PRD §6.2）
# ============================================================


@router.get("/{map_id}/state", response_model=MapStateResponse)
async def get_map_state(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    filter_types: str = Query("all", description="筛选类型：all / location"),
) -> MapStateResponse:
    return await _map_config_service.get_state(
        db, novel_id, map_id, filter_types=filter_types
    )


# ============================================================
# 地形批量编辑（PRD §6.3）
# ============================================================


@router.patch("/{map_id}/tiles", response_model=list[MapTileResponse])
async def batch_update_tiles(
    db: DbSession,
    map_id: str,
    data: MapTileBatchUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> list[MapTileResponse]:
    return await _map_tile_service.batch_update(db, novel_id, map_id, data)


# ============================================================
# 地点绑定（PRD §6.4）
# ============================================================


@router.post(
    "/{map_id}/location-bindings",
    response_model=list[MapLocationBindingResponse],
    status_code=201,
)
async def create_location_bindings(
    db: DbSession,
    map_id: str,
    data: MapLocationBindingCreate,
    novel_id: str = Query(..., description="项目 ID"),
) -> list[MapLocationBindingResponse]:
    return await _map_binding_service.batch_create(db, novel_id, map_id, data)


@router.patch(
    "/{map_id}/location-bindings/{binding_id}",
    response_model=MapLocationBindingResponse,
)
async def update_location_binding(
    db: DbSession,
    map_id: str,
    binding_id: str,
    data: MapLocationBindingUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> MapLocationBindingResponse:
    return await _map_binding_service.update(db, novel_id, binding_id, data)


@router.delete(
    "/{map_id}/location-bindings/{binding_id}",
    status_code=204,
)
async def delete_location_binding(
    db: DbSession,
    map_id: str,
    binding_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _map_binding_service.delete(db, novel_id, binding_id)


# ============================================================
# 动态标记（P1）
# ============================================================


@router.get("/{map_id}/markers")
async def list_markers(
    db: DbSession,
    map_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    scene_id: str | None = Query(None, description="Scene ID"),
):
    markers = await _marker_service.list(db, novel_id, map_id, scene_id)
    return [MapMarkerResponse.model_validate(m) for m in markers]


@router.post("/{map_id}/markers", status_code=201)
async def create_marker(
    db: DbSession,
    map_id: str,
    data: MapMarkerCreate,
    novel_id: str = Query(..., description="项目 ID"),
):
    marker = await _marker_service.create(db, novel_id, map_id, data)
    return MapMarkerResponse.model_validate(marker)


@router.patch("/{map_id}/markers/{marker_id}")
async def update_marker(
    db: DbSession,
    map_id: str,
    marker_id: str,
    data: MapMarkerUpdate,
    novel_id: str = Query(..., description="项目 ID"),
):
    marker = await _marker_service.update(db, novel_id, marker_id, data)
    return MapMarkerResponse.model_validate(marker)


@router.delete("/{map_id}/markers/{marker_id}", status_code=204)
async def delete_marker(
    db: DbSession,
    map_id: str,
    marker_id: str,
    novel_id: str = Query(..., description="项目 ID"),
):
    await _marker_service.delete(db, novel_id, marker_id)
