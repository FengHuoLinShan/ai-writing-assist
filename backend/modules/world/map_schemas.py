"""
World 动态地图 Pydantic Schema — PRD docs/PRD-动态地图功能.md

Create 用 Field(...)，Update 用 Annotated[..., Field(None, ...)]，Response 加 ConfigDict。
UUID 字段统一为 str（用 _uuid_validator 把 ORM 的 UUID 转成 str）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from modules.world.contracts import (
    MapBoundaryProposal as MapBoundaryProposal,
)
from modules.world.contracts import (
    MapCharacterLocationProposal as MapCharacterLocationProposal,
)
from modules.world.contracts import (
    MapEventLocationProposal as MapEventLocationProposal,
)
from modules.world.contracts import (
    MapObservationProposalBase as MapObservationProposalBase,
)
from modules.world.contracts import (
    MapObservationProposalV1,
)
from modules.world.contracts import (
    MapRouteStateProposal as MapRouteStateProposal,
)

# ============================================================
# 类型白名单（PRD §5.5 / §6.1）
# ============================================================

#: 地图类型白名单（PRD §6.1）
MAP_TYPES: tuple[str, ...] = ("world", "city", "region", "dungeon")

#: 地形类型白名单（PRD §5.5，10 种）
TERRAIN_TYPES: tuple[str, ...] = (
    "grassland",
    "forest",
    "desert",
    "mountain",
    "water",
    "city",
    "road",
    "ruin",
    "secret",
    "danger",
)

# ============================================================
# 内部工具
# ============================================================


def _uuid_validator(v: object) -> str:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _optional_uuid_validator(v: object) -> str | None:
    if v is None:
        return None
    return _uuid_validator(v)


# ============================================================
# MapConfig — 地图配置
# ============================================================


class MapConfigCreate(BaseModel):
    """创建地图。novel_id 由 service 注入（per ADR-0002，不在 Create 里）。"""

    name: str = Field(..., min_length=1, max_length=255, description="地图名称")
    map_type: Literal["world", "city", "region", "dungeon"] = Field(
        ...,
        description="地图类型：world / city / region / dungeon（PRD §6.1）",
    )
    description: str | None = Field(None, description="地图描述")
    grid_width: int = Field(..., ge=1, le=200, description="网格宽度")
    grid_height: int = Field(..., ge=1, le=200, description="网格高度")
    hex_size: int = Field(30, ge=4, le=200, description="六边形像素半径")
    parent_map_id: str | None = Field(None, description="父地图 ID（顶层为空）")
    parent_entity_id: str | None = Field(None, description="父地点实体 ID")
    template: str | None = Field(
        None,
        description="初始地形模板：continent / islands / blank（仅 world 类型用）",
    )


class MapConfigUpdate(BaseModel):
    """更新地图配置（部分更新）。"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    description: Annotated[str | None, Field(None)]
    default_center_x: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    default_center_y: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    default_zoom: Annotated[float | None, Field(None)]
    sort_order: Annotated[int | None, Field(None, ge=0)]


class MapConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    name: str
    map_type: str
    description: str | None = None
    default_center_x: float
    default_center_y: float
    default_zoom: float
    grid_width: int
    grid_height: int
    hex_size: int
    parent_map_id: str | None = None
    parent_entity_id: str | None = None
    sort_order: int
    status: Literal["active", "archived"] = "active"
    archived_at: datetime | None = None
    editor_revision: int = 0
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("parent_map_id", "parent_entity_id", mode="before")
    @classmethod
    def _coerce_optional_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)


class MapConfigListResponse(BaseModel):
    items: list[MapConfigResponse]
    total: int


class MapArchiveImpactResponse(BaseModel):
    root_map_id: str
    map_count: int
    asset_counts: dict[str, int] = Field(default_factory=dict)


class MapArchiveResponse(MapArchiveImpactResponse):
    status: Literal["archived"] = "archived"


class MapRestoreRequest(BaseModel):
    root_name: str | None = Field(None, min_length=1, max_length=255)


class MapRestoreResponse(BaseModel):
    root_map_id: str
    restored_map_count: int
    status: Literal["active"] = "active"
    map: MapConfigResponse


# ============================================================
# MapTile — 地形网格
# ============================================================


class MapTileChange(BaseModel):
    """单格地形变更（批量编辑用）。"""

    hex_q: int = Field(..., ge=0, description="轴向坐标 q")
    hex_r: int = Field(..., ge=0, description="轴向坐标 r")
    terrain_type: Literal[
        "grassland",
        "forest",
        "desert",
        "mountain",
        "water",
        "city",
        "road",
        "ruin",
        "secret",
        "danger",
    ] = Field(..., description="新地形（PRD §5.5 白名单）")
    elevation: int | None = Field(None, ge=0, description="新海拔")


class MapTileBatchUpdate(BaseModel):
    """批量地形编辑请求体。"""

    changes: list[MapTileChange] = Field(
        ..., min_length=1, max_length=10000, description="地形变更列表"
    )


class MapTileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    map_id: str
    hex_q: int
    hex_r: int
    terrain_type: str
    elevation: int
    style_override: dict | None = None

    @field_validator("id", "map_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# MapLocationBinding — 地点绑定
# ============================================================


class BindingHex(BaseModel):
    """单格绑定。"""

    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)
    is_center: bool = Field(False, description="是否中心点")
    label_override: str | None = Field(None, max_length=255)
    style_override: dict | None = Field(None)


class MapLocationBindingCreate(BaseModel):
    """批量绑定地点请求体（一个地点绑定多个 hex）。"""

    location_entity_id: str = Field(
        ..., description="地点实体 ID（entity_type=location）"
    )
    hexes: list[BindingHex] = Field(..., min_length=1, max_length=5000)


class MapLocationBindingUpdate(BaseModel):
    """更新单个绑定。"""

    is_center: Annotated[bool | None, Field(None)]
    label_override: Annotated[str | None, Field(None, max_length=255)]
    style_override: Annotated[dict | None, Field(None)]


class MapLocationBindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    map_id: str
    location_entity_id: str
    hex_q: int
    hex_r: int
    is_center: bool
    label_override: str | None = None
    style_override: dict | None = None

    @field_validator("id", "map_id", "location_entity_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# MapLocationLayout — 地点布局节点
# ============================================================


class MapLocationLayoutItem(BaseModel):
    location_entity_id: str
    center_hex_q: int = Field(..., ge=0)
    center_hex_r: int = Field(..., ge=0)
    occupy_radius: Literal[1, 2, 3, 5] = 1
    locked: bool = False
    layout_source: str = Field("quick_create", max_length=32)
    layout_version: int = Field(1, ge=1)
    sync_geo_setting: bool = False
    meta: dict | None = Field(default_factory=dict)

    @field_validator("location_entity_id")
    @classmethod
    def _coerce_uuid(cls, v: str) -> str:
        return str(uuid.UUID(v))


class MapLocationLayoutReplaceRequest(BaseModel):
    layouts: list[MapLocationLayoutItem] = Field(..., max_length=2000)
    sync_bindings: bool = Field(
        False,
        description="是否同步平移地点绑定并废弃被移动地点的快速创建事实",
    )


class MapLocationLayoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    location_entity_id: str
    center_hex_q: int
    center_hex_r: int
    occupy_radius: int
    locked: bool
    layout_source: str
    layout_version: int
    sync_geo_setting: bool
    meta: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "map_id", "location_entity_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class MapLocationLayoutListResponse(BaseModel):
    items: list[MapLocationLayoutResponse]
    total: int


# ============================================================
# Quick Create — 快速创建草稿
# ============================================================


class MapQuickCreateContextResponse(BaseModel):
    map_targets: list[dict] = Field(default_factory=list)
    locations: list[dict] = Field(default_factory=list)
    candidate_locations: list[dict] = Field(default_factory=list)
    existing_maps: list[MapConfigResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MapQuickCreatePreviewRequest(BaseModel):
    target: Literal["world", "detail", "drilldown"] = "world"
    parent_map_id: str | None = None
    parent_entity_id: str | None = None
    replace_map_id: str | None = None
    map_type: Literal["world", "city", "region", "dungeon"] | None = None
    grid_width: int | None = Field(None, ge=1, le=200)
    grid_height: int | None = Field(None, ge=1, le=200)
    base_template: Literal["continent", "islands", "blank"] = "blank"
    location_entity_ids: list[str] = Field(default_factory=list, max_length=2000)
    include_candidates: bool = False
    include_markers: bool = True

    @field_validator("parent_map_id", "parent_entity_id", "replace_map_id")
    @classmethod
    def _coerce_optional_uuid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return str(uuid.UUID(v))

    @field_validator("location_entity_ids")
    @classmethod
    def _coerce_location_ids(cls, values: list[str]) -> list[str]:
        return [str(uuid.UUID(value)) for value in values]


class MapQuickCreateConfirmRequest(MapQuickCreatePreviewRequest):
    name: str | None = Field(None, min_length=1, max_length=255)
    layouts: list[MapLocationLayoutItem] | None = None


class MapQuickCreatePreviewResponse(BaseModel):
    map: dict
    location_layouts: list[MapLocationLayoutItem]
    location_bindings: list[dict] = Field(default_factory=list)
    markers: list[dict] = Field(default_factory=list)
    unlocated_objects: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MapQuickCreateConfirmResponse(BaseModel):
    map: MapConfigResponse
    location_layouts: list[MapLocationLayoutResponse]
    location_bindings: list[MapLocationBindingResponse]
    markers: list = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ============================================================
# MapTerrain — 手绘地形
# ============================================================


class MapTerrainLayerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    terrain_asset_key: str = Field(..., min_length=1, max_length=64)
    opacity: float = Field(0.45, ge=0.0, le=1.0)
    z_index: int = 10
    visible: bool = True
    locked: bool = False
    meta: dict | None = Field(default_factory=dict)


class MapTerrainLayerUpdate(BaseModel):
    """手绘地形图层部分更新；所有字段均为可选，避免默认值覆盖。"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    terrain_asset_key: Annotated[str | None, Field(None, min_length=1, max_length=64)]
    opacity: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    z_index: Annotated[int | None, Field(None)]
    visible: Annotated[bool | None, Field(None)]
    locked: Annotated[bool | None, Field(None)]
    meta: Annotated[dict | None, Field(None)]


class MapTerrainLayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    name: str
    terrain_asset_key: str
    opacity: float
    z_index: int
    visible: bool
    locked: bool
    meta: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "map_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class MapTerrainLayerDeleteResponse(BaseModel):
    deleted_layer_id: str
    deleted_regions: int = 0
    deleted_patches: int = 0
    deleted_bindings: int = 0

    @field_validator("deleted_layer_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class MapTerrainRegionCreate(BaseModel):
    id: str | None = None
    layer_id: str
    name: str = Field(..., min_length=1, max_length=255)
    region_status: Literal["active", "hidden", "deprecated"] = "active"
    meta: dict | None = Field(default_factory=dict)

    @field_validator("id", "layer_id")
    @classmethod
    def _coerce_uuid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return str(uuid.UUID(v))


class MapTerrainRegionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    layer_id: str
    name: str
    region_status: str
    meta: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "map_id", "layer_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class MapTerrainPatchItem(BaseModel):
    region_id: str
    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)
    strength: float = Field(1.0, ge=0.0, le=1.0)
    brush_source: str = Field("brush", max_length=32)

    @field_validator("region_id")
    @classmethod
    def _coerce_uuid(cls, v: str) -> str:
        return str(uuid.UUID(v))


class MapTerrainPatchReplaceRequest(BaseModel):
    layer: MapTerrainLayerCreate | None = None
    regions: list[MapTerrainRegionCreate] = Field(default_factory=list, max_length=200)
    patches: list[MapTerrainPatchItem] = Field(default_factory=list, max_length=20000)


class MapTerrainPatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    layer_id: str
    region_id: str
    hex_q: int
    hex_r: int
    strength: float
    brush_source: str
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "map_id", "layer_id", "region_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class MapTerrainBindingCreate(BaseModel):
    region_id: str
    location_entity_id: str
    binding_type: Literal["footprint", "influence"]
    review_state: Literal["confirmed", "candidate", "needs_review", "ignored"] = (
        "confirmed"
    )
    source: str = Field("user_confirmed", max_length=64)
    meta: dict | None = Field(default_factory=dict)

    @field_validator("region_id", "location_entity_id")
    @classmethod
    def _coerce_uuid(cls, v: str) -> str:
        return str(uuid.UUID(v))


class MapTerrainBindingUpdate(BaseModel):
    binding_type: Annotated[Literal["footprint", "influence"] | None, Field(None)]
    review_state: Annotated[
        Literal["confirmed", "candidate", "needs_review", "ignored"] | None,
        Field(None),
    ]
    source: Annotated[str | None, Field(None, max_length=64)]
    meta: Annotated[dict | None, Field(None)]


class MapTerrainBindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    region_id: str
    location_entity_id: str
    binding_type: str
    review_state: str
    source: str
    meta: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "map_id",
        "region_id",
        "location_entity_id",
        mode="before",
    )
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class MapTerrainStateResponse(BaseModel):
    layers: list[MapTerrainLayerResponse] = Field(default_factory=list)
    regions: list[MapTerrainRegionResponse] = Field(default_factory=list)
    patches: list[MapTerrainPatchResponse] = Field(default_factory=list)
    bindings: list[MapTerrainBindingResponse] = Field(default_factory=list)
    candidate_bindings: list[MapTerrainBindingResponse] = Field(
        default_factory=list,
        description="显式预览的待处理地形绑定；默认响应为空",
    )


# ============================================================
# MapState — 聚合状态（PRD §6.2）
# ============================================================


class MapStateResponse(BaseModel):
    """地图聚合状态（PRD §6.2 渐进式扩展契约）。

    P0：map + 面包屑 + tiles + location_bindings
    P1：增加 markers / scene
    P2：增加 territories
    预留位默认空 list，保证前端解构安全。
    """

    map: MapConfigResponse
    breadcrumbs: list[MapConfigResponse]
    tiles: list[MapTileResponse]
    location_bindings: list[MapLocationBindingResponse]
    markers: list = Field(default_factory=list, description="P1: MapMarker[]，P0 恒为空")
    territories: list = Field(
        default_factory=list, description="P2: MapTerritoryTile[]，P0 恒为空"
    )
    location_layouts: list[MapLocationLayoutResponse] = Field(default_factory=list)
    terrain_layers: list[MapTerrainLayerResponse] = Field(default_factory=list)
    terrain_regions: list[MapTerrainRegionResponse] = Field(default_factory=list)
    terrain_patches: list[MapTerrainPatchResponse] = Field(default_factory=list)
    terrain_bindings: list[MapTerrainBindingResponse] = Field(default_factory=list)
    candidate_location_bindings: list[MapLocationBindingResponse] = Field(
        default_factory=list,
        description="待处理地点绑定图层：关联 CoreEntity.status=candidate",
    )
    candidate_location_layouts: list[MapLocationLayoutResponse] = Field(
        default_factory=list,
        description="关联 draft/candidate 地点的待处理布局节点",
    )
    candidate_markers: list = Field(
        default_factory=list,
        description="待处理动态标记图层：关联 CoreEntity.status=candidate",
    )
    candidate_territories: list = Field(
        default_factory=list,
        description="待处理势力范围图层：关联 CoreEntity.status=candidate",
    )
    candidate_terrain_bindings: list[MapTerrainBindingResponse] = Field(
        default_factory=list,
        description="待处理地形绑定：未采用地点或非 confirmed 绑定",
    )
    scene: dict | None = None  # P1


class MapDynamicStateResponse(BaseModel):
    """Scene-related dynamic map layers without static tiles/layout/terrain."""

    markers: list[MapMarkerResponse] = Field(default_factory=list)
    territories: list[MapTerritoryResponse] = Field(default_factory=list)
    candidate_location_bindings: list[MapLocationBindingResponse] = Field(
        default_factory=list,
    )
    candidate_markers: list[MapMarkerResponse] = Field(default_factory=list)
    candidate_territories: list[MapTerritoryResponse] = Field(default_factory=list)
    scene: dict | None = None


# ============================================================
# MapSceneSummary — 写作页轻量地图摘要
# ============================================================


class MapOpenTarget(BaseModel):
    """前端打开地图时使用的稳定目标。"""

    mode: Literal["overview", "recent", "map"]
    map_id: str | None = None
    scene_id: str | None = None
    focus_entity_id: str | None = None
    observation_id: str | None = None
    focus_path_id: str | None = Field(
        None,
        exclude_if=lambda value: value is None,
    )
    focus_layer_node_id: str | None = Field(
        None,
        exclude_if=lambda value: value is None,
    )
    fallback_reason: str | None = None
    fallback_message: str | None = None


class MapSceneSummaryItem(BaseModel):
    """Scene 摘要里的地点/人物/事件/势力项。"""

    entity_id: str
    name: str
    map_id: str
    hex_q: int | None = None
    hex_r: int | None = None
    depends_on_candidate: bool = False
    candidate_review_state: str | None = None
    evidence_excerpt: str | None = None
    open_target: dict | None = None


class MapSceneSummaryWarning(BaseModel):
    """保守的一致性提示。"""

    level: Literal["info", "warning"] = "info"
    code: str
    message: str
    depends_on_candidate: bool = False
    candidate_review_state: str | None = None
    evidence_excerpt: str | None = None
    open_target: dict | None = None


class MapSceneSummaryResponse(BaseModel):
    """写作页 Scene 面板消费的轻量地图摘要。"""

    scene_id: str
    primary_location: MapSceneSummaryItem | None = None
    characters: list[MapSceneSummaryItem] = Field(default_factory=list)
    events: list[MapSceneSummaryItem] = Field(default_factory=list)
    factions: list[MapSceneSummaryItem] = Field(default_factory=list)
    crises: list[MapSceneSummaryItem] = Field(default_factory=list)
    risks: list[MapSceneSummaryWarning] = Field(default_factory=list)
    warnings: list[MapSceneSummaryWarning] = Field(default_factory=list)
    open_target: MapOpenTarget
    candidate_support: Literal["supported", "unsupported"] = "supported"


# ============================================================
# MapMarker — 动态标记（P1）
# ============================================================

MARKER_TYPES: tuple[str, ...] = ("character", "event", "item")


class MapMarkerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entity_id: str
    marker_type: str
    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)
    offset_x: float = Field(0, ge=-1, le=1)
    offset_y: float = Field(0, ge=-1, le=1)
    label: str | None = None
    style_json: dict | None = None
    start_scene_id: str | None = None
    start_scene_index: int | None = Field(None, ge=0)
    end_scene_id: str | None = None
    end_scene_index: int | None = Field(None, ge=0)
    visible: bool = True

    @field_validator("marker_type")
    @classmethod
    def _valid_marker_type(cls, v):
        if v not in MARKER_TYPES:
            raise ValueError(f"marker_type must be one of {MARKER_TYPES}")
        return v

    @field_validator("entity_id", "start_scene_id", "end_scene_id")
    @classmethod
    def _coerce_uuid(cls, v):
        return str(uuid.UUID(v))


class MapMarkerUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    hex_q: int | None = Field(None, ge=0)
    hex_r: int | None = Field(None, ge=0)
    offset_x: float | None = Field(None, ge=-1, le=1)
    offset_y: float | None = Field(None, ge=-1, le=1)
    label: str | None = None
    style_json: dict | None = None
    start_scene_id: str | None = None
    start_scene_index: int | None = Field(None, ge=0)
    end_scene_id: str | None = None
    end_scene_index: int | None = Field(None, ge=0)
    visible: bool | None = None

    @field_validator("start_scene_id", "end_scene_id")
    @classmethod
    def _coerce_uuid(cls, v):
        if v is not None:
            return str(uuid.UUID(v))
        return v


class MapMarkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    entity_id: str
    marker_type: str
    hex_q: int
    hex_r: int
    offset_x: float
    offset_y: float
    label: str | None
    style_json: dict | None
    start_scene_id: str | None
    start_scene_index: int | None
    end_scene_id: str | None
    end_scene_index: int | None
    visible: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "novel_id", "map_id", "entity_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("start_scene_id", "end_scene_id", mode="before")
    @classmethod
    def _coerce_optional_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)


# ============================================================
# MapTerritoryTile — 势力范围（P2）
# ============================================================


class TerritoryHex(BaseModel):
    """单格势力范围。"""

    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)
    style_override: dict | None = Field(None)


class MapTerritoryCreate(BaseModel):
    """批量创建势力范围请求体。"""

    faction_entity_id: str = Field(
        ..., description="组织实体 ID（entity_type=organization）"
    )
    hexes: list[TerritoryHex] = Field(..., min_length=1, max_length=5000)


class MapTerritoryUpdate(BaseModel):
    """更新单格势力范围样式。"""

    style_override: dict | None = Field(None)


class MapTerritoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    faction_entity_id: str
    hex_q: int
    hex_r: int
    style_override: dict | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("id", "novel_id", "map_id", "faction_entity_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# MapLayerTree / atomic editor
# ============================================================


class MapLayerNodeWrite(BaseModel):
    id: str | None = None
    client_id: str | None = Field(None, min_length=1, max_length=64)
    parent_id: str | None = None
    parent_client_id: str | None = Field(None, min_length=1, max_length=64)
    terrain_layer_id: str | None = None
    terrain_layer_client_id: str | None = Field(None, min_length=1, max_length=64)
    path_layer_id: str | None = None
    path_layer_client_id: str | None = Field(None, min_length=1, max_length=64)
    node_type: Literal["group", "leaf"]
    layer_key: str | None = Field(None, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    visible: bool = True
    locked: bool = False
    opacity: float = Field(1.0, ge=0.0, le=1.0)
    sort_order: int = Field(0, ge=0)
    min_zoom: int | None = Field(None, ge=-3, le=3)
    max_zoom: int | None = Field(None, ge=-3, le=3)
    selection_mode: Literal["normal", "exclusive", "floor"] = "normal"
    floor_level: int | None = Field(None, ge=-1000, le=1000)
    meta: dict | None = Field(default_factory=dict)

    @field_validator("id", "parent_id", "terrain_layer_id", "path_layer_id")
    @classmethod
    def _coerce_optional_ids(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None

    @model_validator(mode="after")
    def _validate_refs(self):
        if bool(self.id) == bool(self.client_id):
            raise ValueError("node must provide exactly one of id or client_id")
        if self.parent_id and self.parent_client_id:
            raise ValueError("parent_id and parent_client_id are mutually exclusive")
        if self.terrain_layer_id and self.terrain_layer_client_id:
            raise ValueError(
                "terrain_layer_id and terrain_layer_client_id are mutually exclusive"
            )
        if self.path_layer_id and self.path_layer_client_id:
            raise ValueError(
                "path_layer_id and path_layer_client_id are mutually exclusive"
            )
        if self.min_zoom is not None and self.max_zoom is not None:
            if self.min_zoom > self.max_zoom:
                raise ValueError("min_zoom must be less than or equal to max_zoom")
        if self.node_type == "group" and any(
            (
                self.terrain_layer_id,
                self.terrain_layer_client_id,
                self.path_layer_id,
                self.path_layer_client_id,
            )
        ):
            raise ValueError("group nodes cannot bind a terrain or path layer")
        if self.node_type == "leaf" and self.selection_mode != "normal":
            raise ValueError("leaf nodes must use selection_mode=normal")
        return self


class MapLayerNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    parent_id: str | None = None
    terrain_layer_id: str | None = None
    path_layer_id: str | None = None
    node_type: Literal["group", "leaf"]
    layer_key: str | None = None
    name: str
    visible: bool
    locked: bool
    opacity: float
    sort_order: int
    min_zoom: int | None = None
    max_zoom: int | None = None
    selection_mode: Literal["normal", "exclusive", "floor"] = "normal"
    floor_level: int | None = None
    effective_visible: bool = True
    effective_locked: bool = False
    effective_opacity: float = 1.0
    effective_min_zoom: int | None = None
    effective_max_zoom: int | None = None
    depth: int = 1
    meta: dict | None = None

    @field_validator(
        "id",
        "novel_id",
        "map_id",
        "parent_id",
        "terrain_layer_id",
        "path_layer_id",
        mode="before",
    )
    @classmethod
    def _coerce_ids(cls, value: object) -> str | None:
        return _optional_uuid_validator(value)


class MapLayerTreeResponse(BaseModel):
    map_id: str
    editor_revision: int
    nodes: list[MapLayerNodeResponse] = Field(default_factory=list)


class MapResourceRef(BaseModel):
    id: str | None = None
    client_id: str | None = Field(None, min_length=1, max_length=64)

    @field_validator("id")
    @classmethod
    def _coerce_id(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None

    @model_validator(mode="after")
    def _exactly_one(self):
        if bool(self.id) == bool(self.client_id):
            raise ValueError("resource ref requires exactly one of id or client_id")
        return self


PATH_LAYER_CATEGORIES: tuple[str, ...] = ("transport", "water")
TRANSPORT_PATH_TYPES: tuple[str, ...] = (
    "major_road",
    "street",
    "dirt_trail",
    "rail",
)
WATER_PATH_TYPES: tuple[str, ...] = ("river", "stream", "canal")
PATH_TYPES: tuple[str, ...] = TRANSPORT_PATH_TYPES + WATER_PATH_TYPES


class MapPathStyle(BaseModel):
    """Validated Canvas style override for a continuous path."""

    model_config = ConfigDict(extra="forbid")

    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    casing_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    width: float | None = Field(None, ge=0.25, le=32, allow_inf_nan=False)
    casing_width: float | None = Field(None, ge=0, le=16, allow_inf_nan=False)
    dash: list[float] | None = Field(None, max_length=4)

    @field_validator("dash")
    @classmethod
    def _validate_dash(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if any(not 0 <= number <= 20 for number in value):
            raise ValueError("dash values must be between 0 and 20")
        return value


class MapPathNodeInput(BaseModel):
    q: float = Field(..., ge=0, allow_inf_nan=False)
    r: float = Field(..., ge=0, allow_inf_nan=False)
    width_scale: float = Field(1.0, ge=0.25, le=4, allow_inf_nan=False)
    tension: float = Field(0.5, ge=0, le=1, allow_inf_nan=False)
    segment_type: Literal[
        "major_road",
        "street",
        "dirt_trail",
        "rail",
        "river",
        "stream",
        "canal",
    ] | None = None


class MapPathCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    path_type: Literal[
        "major_road",
        "street",
        "dirt_trail",
        "rail",
        "river",
        "stream",
        "canal",
    ]
    nodes: list[MapPathNodeInput] = Field(..., min_length=2, max_length=500)
    sort_order: int = Field(0, ge=0)
    visible: bool = True
    locked: bool = False
    opacity: float = Field(1.0, ge=0, le=1, allow_inf_nan=False)
    min_zoom: int | None = Field(None, ge=-3, le=3)
    max_zoom: int | None = Field(None, ge=-3, le=3)
    style: MapPathStyle | None = None
    start_location_entity_id: str | None = None
    end_location_entity_id: str | None = None
    meta: dict | None = Field(default_factory=dict)

    @field_validator("start_location_entity_id", "end_location_entity_id")
    @classmethod
    def _coerce_location_id(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None

    @model_validator(mode="after")
    def _validate_zoom(self):
        if self.min_zoom is not None and self.max_zoom is not None:
            if self.min_zoom > self.max_zoom:
                raise ValueError("min_zoom must be less than or equal to max_zoom")
        return self


class MapPathUpdate(BaseModel):
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    path_type: Literal[
        "major_road",
        "street",
        "dirt_trail",
        "rail",
        "river",
        "stream",
        "canal",
    ] | None = None
    nodes: list[MapPathNodeInput] | None = Field(None, min_length=2, max_length=500)
    sort_order: Annotated[int | None, Field(None, ge=0)]
    visible: bool | None = None
    locked: bool | None = None
    opacity: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    min_zoom: int | None = Field(None, ge=-3, le=3)
    max_zoom: int | None = Field(None, ge=-3, le=3)
    style: MapPathStyle | None = None
    start_location_entity_id: str | None = None
    end_location_entity_id: str | None = None
    snap_start: bool = False
    snap_end: bool = False
    meta: dict | None = None

    @field_validator("start_location_entity_id", "end_location_entity_id")
    @classmethod
    def _coerce_update_location_id(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None

    @model_validator(mode="after")
    def _validate_update_zoom(self):
        if self.min_zoom is not None and self.max_zoom is not None:
            if self.min_zoom > self.max_zoom:
                raise ValueError("min_zoom must be less than or equal to max_zoom")
        return self


class MapPathLayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    category: Literal["transport", "water"]
    name: str
    layer_node_id: str
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "map_id", "layer_node_id", mode="before")
    @classmethod
    def _coerce_path_layer_ids(cls, value: object) -> str:
        return _uuid_validator(value)


class MapPathNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    path_id: str
    sort_order: int
    q: float
    r: float
    width_scale: float
    tension: float
    segment_type: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "map_id", "path_id", mode="before")
    @classmethod
    def _coerce_path_node_ids(cls, value: object) -> str:
        return _uuid_validator(value)


class MapPathResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str
    path_layer_id: str
    name: str
    path_type: str
    sort_order: int
    visible: bool
    locked: bool
    opacity: float
    min_zoom: int | None = None
    max_zoom: int | None = None
    style: MapPathStyle | None = None
    start_location_entity_id: str | None = None
    end_location_entity_id: str | None = None
    status: Literal["active", "archived"]
    archived_at: datetime | None = None
    content_revision: int
    meta: dict | None = None
    nodes: list[MapPathNodeResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "map_id",
        "path_layer_id",
        mode="before",
    )
    @classmethod
    def _coerce_path_ids(cls, value: object) -> str:
        return _uuid_validator(value)

    @field_validator(
        "start_location_entity_id",
        "end_location_entity_id",
        mode="before",
    )
    @classmethod
    def _coerce_optional_path_ids(cls, value: object) -> str | None:
        return _optional_uuid_validator(value)


class MapPathStateResponse(BaseModel):
    map_id: str
    editor_revision: int
    layers: list[MapPathLayerResponse] = Field(default_factory=list)
    paths: list[MapPathResponse] = Field(default_factory=list)


class MapPathArchiveImpactResponse(BaseModel):
    path_id: str
    observation_count: int = 0
    fact_count: int = 0
    other_reference_count: int = 0


class BaseTerrainReplaceCommand(BaseModel):
    type: Literal["base_terrain_replace"]
    changes: list[MapTileChange] = Field(..., min_length=1, max_length=10000)


class LocationLayoutReplaceCommand(BaseModel):
    type: Literal["location_layout_replace"]
    layouts: list[MapLocationLayoutItem] = Field(..., max_length=2000)
    sync_bindings: bool = True


class LocationBindingReplaceCommand(BaseModel):
    type: Literal["location_binding_replace"]
    items: list[MapLocationBindingCreate] = Field(default_factory=list, max_length=2000)


class TerrainLayerCreateCommand(BaseModel):
    type: Literal["terrain_layer_create"]
    client_id: str = Field(..., min_length=1, max_length=64)
    data: MapTerrainLayerCreate


class TerrainLayerUpdateCommand(BaseModel):
    type: Literal["terrain_layer_update"]
    ref: MapResourceRef
    data: MapTerrainLayerUpdate


class TerrainLayerDeleteCommand(BaseModel):
    type: Literal["terrain_layer_delete"]
    ref: MapResourceRef


class PathLayerCreateCommand(BaseModel):
    type: Literal["path_layer_create"]
    client_id: str = Field(..., min_length=1, max_length=64)
    leaf_client_id: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=255)
    category: Literal["transport", "water"]
    meta: dict | None = Field(default_factory=dict)


class PathLayerDeleteCommand(BaseModel):
    type: Literal["path_layer_delete"]
    ref: MapResourceRef


class MapPathCreateData(MapPathCreate):
    layer_ref: MapResourceRef


class MapPathUpdateData(MapPathUpdate):
    layer_ref: MapResourceRef | None = None


class PathCreateCommand(BaseModel):
    type: Literal["path_create"]
    client_id: str = Field(..., min_length=1, max_length=64)
    data: MapPathCreateData


class PathUpdateCommand(BaseModel):
    type: Literal["path_update"]
    ref: MapResourceRef
    data: MapPathUpdateData


class PathArchiveCommand(BaseModel):
    type: Literal["path_archive"]
    ref: MapResourceRef


class PathRestoreCommand(BaseModel):
    type: Literal["path_restore"]
    ref: MapResourceRef


class TerrainPatchReplaceCommand(BaseModel):
    type: Literal["terrain_patch_replace"]
    layer_ref: MapResourceRef
    data: MapTerrainPatchReplaceRequest


class MarkerCreateCommand(BaseModel):
    type: Literal["marker_create"]
    client_id: str = Field(..., min_length=1, max_length=64)
    data: MapMarkerCreate


class MarkerUpdateCommand(BaseModel):
    type: Literal["marker_update"]
    ref: MapResourceRef
    data: MapMarkerUpdate


class MarkerDeleteCommand(BaseModel):
    type: Literal["marker_delete"]
    ref: MapResourceRef


class TerritoryReplaceCommand(BaseModel):
    type: Literal["territory_replace"]
    faction_entity_id: str
    hexes: list[TerritoryHex] = Field(default_factory=list, max_length=5000)

    @field_validator("faction_entity_id")
    @classmethod
    def _coerce_entity_id(cls, value: str) -> str:
        return str(uuid.UUID(value))


class LayerTreeReplaceCommand(BaseModel):
    type: Literal["layer_tree_replace"]
    nodes: list[MapLayerNodeWrite] = Field(..., min_length=1, max_length=500)


MapEditorCommand = Annotated[
    BaseTerrainReplaceCommand
    | LocationLayoutReplaceCommand
    | LocationBindingReplaceCommand
    | TerrainLayerCreateCommand
    | TerrainLayerUpdateCommand
    | TerrainLayerDeleteCommand
    | PathLayerCreateCommand
    | PathLayerDeleteCommand
    | PathCreateCommand
    | PathUpdateCommand
    | PathArchiveCommand
    | PathRestoreCommand
    | TerrainPatchReplaceCommand
    | MarkerCreateCommand
    | MarkerUpdateCommand
    | MarkerDeleteCommand
    | TerritoryReplaceCommand
    | LayerTreeReplaceCommand,
    Field(discriminator="type"),
]


class MapEditorApplyRequest(BaseModel):
    expected_revision: int = Field(..., ge=0)
    commands: list[MapEditorCommand] = Field(..., min_length=1, max_length=200)


class MapEditorApplyResponse(BaseModel):
    map_id: str
    editor_revision: int
    command_results: list[dict] = Field(default_factory=list)
    client_id_map: dict[str, str] = Field(default_factory=dict)


# ============================================================
# Entity map presence
# ============================================================


class MapEntityPresenceItem(BaseModel):
    map_id: str
    map_name: str
    roles: list[str] = Field(default_factory=list)
    binding_count: int = 0
    representative_hex_q: int | None = None
    representative_hex_r: int | None = None
    representative_world_q: float | None = None
    representative_world_r: float | None = None
    path_refs: list[dict] = Field(default_factory=list)
    scene_index_min: int | None = None
    scene_index_max: int | None = None
    display_state: Literal["active", "review"] = "active"
    open_target: MapOpenTarget


class MapEntityPresenceResponse(BaseModel):
    entity_id: str
    items: list[MapEntityPresenceItem] = Field(default_factory=list)
    total: int = 0


# ============================================================
# MapObservation / MapFact — 世界动态 P0 可信事实底座
# ============================================================

MAP_REVIEW_STATES: tuple[str, ...] = (
    "candidate",
    "confirmed",
    "ignored",
    "conflicted",
)
MAP_FACT_STATUSES: tuple[str, ...] = ("confirmed", "rolled_back", "deprecated")

MAP_DYNAMIC_TRACKS: tuple[str, ...] = (
    "journey",
    "territory",
    "crisis",
    "resource",
    "status",
    "world",
)

MAP_DYNAMIC_NORMALIZATION_STATES: tuple[str, ...] = (
    "typed",
    "legacy_normalized",
    "untyped",
    "invalid",
)


class MapDynamicValueBase(BaseModel):
    """Versioned, server-validated value stored inside ``value_json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1


class MapDynamicHex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hex_q: int = Field(..., ge=0)
    hex_r: int = Field(..., ge=0)


class MapLocationDynamicValue(MapDynamicValueBase):
    type: Literal["location"]
    location_entity_id: str | None = None
    path_id: str | None = None
    movement_mode: Literal[
        "walk",
        "ride",
        "vehicle",
        "rail",
        "water",
        "flight",
        "teleport",
        "unknown",
    ] = "unknown"
    state: str = Field("present", min_length=1, max_length=64)

    @field_validator("location_entity_id", "path_id")
    @classmethod
    def _coerce_location_value_ids(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None


class MapRouteStateDynamicValue(MapDynamicValueBase):
    type: Literal["route_state"]
    path_id: str
    state: Literal["open", "restricted", "blocked"]
    reason: str | None = Field(None, max_length=1000)

    @field_validator("path_id")
    @classmethod
    def _coerce_route_path_id(cls, value: str) -> str:
        return str(uuid.UUID(value))


MapDynamicScalar = str | int | float | bool | None


class MapStatusDynamicValue(MapDynamicValueBase):
    type: Literal["status"]
    field_key: str = Field(..., min_length=1, max_length=128)
    value: MapDynamicScalar

    @field_validator("value")
    @classmethod
    def _finite_status_number(cls, value: MapDynamicScalar) -> MapDynamicScalar:
        if isinstance(value, float) and not (-float("inf") < value < float("inf")):
            raise ValueError("status value must be finite")
        return value


class MapBoundaryDynamicValue(MapDynamicValueBase):
    type: Literal["boundary"]
    controller_entity_id: str
    hexes: list[MapDynamicHex] = Field(default_factory=list, max_length=20000)

    @field_validator("controller_entity_id")
    @classmethod
    def _coerce_boundary_controller_id(cls, value: str) -> str:
        return str(uuid.UUID(value))

    @model_validator(mode="after")
    def _canonicalize_hexes(self) -> MapBoundaryDynamicValue:
        self.hexes = _canonical_dynamic_hexes(self.hexes)
        return self


class MapResourceDynamicValue(MapDynamicValueBase):
    type: Literal["resource"]
    resource_key: str = Field(..., min_length=1, max_length=128)
    controller_entity_id: str | None = None
    status: str | None = Field(None, max_length=128)
    amount: float | None = Field(None, allow_inf_nan=False)

    @field_validator("controller_entity_id")
    @classmethod
    def _coerce_resource_controller_id(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None


class MapTerrainDynamicValue(MapDynamicValueBase):
    type: Literal["terrain"]
    terrain_key: str = Field(..., min_length=1, max_length=128)
    state: str = Field(..., min_length=1, max_length=128)
    hexes: list[MapDynamicHex] = Field(default_factory=list, max_length=20000)

    @model_validator(mode="after")
    def _canonicalize_hexes(self) -> MapTerrainDynamicValue:
        self.hexes = _canonical_dynamic_hexes(self.hexes)
        return self


class MapCrisisDynamicValue(MapDynamicValueBase):
    type: Literal["crisis"]
    crisis_key: str = Field(..., min_length=1, max_length=128)
    severity: int = Field(..., ge=0, le=5)
    hexes: list[MapDynamicHex] = Field(default_factory=list, max_length=20000)

    @model_validator(mode="after")
    def _canonicalize_hexes(self) -> MapCrisisDynamicValue:
        self.hexes = _canonical_dynamic_hexes(self.hexes)
        return self


class MapSemanticDynamicValue(MapDynamicValueBase):
    type: Literal["semantic"]
    relation_type: str = Field(..., min_length=1, max_length=64)
    related_entity_ids: list[str] = Field(default_factory=list, max_length=200)
    summary: str | None = Field(None, max_length=2000)

    @field_validator("related_entity_ids")
    @classmethod
    def _coerce_semantic_entity_ids(cls, values: list[str]) -> list[str]:
        return sorted({str(uuid.UUID(value)) for value in values})


def _canonical_dynamic_hexes(values: list[MapDynamicHex]) -> list[MapDynamicHex]:
    by_coordinate = {(item.hex_q, item.hex_r): item for item in values}
    return [by_coordinate[key] for key in sorted(by_coordinate)]


MapDynamicValueV1 = Annotated[
    MapLocationDynamicValue
    | MapRouteStateDynamicValue
    | MapStatusDynamicValue
    | MapBoundaryDynamicValue
    | MapResourceDynamicValue
    | MapTerrainDynamicValue
    | MapCrisisDynamicValue
    | MapSemanticDynamicValue,
    Field(discriminator="type"),
]
_MAP_DYNAMIC_VALUE_ADAPTER = TypeAdapter(MapDynamicValueV1)


_MAP_OBSERVATION_PROPOSAL_ADAPTER = TypeAdapter(MapObservationProposalV1)


def validate_map_observation_payload(
    dynamic_type: str,
    value_json: dict[str, Any] | None,
    *,
    require_explicit_schema: bool = False,
) -> None:
    """Validate proposal or canonical observation payloads.

    Legacy payloads remain readable and can still be created through the
    compatibility create route.  Author PATCH is stricter and requires an
    explicit proposal or canonical schema.
    """

    value = value_json if isinstance(value_json, dict) else {}
    if value.get("payload_kind") == "proposal":
        proposal = _MAP_OBSERVATION_PROPOSAL_ADAPTER.validate_python(value)
        expected_type = {
            "character_location": "location",
            "event_location": "location",
            "route_state": "route_state",
            "boundary": "boundary",
        }[proposal.proposal_type]
        normalized_type = str(dynamic_type or "").strip().lower().replace("-", "_")
        normalized_type = {
            "movement": "location",
            "position": "location",
            "position_change": "location",
            "journey": "location",
            "route": "route_state",
            "path_state": "route_state",
            "territory": "boundary",
            "territory_change": "boundary",
        }.get(normalized_type, normalized_type)
        if normalized_type != expected_type:
            raise ValueError("proposal_type does not match dynamic_type")
        return
    if require_explicit_schema and "schema_version" not in value:
        raise ValueError("author update requires a proposal or canonical payload")
    from modules.world.services.map.map_dynamic_projection import (
        validate_versioned_dynamic_value,
    )

    validate_versioned_dynamic_value(dynamic_type, value)


class MapSpatialAnchor(BaseModel):
    """Validated spatial anchor while preserving legacy extension keys."""

    model_config = ConfigDict(extra="allow")

    map_id: str | None = None
    path_id: str | None = None
    path_revision: int | None = Field(None, ge=1)
    path_name: str | None = Field(None, max_length=255)
    location_entity_id: str | None = None
    # Legacy hex anchors are integer grid coordinates.  Keep their JSON wire
    # representation exact (``2`` rather than ``2.0``); continuous path
    # coordinates use the separate representative_q/r fields below.
    hex_q: int | None = Field(None, ge=0)
    hex_r: int | None = Field(None, ge=0)
    representative_q: float | None = Field(None, ge=0, allow_inf_nan=False)
    representative_r: float | None = Field(None, ge=0, allow_inf_nan=False)

    @field_validator("map_id", "path_id", "location_entity_id")
    @classmethod
    def _coerce_anchor_uuid(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None

    @model_validator(mode="after")
    def _coordinate_pairs(self):
        if (self.hex_q is None) != (self.hex_r is None):
            raise ValueError("hex_q and hex_r must be provided together")
        if (self.representative_q is None) != (self.representative_r is None):
            raise ValueError(
                "representative_q and representative_r must be provided together"
            )
        if self.path_id is None and (
            self.path_revision is not None or self.path_name is not None
        ):
            raise ValueError("path_revision and path_name require path_id")
        return self


class MapObservationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_entity_id: str | None = Field(None, description="目标实体 ID，可为空")
    target_entity_type: str | None = Field(None, max_length=64)
    target_name: str | None = Field(None, max_length=255)
    dynamic_type: str = Field(..., min_length=1, max_length=64)
    time_anchor: dict | None = Field(default_factory=dict)
    spatial_anchor: MapSpatialAnchor | None = Field(default_factory=MapSpatialAnchor)
    value_json: dict | None = Field(default_factory=dict)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    review_state: Literal["candidate", "conflicted"] = Field("candidate")
    source_ref: dict | None = Field(default_factory=dict)
    evidence_text: str | None = None
    scene_id: str | None = None
    scene_index: int | None = Field(None, ge=0)
    source_chapter_index: int | None = Field(None, ge=0)

    @field_validator("target_entity_id", "scene_id")
    @classmethod
    def _coerce_optional_uuid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return str(uuid.UUID(v))

    @model_validator(mode="after")
    def _validate_versioned_value(self) -> MapObservationCreate:
        validate_map_observation_payload(self.dynamic_type, self.value_json)
        return self


class MapObservationAuthorUpdate(BaseModel):
    """Fields an author may change on an unconfirmed observation.

    Provenance, evidence, workflow, confidence and source Scene/chapter are
    intentionally absent.  ``extra=forbid`` makes the API, not the UI, enforce
    that read-only boundary.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_updated_at: datetime
    review_state: Literal["candidate", "ignored", "conflicted"] | None = None
    target_entity_id: str | None = None
    target_entity_type: str | None = Field(None, max_length=64)
    target_name: str | None = Field(None, max_length=255)
    spatial_anchor: MapSpatialAnchor | None = None
    value_json: dict | None = None

    @field_validator("target_entity_id")
    @classmethod
    def _coerce_optional_uuid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return str(uuid.UUID(v))

    @model_validator(mode="after")
    def _validate_author_payload(self) -> MapObservationAuthorUpdate:
        if "review_state" in self.model_fields_set and self.review_state is None:
            raise ValueError("review_state must not be null")
        if self.value_json is None:
            return self
        value = self.value_json
        if value.get("payload_kind") == "proposal":
            _MAP_OBSERVATION_PROPOSAL_ADAPTER.validate_python(value)
        elif "schema_version" not in value:
            raise ValueError("author update requires a proposal or canonical payload")
        return self


class MapObservationReviewUpdate(MapObservationAuthorUpdate):
    """Compatibility name for existing internal imports."""


class MapObservationRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_updated_at: datetime


class MapObservationAssignmentRequest(MapObservationRevisionRequest):
    map_id: str | None = None

    @field_validator("map_id")
    @classmethod
    def _coerce_map_id(cls, value: str | None) -> str | None:
        return str(uuid.UUID(value)) if value else None


class MapObservationBatchReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    expected_updated_at: datetime

    @field_validator("observation_id")
    @classmethod
    def _coerce_observation_id(cls, value: str) -> str:
        return str(uuid.UUID(value))


class MapObservationBatchReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MapObservationBatchReviewItem] = Field(..., min_length=1, max_length=100)
    action: Literal["confirm", "ignore", "conflict"]

    @model_validator(mode="after")
    def _unique_items(self) -> MapObservationBatchReviewRequest:
        ids = [item.observation_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("batch observation ids must be unique")
        return self


class MapObservationEligibility(BaseModel):
    can_confirm: bool = False
    missing_items: list[str] = Field(default_factory=list)
    missing_item_labels: list[str] = Field(default_factory=list)
    conflict_reason: str | None = None


class MapObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    map_id: str | None = None
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    target_name: str | None = None
    dynamic_type: str
    time_anchor: dict | None = None
    spatial_anchor: dict | None = None
    value_json: dict | None = None
    normalized_value: MapDynamicValueV1 | None = None
    dimension_key: str | None = None
    normalization_state: Literal[
        "typed", "legacy_normalized", "untyped", "invalid"
    ] | None = None
    proposal_value: MapObservationProposalV1 | None = None
    proposal_type: str | None = None
    eligibility: MapObservationEligibility = Field(
        default_factory=MapObservationEligibility
    )
    confidence: float
    review_state: str
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    source_ref: dict | None = None
    evidence_text: str | None = None
    scene_id: str | None = None
    scene_index: int | None = None
    source_chapter_index: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("map_id", "target_entity_id", "scene_id", mode="before")
    @classmethod
    def _coerce_optional_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)

    @model_validator(mode="after")
    def derive_author_state(self) -> MapObservationResponse:
        from modules.world.asset_state import project_map_state

        projection = project_map_state(
            status=self.review_state,
            source_ref=self.source_ref,
            confidence=self.confidence,
        )
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        if self.suggested_action is None:
            self.suggested_action = projection["suggested_action"]
        if self.normalization_state is None:
            from modules.world.services.map.map_dynamic_projection import (
                normalize_dynamic_value,
            )

            normalized = normalize_dynamic_value(
                self.dynamic_type,
                self.value_json,
                self.spatial_anchor,
            )
            self.normalized_value = (
                _MAP_DYNAMIC_VALUE_ADAPTER.validate_python(normalized.value)
                if normalized.value is not None
                else None
            )
            self.dimension_key = normalized.dimension_key
            self.normalization_state = normalized.state
        if (
            isinstance(self.value_json, dict)
            and self.value_json.get("payload_kind") == "proposal"
        ):
            proposal = _MAP_OBSERVATION_PROPOSAL_ADAPTER.validate_python(
                self.value_json
            )
            self.proposal_value = proposal
            self.proposal_type = proposal.proposal_type
            self.normalized_value = None
            self.dimension_key = None
            self.normalization_state = "untyped"
        elif self.proposal_type is None and isinstance(self.source_ref, dict):
            persisted_proposal_type = self.source_ref.get("proposal_type")
            if persisted_proposal_type in {
                "character_location",
                "event_location",
                "route_state",
                "boundary",
            }:
                self.proposal_type = persisted_proposal_type
        return self


class MapObservationListResponse(BaseModel):
    items: list[MapObservationResponse]
    total: int
    has_more: bool = False


class MapFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    observation_id: str | None = None
    map_id: str | None = None
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    target_name: str | None = None
    dynamic_type: str
    time_anchor: dict | None = None
    spatial_anchor: dict | None = None
    value_json: dict | None = None
    normalized_value: MapDynamicValueV1 | None = None
    dimension_key: str | None = None
    normalization_state: Literal[
        "typed", "legacy_normalized", "untyped", "invalid"
    ] | None = None
    confidence: float
    fact_status: str
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    source_ref: dict | None = None
    evidence_text: str | None = None
    scene_id: str | None = None
    scene_index: int | None = None
    source_chapter_index: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def _coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator(
        "observation_id",
        "map_id",
        "target_entity_id",
        "scene_id",
        mode="before",
    )
    @classmethod
    def _coerce_optional_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)

    @model_validator(mode="after")
    def derive_author_state(self) -> MapFactResponse:
        from modules.world.asset_state import project_map_state

        projection = project_map_state(
            status=self.fact_status,
            source_ref=self.source_ref,
            confidence=self.confidence,
        )
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        if self.suggested_action is None:
            self.suggested_action = projection["suggested_action"]
        if self.normalization_state is None:
            from modules.world.services.map.map_dynamic_projection import (
                normalize_dynamic_value,
            )

            normalized = normalize_dynamic_value(
                self.dynamic_type,
                self.value_json,
                self.spatial_anchor,
            )
            self.normalized_value = (
                _MAP_DYNAMIC_VALUE_ADAPTER.validate_python(normalized.value)
                if normalized.value is not None
                else None
            )
            self.dimension_key = normalized.dimension_key
            self.normalization_state = normalized.state
        return self


class MapFactListResponse(BaseModel):
    items: list[MapFactResponse]
    total: int


class MapFactStatusUpdate(BaseModel):
    fact_status: Literal["confirmed", "rolled_back", "deprecated"]


class MapObservationBatchReviewResponse(BaseModel):
    action: Literal["confirm", "ignore", "conflict"]
    requested_count: int
    updated_count: int
    created_fact_count: int
    observations: list[MapObservationResponse] = Field(default_factory=list)
    facts: list[MapFactResponse] = Field(default_factory=list)


class MapBatchActionRequest(BaseModel):
    action: Literal[
        "confirm_observations",
        "ignore_observations",
        "mark_conflicted",
        "update_fact_status",
        "update_layer_visibility",
    ]
    observation_items: list[MapObservationBatchReviewItem] = Field(
        default_factory=list,
        max_length=100,
    )
    fact_ids: list[str] = Field(default_factory=list, max_length=100)
    patch: dict = Field(default_factory=dict)
    confirmation_text: str | None = Field(None, max_length=64)

    @field_validator("fact_ids")
    @classmethod
    def _coerce_ids(cls, values: list[str]) -> list[str]:
        return [str(uuid.UUID(value)) for value in values]

    @model_validator(mode="after")
    def _validate_action_items(self) -> MapBatchActionRequest:
        if self.action in {
            "confirm_observations",
            "ignore_observations",
            "mark_conflicted",
        } and not self.observation_items:
            raise ValueError("observation_items is required for observation actions")
        return self


class MapBatchActionResponse(BaseModel):
    action: str
    requested_count: int
    updated_count: int
    created_fact_count: int = 0
    observations: list[MapObservationResponse] = Field(default_factory=list)
    facts: list[MapFactResponse] = Field(default_factory=list)
    layer_visibility: dict = Field(default_factory=dict)


# ============================================================
# MapDashboard — 世界动态总控台（P1）
# ============================================================


class MapDashboardQueueItem(BaseModel):
    item_id: str
    item_kind: Literal["observation", "fact"]
    title: str
    target_entity_id: str | None = None
    object_type: str | None = None
    type_label: str | None = None
    dynamic_type: str
    time_label: str
    status_label: str
    source_summary: str
    location_label: str | None = None
    spatial_anchor_label: str | None = None
    debug_ref: dict = Field(default_factory=dict)
    priority: int
    risk_level: Literal["info", "warning", "danger"] = "info"
    confidence: float | None = None
    review_state: str | None = None
    fact_status: str | None = None
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None


class MapDashboardInspector(BaseModel):
    title: str
    status_label: str
    summary: str | None = None
    focus_entity_id: str | None = None
    object_type: str | None = None
    type_label: str | None = None
    object_name: str | None = None
    location_label: str | None = None
    spatial_anchor_label: str | None = None
    debug_ref: dict = Field(default_factory=dict)
    timeline: list[MapDashboardQueueItem] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    map_facts: list[MapDashboardQueueItem] = Field(default_factory=list)
    ai_candidates: list[MapDashboardQueueItem] = Field(default_factory=list)
    conflicts: list[MapDashboardQueueItem] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)
    related_dynamics: list[MapDashboardQueueItem] = Field(default_factory=list)


class MapDashboardBatchGroup(BaseModel):
    group_key: str
    group_label: str
    count: int
    candidate_count: int
    confirmed_count: int
    first_joined_label: str


class MapDashboardResponse(BaseModel):
    map_id: str
    mode: Literal["dashboard"] = "dashboard"
    title: str = "世界动态总控台"
    first_visual_layer: dict = Field(default_factory=dict)
    dynamic_queue: list[MapDashboardQueueItem] = Field(default_factory=list)
    inspector: MapDashboardInspector
    batch_groups: list[MapDashboardBatchGroup] = Field(default_factory=list)
    risk_summary: list[str] = Field(default_factory=list)


# ============================================================
# MapPlayback — 世界动态 P3 电影化播放派生视图
# ============================================================


class MapPlaybackEvent(BaseModel):
    event_id: str
    event_kind: Literal["observation", "fact"]
    typed_observation: str
    track: Literal["journey", "territory", "crisis", "resource", "status", "world"]
    title: str
    time_label: str
    status_label: str
    change_summary: str
    source_summary: str
    spatial_anchor: dict = Field(default_factory=dict)
    scene_index: int | None = None
    source_chapter_index: int | None = None
    risk_level: Literal["info", "warning", "danger"] = "info"
    confidence: float | None = None
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None


class MapPlaybackTrack(BaseModel):
    track: Literal["journey", "territory", "crisis", "resource", "status", "world"]
    label: str
    count: int
    first_time_label: str


class MapPlaybackResponse(BaseModel):
    map_id: str
    title: str = "世界动态播放"
    events: list[MapPlaybackEvent] = Field(default_factory=list)
    tracks: list[MapPlaybackTrack] = Field(default_factory=list)
    low_motion_recommended: bool = False


# ============================================================
# Map timeline / point-in-time state — deterministic read projections
# ============================================================


class MapDynamicDeltaRead(BaseModel):
    delta_id: str
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    target_name: str | None = None
    dynamic_type: str
    track: Literal["journey", "territory", "crisis", "resource", "status", "world"]
    dimension_key: str
    scene_index: int
    before_scene_index: int | None = None
    source_chapter_index: int | None = None
    change_kind: Literal["initial", "change"]
    before: MapDynamicValueV1 | None = None
    after: MapDynamicValueV1
    spatial_anchor_before: dict | None = None
    spatial_anchor_after: dict | None = None
    source_fact_ids: list[str] = Field(default_factory=list)


class MapDynamicConflict(BaseModel):
    conflict_id: str
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    target_name: str | None = None
    dynamic_type: str
    dimension_key: str
    scene_index: int
    source_fact_ids: list[str] = Field(default_factory=list)
    values: list[MapDynamicValueV1] = Field(default_factory=list)
    spatial_anchors: list[dict] = Field(default_factory=list)
    reason: Literal["same_scene_conflict"] = "same_scene_conflict"


class MapContinuityIssue(BaseModel):
    issue_key: str
    issue_type: Literal[
        "same_scene_conflict",
        "missing_anchor",
        "route_unknown",
        "no_route",
        "blocked_route",
        "path_revision_mismatch",
    ]
    severity: Literal["info", "warning", "danger"]
    target_entity_id: str | None = None
    target_name: str | None = None
    from_scene_index: int
    to_scene_index: int
    source_fact_ids: list[str] = Field(default_factory=list)
    path_ids: list[str] = Field(default_factory=list)
    distance_hex: float | None = Field(None, allow_inf_nan=False)
    message: str
    suggested_observation: dict[str, Any] | None = None


class MapDynamicTimelineScene(BaseModel):
    scene_index: int
    delta_count: int = 0
    candidate_count: int = 0
    conflict_count: int = 0
    continuity_issue_count: int = 0


class MapDynamicTimelineResponse(BaseModel):
    map_id: str
    projection_token: str
    from_scene_index: int | None = None
    to_scene_index: int | None = None
    scenes: list[MapDynamicTimelineScene] = Field(default_factory=list)
    deltas: list[MapDynamicDeltaRead] = Field(default_factory=list)
    candidates: list[MapObservationResponse] = Field(default_factory=list)
    conflicts: list[MapDynamicConflict] = Field(default_factory=list)
    continuity_issues: list[MapContinuityIssue] = Field(default_factory=list)
    untyped_facts: list[MapFactResponse] = Field(default_factory=list)
    undated_facts: list[MapFactResponse] = Field(default_factory=list)
    total: int = 0
    skip: int = 0
    limit: int = 100
    has_more: bool = False


class MapDynamicStateItem(BaseModel):
    target_entity_id: str | None = None
    target_entity_type: str | None = None
    target_name: str | None = None
    dynamic_type: str
    track: Literal["journey", "territory", "crisis", "resource", "status", "world"]
    dimension_key: str
    normalized_value: MapDynamicValueV1
    spatial_anchor: dict | None = None
    source_fact_ids: list[str] = Field(default_factory=list)
    scene_index: int


class MapDynamicStateAtResponse(BaseModel):
    map_id: str
    projection_token: str
    scene_index: int
    items: list[MapDynamicStateItem] = Field(default_factory=list)
    conflicts: list[MapDynamicConflict] = Field(default_factory=list)
    total: int = 0
    skip: int = 0
    limit: int = 100
    has_more: bool = False
