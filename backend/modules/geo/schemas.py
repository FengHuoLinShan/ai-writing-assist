"""
Geo Pydantic Schema 定义

GeoLocation 现在是扩展表（entity_id PK+FK → core_entities）。
公共字段（name, summary, status）在 core_entities，此模块只处理地理特有字段。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _coerce_uuid_to_str(v: object) -> str:
    """将 UUID 或字符串转为字符串"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


# ============================================================
# GeoLocation Schema
# ============================================================

class GeoLocationCreate(BaseModel):
    """创建地理地点扩展记录 — 在 core_entities 已创建后调用"""

    entity_id: str = Field(..., description="地点 entity_id = core_entities.id")
    novel_id: str = Field(..., description="小说项目 ID")
    location_level: str = Field(..., description="地点层级")
    parent_location_id: str | None = Field(default=None, description="父地点 entity_id")
    x: float | None = Field(default=None, description="简易相对坐标 X")
    y: float | None = Field(default=None, description="简易相对坐标 Y")
    position_label: str | None = Field(default=None, max_length=128, description="方位标签")
    scale_label: str | None = Field(default=None, max_length=64, description="规模标签")
    terrain: str | None = Field(default=None, max_length=64, description="地形")
    climate: str | None = Field(default=None, max_length=64, description="气候")
    access_level: str = Field(default="normal", max_length=32, description="访问级别")
    content_json: dict = Field(default_factory=dict, description="扩展信息 JSON")


class GeoLocationUpdate(BaseModel):
    """更新地理地点扩展字段（所有字段可选）"""

    location_level: Annotated[str | None, Field(None, max_length=32)]
    parent_location_id: Annotated[str | None, Field(None)]
    x: Annotated[float | None, Field(None)]
    y: Annotated[float | None, Field(None)]
    position_label: Annotated[str | None, Field(None, max_length=128)]
    scale_label: Annotated[str | None, Field(None, max_length=64)]
    terrain: Annotated[str | None, Field(None, max_length=64)]
    climate: Annotated[str | None, Field(None, max_length=64)]
    access_level: Annotated[str | None, Field(None, max_length=32)]
    content_json: Annotated[dict | None, Field(None)]


class GeoLocationResponse(BaseModel):
    """地理地点响应 — 不包含 summary/status（在 core_entities）"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    novel_id: str
    location_level: str
    parent_location_id: str | None = None
    x: float | None = None
    y: float | None = None
    position_label: str | None = None
    scale_label: str | None = None
    terrain: str | None = None
    climate: str | None = None
    access_level: str = "normal"
    content_json: dict = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("entity_id", "novel_id", "parent_location_id", mode="before")
    @classmethod
    def coerce_ids_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        return _coerce_uuid_to_str(v)


class GeoLocationListResponse(BaseModel):
    """地理地点列表响应"""

    items: list[GeoLocationResponse]
    total: int


# ============================================================
# GeoEdge Schema (unchanged except FK references core_entities)
# ============================================================

class GeoEdgeCreate(BaseModel):
    """创建地理关系边请求"""

    novel_id: str = Field(..., description="小说项目 ID")
    source_location_id: str = Field(..., description="起点地点 entity_id")
    target_location_id: str = Field(..., description="终点地点 entity_id")
    relation_type: str = Field(..., description="关系类型")
    direction_label: str | None = Field(default=None, max_length=64, description="方向描述")
    distance_label: str | None = Field(default=None, max_length=64, description="距离描述")
    travel_time: str | None = Field(default=None, max_length=64, description="通行时间")
    difficulty: str | None = Field(default=None, max_length=32, description="通行难度")
    visibility: str = Field(default="public", max_length=32, description="可见性")
    condition_text: str | None = Field(default=None, description="通行条件")
    status: str = Field(default="canonical", max_length=32)


class GeoEdgeUpdate(BaseModel):
    """更新地理关系边请求"""

    relation_type: Annotated[str | None, Field(None, max_length=32)]
    direction_label: Annotated[str | None, Field(None, max_length=64)]
    distance_label: Annotated[str | None, Field(None, max_length=64)]
    travel_time: Annotated[str | None, Field(None, max_length=64)]
    difficulty: Annotated[str | None, Field(None, max_length=32)]
    visibility: Annotated[str | None, Field(None, max_length=32)]
    condition_text: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class GeoEdgeResponse(BaseModel):
    """地理关系边响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    source_location_id: str
    target_location_id: str
    relation_type: str
    direction_label: str | None = None
    distance_label: str | None = None
    travel_time: str | None = None
    difficulty: str | None = None
    visibility: str = "public"
    condition_text: str | None = None
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "source_location_id", "target_location_id", mode="before")
    @classmethod
    def coerce_ids_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        return _coerce_uuid_to_str(v)


