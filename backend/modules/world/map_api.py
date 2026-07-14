"""
World 动态地图 API 路由 — PRD docs/PRD-动态地图功能.md

独立 router（prefix=/api/world/maps），由 app.main include。
满足 PRD §7.1 "注册到 /api/world 命名空间" 要求，同时保持 map_*.py 文件独立性。
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.map_schemas import (
    MapArchiveImpactResponse,
    MapArchiveResponse,
    MapBatchActionRequest,
    MapBatchActionResponse,
    MapConfigCreate,
    MapConfigListResponse,
    MapConfigResponse,
    MapConfigUpdate,
    MapDashboardResponse,
    MapDynamicStateAtResponse,
    MapDynamicStateResponse,
    MapDynamicTimelineResponse,
    MapEditorApplyRequest,
    MapEditorApplyResponse,
    MapFactListResponse,
    MapFactResponse,
    MapFactStatusUpdate,
    MapLayerTreeResponse,
    MapLocationBindingCreate,
    MapLocationBindingResponse,
    MapLocationBindingUpdate,
    MapLocationLayoutListResponse,
    MapLocationLayoutReplaceRequest,
    MapMarkerCreate,
    MapMarkerResponse,
    MapMarkerUpdate,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationReviewUpdate,
    MapOpenTarget,
    MapPathArchiveImpactResponse,
    MapPathResponse,
    MapPathStateResponse,
    MapPlaybackResponse,
    MapQuickCreateConfirmRequest,
    MapQuickCreateConfirmResponse,
    MapQuickCreateContextResponse,
    MapQuickCreatePreviewRequest,
    MapQuickCreatePreviewResponse,
    MapRestoreRequest,
    MapRestoreResponse,
    MapSceneSummaryResponse,
    MapStateResponse,
    MapTerrainBindingCreate,
    MapTerrainBindingResponse,
    MapTerrainBindingUpdate,
    MapTerrainLayerDeleteResponse,
    MapTerrainLayerResponse,
    MapTerrainLayerUpdate,
    MapTerrainPatchReplaceRequest,
    MapTerrainStateResponse,
    MapTerritoryCreate,
    MapTerritoryResponse,
    MapTerritoryUpdate,
    MapTileBatchUpdate,
    MapTileResponse,
)
from modules.world.services.map.map_archive import MapArchiveService
from modules.world.services.map.map_editor_apply import MapEditorApplyService
from modules.world.services.map.map_layer_tree import MapLayerTreeService
from modules.world.services.map.map_location_layout import MapLocationLayoutService
from modules.world.services.map.map_path import MapPathService
from modules.world.services.map.map_quick_create import MapQuickCreateService
from modules.world.services.map.map_scene_summary import MapSceneSummaryService
from modules.world.services.map.map_terrain import MapTerrainService
from modules.world.services.map_service import (
    MapConfigService,
    MapDynamicFactService,
    MapLocationBindingService,
    MapMarkerService,
    MapTerritoryService,
    MapTileService,
)

router = APIRouter(prefix="/api/world/maps", tags=["world-map"])

_map_config_service = MapConfigService()
_map_tile_service = MapTileService()
_map_binding_service = MapLocationBindingService()
_marker_service = MapMarkerService()
_territory_service = MapTerritoryService()
_scene_summary_service = MapSceneSummaryService()
_dynamic_fact_service = MapDynamicFactService()
_layout_service = MapLocationLayoutService()
_quick_create_service = MapQuickCreateService()
_terrain_service = MapTerrainService()
_archive_service = MapArchiveService()
_editor_apply_service = MapEditorApplyService()
_layer_tree_service = MapLayerTreeService()
_path_service = MapPathService()


async def _require_active_novel_id(
    db: DbSession,
    novel_id: NovelIdQuery,
) -> str:
    await require_active_project(db, novel_id)
    return novel_id


ActiveNovelIdQuery = Annotated[str, Depends(_require_active_novel_id)]


# ============================================================
# 地图管理（PRD §6.1）
# ============================================================


@router.get("", response_model=MapConfigListResponse)
async def list_maps(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    parent_map_id: str | None = Query(None, description="父地图 ID（空=顶层）"),
    status: Literal["active", "archived"] = Query("active"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> MapConfigListResponse:
    return await _map_config_service.list(
        db,
        novel_id,
        parent_map_id=parent_map_id,
        status=status,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=MapConfigResponse, status_code=201)
async def create_map(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: MapConfigCreate = ...,
) -> MapConfigResponse:
    return await _map_config_service.create(db, novel_id, data)


@router.get("/scene-summary", response_model=MapSceneSummaryResponse)
async def get_scene_summary(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str = Query(..., description="Scene ID"),
) -> MapSceneSummaryResponse:
    """写作页 Scene 地图摘要。"""
    return await _scene_summary_service.summarize(db, novel_id, scene_id)


@router.get("/open-target", response_model=MapOpenTarget)
async def get_map_open_target(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str | None = Query(None, description="Scene ID"),
    focus_entity_id: str | None = Query(None, description="聚焦对象 ID"),
) -> MapOpenTarget:
    """为写作页和世界对象页生成稳定地图打开目标。"""
    return await _dynamic_fact_service.get_open_target(
        db,
        novel_id,
        scene_id=scene_id,
        focus_entity_id=focus_entity_id,
    )


@router.get("/quick-create/context", response_model=MapQuickCreateContextResponse)
async def get_quick_create_context(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_candidates: bool = Query(False, description="是否包含待处理观察"),
) -> MapQuickCreateContextResponse:
    return await _quick_create_service.context(
        db,
        novel_id,
        include_candidates=include_candidates,
    )


@router.post("/quick-create/preview", response_model=MapQuickCreatePreviewResponse)
async def preview_quick_create_map(
    db: DbSession,
    data: MapQuickCreatePreviewRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapQuickCreatePreviewResponse:
    return await _quick_create_service.preview(db, novel_id, data)


@router.post(
    "/quick-create/confirm",
    response_model=MapQuickCreateConfirmResponse,
    status_code=201,
)
async def confirm_quick_create_map(
    db: DbSession,
    data: MapQuickCreateConfirmRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapQuickCreateConfirmResponse:
    return await _quick_create_service.confirm(db, novel_id, data)


@router.get("/{map_id}", response_model=MapConfigResponse)
async def get_map(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapConfigResponse:
    return await _map_config_service.get(db, map_id, novel_id=novel_id)


@router.patch("/{map_id}", response_model=MapConfigResponse)
async def update_map(
    db: DbSession,
    map_id: str,
    data: MapConfigUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapConfigResponse:
    return await _map_config_service.update(db, map_id, data, novel_id=novel_id)


@router.delete("/{map_id}", status_code=204)
async def delete_map(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _map_config_service.delete(db, map_id, novel_id=novel_id)


@router.get(
    "/{map_id}/archive-impact",
    response_model=MapArchiveImpactResponse,
)
async def get_map_archive_impact(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapArchiveImpactResponse:
    return await _archive_service.impact(db, novel_id, map_id)


@router.post("/{map_id}/archive", response_model=MapArchiveResponse)
async def archive_map(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapArchiveResponse:
    return await _archive_service.archive(db, novel_id, map_id)


@router.post("/{map_id}/restore", response_model=MapRestoreResponse)
async def restore_map(
    db: DbSession,
    map_id: str,
    data: MapRestoreRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapRestoreResponse:
    return await _archive_service.restore(db, novel_id, map_id, data)


@router.post("/{map_id}/editor/apply", response_model=MapEditorApplyResponse)
async def apply_map_editor_commands(
    db: DbSession,
    map_id: str,
    data: MapEditorApplyRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapEditorApplyResponse:
    return await _editor_apply_service.apply(db, novel_id, map_id, data)


@router.get("/{map_id}/layer-tree", response_model=MapLayerTreeResponse)
async def get_map_layer_tree(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapLayerTreeResponse:
    return await _layer_tree_service.get_tree(db, novel_id, map_id)


@router.get("/{map_id}/paths", response_model=MapPathStateResponse)
async def get_map_paths(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    status: Literal["active", "archived", "all"] = Query("active"),
) -> MapPathStateResponse:
    return await _path_service.get_state(
        db,
        novel_id,
        map_id,
        status=status,
    )


@router.get("/{map_id}/paths/{path_id}", response_model=MapPathResponse)
async def get_map_path(
    db: DbSession,
    map_id: str,
    path_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapPathResponse:
    return await _path_service.get_path(db, novel_id, map_id, path_id)


@router.get(
    "/{map_id}/paths/{path_id}/archive-impact",
    response_model=MapPathArchiveImpactResponse,
)
async def get_map_path_archive_impact(
    db: DbSession,
    map_id: str,
    path_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapPathArchiveImpactResponse:
    return await _path_service.archive_impact(db, novel_id, map_id, path_id)


@router.post("/{map_id}/generate", response_model=MapStateResponse)
async def generate_map_terrain(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
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
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str | None = Query(None, description="Scene ID"),
    filter_types: str = Query("all", description="筛选类型：all / location"),
) -> MapStateResponse:
    return await _map_config_service.get_state(
        db, novel_id, map_id, filter_types=filter_types, scene_id=scene_id
    )


@router.get("/{map_id}/state/dynamic", response_model=MapDynamicStateResponse)
async def get_map_dynamic_state(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str | None = Query(None, description="Scene ID"),
) -> MapDynamicStateResponse:
    return await _map_config_service.get_dynamic_state(
        db,
        novel_id,
        map_id,
        scene_id=scene_id,
    )


@router.get("/{map_id}/dashboard", response_model=MapDashboardResponse)
async def get_map_dashboard(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str | None = Query(None, description="Scene ID"),
    focus_entity_id: str | None = Query(None, description="聚焦对象 ID"),
    focus_item_id: str | None = Query(None, description="聚焦动态项 ID"),
) -> MapDashboardResponse:
    return await _dynamic_fact_service.get_dashboard(
        db,
        novel_id,
        map_id=map_id,
        scene_id=scene_id,
        focus_entity_id=focus_entity_id,
        focus_item_id=focus_item_id,
    )


@router.get("/{map_id}/playback", response_model=MapPlaybackResponse)
async def get_map_playback(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str | None = Query(None, description="Scene ID"),
    focus_entity_id: str | None = Query(None, description="聚焦对象 ID"),
    include_candidates: bool = Query(True, description="是否包含待处理观察"),
) -> MapPlaybackResponse:
    return await _dynamic_fact_service.get_playback(
        db,
        novel_id,
        map_id=map_id,
        scene_id=scene_id,
        focus_entity_id=focus_entity_id,
        include_candidates=include_candidates,
    )


@router.get("/{map_id}/timeline", response_model=MapDynamicTimelineResponse)
async def get_map_timeline(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    from_scene_index: int | None = Query(None, ge=0),
    to_scene_index: int | None = Query(None, ge=0),
    focus_entity_id: str | None = Query(None, description="聚焦对象 ID"),
    tracks: str | None = Query(
        None,
        description="逗号分隔的 journey/territory/crisis/resource/status/world",
    ),
    include_candidates: bool = Query(False, description="是否包含待处理覆盖层"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> MapDynamicTimelineResponse:
    selected_tracks = (
        {item.strip() for item in tracks.split(",") if item.strip()}
        if tracks
        else None
    )
    return await _dynamic_fact_service.get_timeline(
        db,
        novel_id,
        map_id=map_id,
        from_scene_index=from_scene_index,
        to_scene_index=to_scene_index,
        focus_entity_id=focus_entity_id,
        tracks=selected_tracks,
        include_candidates=include_candidates,
        skip=skip,
        limit=limit,
    )


@router.get("/{map_id}/state-at", response_model=MapDynamicStateAtResponse)
async def get_map_state_at(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_index: int = Query(..., ge=0),
    focus_entity_id: str | None = Query(None, description="聚焦对象 ID"),
    tracks: str | None = Query(
        None,
        description="逗号分隔的 journey/territory/crisis/resource/status/world",
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> MapDynamicStateAtResponse:
    selected_tracks = (
        {item.strip() for item in tracks.split(",") if item.strip()}
        if tracks
        else None
    )
    return await _dynamic_fact_service.get_state_at(
        db,
        novel_id,
        map_id=map_id,
        scene_index=scene_index,
        focus_entity_id=focus_entity_id,
        tracks=selected_tracks,
        skip=skip,
        limit=limit,
    )


# ============================================================
# 地点布局（快速创建 / 拖拽 / +/-）
# ============================================================


@router.get(
    "/{map_id}/location-layouts",
    response_model=MapLocationLayoutListResponse,
)
async def list_location_layouts(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapLocationLayoutListResponse:
    return await _layout_service.list(db, novel_id, map_id)


@router.put(
    "/{map_id}/location-layouts",
    response_model=MapLocationLayoutListResponse,
)
async def replace_location_layouts(
    db: DbSession,
    map_id: str,
    data: MapLocationLayoutReplaceRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapLocationLayoutListResponse:
    return await _layout_service.replace(db, novel_id, map_id, data)


# ============================================================
# 地形批量编辑（PRD §6.3）
# ============================================================


@router.patch("/{map_id}/tiles", response_model=list[MapTileResponse])
async def batch_update_tiles(
    db: DbSession,
    map_id: str,
    data: MapTileBatchUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[MapTileResponse]:
    return await _map_tile_service.batch_update(db, novel_id, map_id, data)


# ============================================================
# 手绘地形图层
# ============================================================


@router.get("/{map_id}/terrain", response_model=MapTerrainStateResponse)
async def get_terrain_state(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    include_candidates: bool = Query(default=False),
) -> MapTerrainStateResponse:
    return await _terrain_service.get_state(
        db,
        novel_id,
        map_id,
        include_candidates=include_candidates,
    )


@router.patch(
    "/{map_id}/terrain/layers/{layer_id}",
    response_model=MapTerrainLayerResponse,
)
async def update_terrain_layer(
    db: DbSession,
    map_id: str,
    layer_id: str,
    data: MapTerrainLayerUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapTerrainLayerResponse:
    return await _terrain_service.update_layer(
        db,
        novel_id,
        map_id,
        layer_id,
        data,
    )


@router.delete(
    "/{map_id}/terrain/layers/{layer_id}",
    response_model=MapTerrainLayerDeleteResponse,
)
async def delete_terrain_layer(
    db: DbSession,
    map_id: str,
    layer_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapTerrainLayerDeleteResponse:
    return await _terrain_service.delete_layer(db, novel_id, map_id, layer_id)


@router.put(
    "/{map_id}/terrain/layers/{layer_id}/patches",
    response_model=MapTerrainStateResponse,
)
async def replace_terrain_layer_patches(
    db: DbSession,
    map_id: str,
    layer_id: str,
    data: MapTerrainPatchReplaceRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapTerrainStateResponse:
    return await _terrain_service.replace_layer_patches(
        db,
        novel_id,
        map_id,
        layer_id,
        data,
    )


@router.post(
    "/{map_id}/terrain/regions/{region_id}/bindings",
    response_model=MapTerrainBindingResponse,
    status_code=201,
)
async def create_terrain_binding(
    db: DbSession,
    map_id: str,
    region_id: str,
    data: MapTerrainBindingCreate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapTerrainBindingResponse:
    payload = data.model_copy(update={"region_id": region_id})
    return await _terrain_service.create_binding(db, novel_id, map_id, payload)


@router.patch(
    "/{map_id}/terrain/bindings/{binding_id}",
    response_model=MapTerrainBindingResponse,
)
async def update_terrain_binding(
    db: DbSession,
    map_id: str,
    binding_id: str,
    data: MapTerrainBindingUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapTerrainBindingResponse:
    return await _terrain_service.update_binding(
        db,
        novel_id,
        map_id,
        binding_id,
        data,
    )


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
    *,
    novel_id: ActiveNovelIdQuery,
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
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapLocationBindingResponse:
    return await _map_binding_service.update(
        db, novel_id, binding_id, data, map_id=map_id
    )


@router.delete(
    "/{map_id}/location-bindings/{binding_id}",
    status_code=204,
)
async def delete_location_binding(
    db: DbSession,
    map_id: str,
    binding_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _map_binding_service.delete(db, novel_id, binding_id, map_id=map_id)


# ============================================================
# 动态标记（P1）
# ============================================================


@router.get("/{map_id}/markers")
async def list_markers(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    scene_id: str | None = Query(None, description="Scene ID"),
):
    markers = await _marker_service.list(db, novel_id, map_id, scene_id)
    return [MapMarkerResponse.model_validate(m) for m in markers]


@router.post("/{map_id}/markers", status_code=201)
async def create_marker(
    db: DbSession,
    map_id: str,
    data: MapMarkerCreate,
    *,
    novel_id: ActiveNovelIdQuery,
):
    marker = await _marker_service.create(db, novel_id, map_id, data)
    return MapMarkerResponse.model_validate(marker)


@router.patch("/{map_id}/markers/{marker_id}")
async def update_marker(
    db: DbSession,
    map_id: str,
    marker_id: str,
    data: MapMarkerUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
):
    marker = await _marker_service.update(
        db, novel_id, marker_id, data, map_id=map_id
    )
    return MapMarkerResponse.model_validate(marker)


@router.delete("/{map_id}/markers/{marker_id}", status_code=204)
async def delete_marker(
    db: DbSession,
    map_id: str,
    marker_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
):
    await _marker_service.delete(db, novel_id, marker_id, map_id=map_id)


# ============================================================
# 势力范围（P2）
# ============================================================


@router.get("/{map_id}/territories")
async def list_territories(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
):
    territories = await _territory_service.list(db, novel_id, map_id)
    return [MapTerritoryResponse.model_validate(t) for t in territories]


@router.post("/{map_id}/territories", status_code=201)
async def create_territories(
    db: DbSession,
    map_id: str,
    data: MapTerritoryCreate,
    *,
    novel_id: ActiveNovelIdQuery,
):
    territories = await _territory_service.create(db, novel_id, map_id, data)
    return [MapTerritoryResponse.model_validate(t) for t in territories]


@router.patch("/{map_id}/territories/{territory_id}")
async def update_territory(
    db: DbSession,
    map_id: str,
    territory_id: str,
    data: MapTerritoryUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
):
    territory = await _territory_service.update(
        db, novel_id, territory_id, data, map_id=map_id
    )
    return MapTerritoryResponse.model_validate(territory)


@router.delete("/{map_id}/territories/{territory_id}", status_code=204)
async def delete_territory(
    db: DbSession,
    map_id: str,
    territory_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _territory_service.delete(db, novel_id, territory_id, map_id=map_id)


@router.delete("/{map_id}/territories", status_code=204)
async def delete_territories_by_faction(
    db: DbSession,
    map_id: str,
    faction_entity_id: str = Query(..., description="组织实体 ID"),
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _territory_service.delete_by_faction(db, novel_id, map_id, faction_entity_id)


# ============================================================
# 聚焦模式（P2）
# ============================================================


@router.get("/{map_id}/focus", response_model=MapStateResponse)
async def get_focus_mode(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    faction_entity_id: str = Query(..., description="组织实体 ID"),
) -> MapStateResponse:
    """聚焦模式：返回完整地图状态，但只包含指定组织的势力范围。"""
    state = await _map_config_service.get_state(db, novel_id, map_id)
    # Filter territories to only the requested faction
    from modules.world.services.common import parse_uuid

    fid = parse_uuid(faction_entity_id, "faction_entity_id")
    state.territories = [t for t in state.territories if t.faction_entity_id == str(fid)]
    return state


# ============================================================
# 世界动态事实底座（P0）
# ============================================================


@router.get("/{map_id}/observations", response_model=MapObservationListResponse)
async def list_map_observations(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    review_state: str | None = Query(None, description="candidate / confirmed / ignored"),
) -> MapObservationListResponse:
    return await _dynamic_fact_service.list_observations(
        db,
        novel_id,
        map_id=map_id,
        review_state=review_state,
    )


@router.post(
    "/{map_id}/observations",
    response_model=MapObservationResponse,
    status_code=201,
)
async def create_map_observation(
    db: DbSession,
    map_id: str,
    data: MapObservationCreate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapObservationResponse:
    return await _dynamic_fact_service.create_observation(
        db,
        novel_id,
        map_id=map_id,
        data=data,
    )


@router.patch(
    "/{map_id}/observations/{observation_id}",
    response_model=MapObservationResponse,
)
async def update_map_observation_review(
    db: DbSession,
    map_id: str,
    observation_id: str,
    data: MapObservationReviewUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapObservationResponse:
    return await _dynamic_fact_service.update_observation_review(
        db,
        novel_id,
        map_id=map_id,
        observation_id=observation_id,
        data=data,
    )


@router.post(
    "/{map_id}/observations/batch-review",
    response_model=MapObservationBatchReviewResponse,
)
async def batch_review_map_observations(
    db: DbSession,
    map_id: str,
    data: MapObservationBatchReviewRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapObservationBatchReviewResponse:
    return await _dynamic_fact_service.batch_review_observations(
        db,
        novel_id,
        map_id=map_id,
        data=data,
    )


@router.post(
    "/{map_id}/observations/{observation_id}/confirm",
    response_model=MapFactResponse,
)
async def confirm_map_observation(
    db: DbSession,
    map_id: str,
    observation_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapFactResponse:
    return await _dynamic_fact_service.confirm_observation(
        db,
        novel_id,
        map_id=map_id,
        observation_id=observation_id,
    )


@router.post(
    "/{map_id}/observations/{observation_id}/ignore",
    response_model=MapObservationResponse,
)
async def ignore_map_observation(
    db: DbSession,
    map_id: str,
    observation_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapObservationResponse:
    return await _dynamic_fact_service.ignore_observation(
        db,
        novel_id,
        map_id=map_id,
        observation_id=observation_id,
    )


@router.post("/{map_id}/batch-actions", response_model=MapBatchActionResponse)
async def run_map_batch_action(
    db: DbSession,
    map_id: str,
    data: MapBatchActionRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapBatchActionResponse:
    return await _dynamic_fact_service.run_batch_action(
        db,
        novel_id,
        map_id=map_id,
        data=data,
    )


@router.get("/{map_id}/facts", response_model=MapFactListResponse)
async def list_map_facts(
    db: DbSession,
    map_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    fact_status: str | None = Query("confirmed", description="confirmed / rolled_back"),
) -> MapFactListResponse:
    return await _dynamic_fact_service.list_facts(
        db,
        novel_id,
        map_id=map_id,
        fact_status=fact_status,
    )


@router.patch("/{map_id}/facts/{fact_id}", response_model=MapFactResponse)
async def update_map_fact_status(
    db: DbSession,
    map_id: str,
    fact_id: str,
    data: MapFactStatusUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> MapFactResponse:
    return await _dynamic_fact_service.update_fact_status(
        db,
        novel_id,
        map_id=map_id,
        fact_id=fact_id,
        data=data,
    )
