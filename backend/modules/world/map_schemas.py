"""
World 动态地图 Pydantic Schema — PRD docs/PRD-动态地图功能.md

Create 用 Field(...)，Update 用 Annotated[..., Field(None, ...)]，Response 加 ConfigDict。
UUID 字段统一为 str（用 _uuid_validator 把 ORM 的 UUID 转成 str）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    candidate_location_bindings: list[MapLocationBindingResponse] = Field(
        default_factory=list,
        description="待确认地点绑定图层：关联 CoreEntity.status=candidate",
    )
    candidate_markers: list = Field(
        default_factory=list,
        description="待确认动态标记图层：关联 CoreEntity.status=candidate",
    )
    candidate_territories: list = Field(
        default_factory=list,
        description="待确认势力范围图层：关联 CoreEntity.status=candidate",
    )
    scene: dict | None = None  # P1


# ============================================================
# MapSceneSummary — 写作页轻量地图摘要
# ============================================================


class MapOpenTarget(BaseModel):
    """前端打开地图时使用的稳定目标。"""

    mode: Literal["overview", "recent", "map"]
    map_id: str | None = None
    scene_id: str | None = None
    focus_entity_id: str | None = None
    fallback_reason: str | None = None
    fallback_message: str | None = None


class MapSceneSummaryItem(BaseModel):
    """Scene 摘要里的地点/人物/事件/势力项。"""

    entity_id: str
    name: str
    map_id: str
    hex_q: int | None = None
    hex_r: int | None = None


class MapSceneSummaryWarning(BaseModel):
    """保守的一致性提示。"""

    level: Literal["info", "warning"] = "info"
    code: str
    message: str


class MapSceneSummaryResponse(BaseModel):
    """写作页 Scene 面板消费的轻量地图摘要。"""

    scene_id: str
    primary_location: MapSceneSummaryItem | None = None
    characters: list[MapSceneSummaryItem] = Field(default_factory=list)
    events: list[MapSceneSummaryItem] = Field(default_factory=list)
    factions: list[MapSceneSummaryItem] = Field(default_factory=list)
    warnings: list[MapSceneSummaryWarning] = Field(default_factory=list)
    open_target: MapOpenTarget


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