class GeoEdgeListResponse(BaseModel):
    """地理关系边列表响应"""

    items: list[GeoEdgeResponse]
    total: int


# ============================================================
# GeoEra Schema (unchanged)
# ============================================================

class GeoEraCreate(BaseModel):
    """创建历史时期请求"""

    novel_id: str = Field(..., description="小说项目 ID")
    name: str = Field(..., min_length=1, max_length=128)
    order_index: int = Field(..., ge=0)
    summary: str | None = Field(default=None, description="时期概述")
    start_event_id: str | None = Field(default=None)
    end_event_id: str | None = Field(default=None)
    status: str = Field(default="canonical", max_length=32)


class GeoEraUpdate(BaseModel):
    """更新历史时期请求"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=128)]
    order_index: Annotated[int | None, Field(None, ge=0)]
    summary: Annotated[str | None, Field(None)]
    start_event_id: Annotated[str | None, Field(None)]
    end_event_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class GeoEraResponse(BaseModel):
    """历史时期响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    name: str
    order_index: int
    summary: str | None = None
    start_event_id: str | None = None
    end_event_id: str | None = None
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "start_event_id", "end_event_id", mode="before")
    @classmethod
    def coerce_ids_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        return _coerce_uuid_to_str(v)


class GeoEraListResponse(BaseModel):
    """历史时期列表响应"""

    items: list[GeoEraResponse]
    total: int


# ============================================================
# Facade composite output schemas
# ============================================================

class LocationNode(BaseModel):
    """地点树节点"""

    entity_id: str
    location_level: str
    position_label: str | None = None
    x: float | None = None
    y: float | None = None
    access_level: str = "normal"
    children: list[LocationNode] = []


class TravelConstraintResult(BaseModel):
    """通行约束查询结果"""

    source_id: str
    target_id: str
    has_direct_route: bool = False
    route_type: str | None = None
    direction_label: str | None = None
    distance_label: str | None = None
    travel_time: str | None = None
    difficulty: str | None = None
    visibility: str | None = None
    condition_text: str | None = None
    blocked: bool = False
    blocked_reason: str | None = None
    alternative_routes: list[dict] = []


class RouteQueryRequest(BaseModel):
    """路径计算请求"""

    novel_id: str = Field(..., description="小说项目 ID")
    source_location_id: str = Field(..., description="起点地点 entity_id")
    target_location_id: str = Field(..., description="终点地点 entity_id")
    chapter_index: int = Field(..., ge=0)


class RouteQueryResponse(BaseModel):
    """路径计算响应"""

    is_reachable: bool
    total_travel_hours: float
    recommended_path: list[str] = []
    message: str = ""


class EraState(BaseModel):
    """地点在某个历史时期的状态"""

    era_id: str
    era_name: str
    era_order_index: int
    summary: str | None = None
    location_state: dict = {}


class GeoContextBundle(BaseModel):
    """地理上下文组合"""

    location: GeoLocationResponse | None = None
    parent_locations: list[GeoLocationResponse] = []
    child_locations: list[GeoLocationResponse] = []
    edges: list[GeoEdgeResponse] = []
    current_era: GeoEraResponse | None = None
    era_states: list[EraState] = []
