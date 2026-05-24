"""
Geo Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# 通用的 UUID→str 转换函数
# ============================================================

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
    """创建地理地点请求"""

    novel_id: str = Field(
        ...,
        description="小说项目 ID",
    )
    world_entity_id: str = Field(
        ...,
        description="对应的世界对象 ID",
    )
    location_level: str = Field(
        ...,
        description="地点层级：continent/country/region/city/district/landmark/building/room",
    )
    parent_location_id: str | None = Field(
        default=None,
        description="父地点 ID（可选，用于构建地点层级树）",
    )
    x: float | None = Field(
        default=None,
        description="简易相对坐标 X",
    )
    y: float | None = Field(
        default=None,
        description="简易相对坐标 Y",
    )
    position_label: str | None = Field(
        default=None,
        max_length=128,
        description="方位标签，如「王国北部」",
    )
    scale_label: str | None = Field(
        default=None,
        max_length=64,
        description="规模标签，如「数十公里」",
    )
    terrain: str | None = Field(
        default=None,
        max_length=64,
        description="地形",
    )
    climate: str | None = Field(
        default=None,
        max_length=64,
        description="气候",
    )
    access_level: str = Field(
        default="normal",
        max_length=32,
        description="访问级别",
    )
    summary: str | None = Field(
        default=None,
        description="地点概述",
    )
    content_json: dict = Field(
        default_factory=dict,
        description="扩展信息 JSON",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )


class GeoLocationUpdate(BaseModel):
    """更新地理地点请求（所有字段可选）"""

    location_level: Annotated[str | None, Field(None, max_length=32)]
    parent_location_id: Annotated[str | None, Field(None)]
    x: Annotated[float | None, Field(None)]
    y: Annotated[float | None, Field(None)]
    position_label: Annotated[str | None, Field(None, max_length=128)]
    scale_label: Annotated[str | None, Field(None, max_length=64)]
    terrain: Annotated[str | None, Field(None, max_length=64)]
    climate: Annotated[str | None, Field(None, max_length=64)]
    access_level: Annotated[str | None, Field(None, max_length=32)]
    summary: Annotated[str | None, Field(None)]
    content_json: Annotated[dict | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class GeoLocationResponse(BaseModel):
    """地理地点响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    world_entity_id: str
    location_level: str
    parent_location_id: str | None = None
    x: float | None = None
    y: float | None = None
    position_label: str | None = None
    scale_label: str | None = None
    terrain: str | None = None
    climate: str | None = None
    access_level: str = "normal"
    summary: str | None = None
    content_json: dict = {}
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id", "novel_id", "world_entity_id", "parent_location_id",
        mode="before",
    )
    @classmethod
    def coerce_ids_to_str(cls, v: object) -> str | None:
        """将 UUID 转为字符串"""
        if v is None:
            return None
        return _coerce_uuid_to_str(v)


class GeoLocationListResponse(BaseModel):
    """地理地点列表响应"""

    items: list[GeoLocationResponse]
    total: int


# ============================================================
# GeoEdge Schema
# ============================================================

class GeoEdgeCreate(BaseModel):
    """创建地理关系边请求"""

    novel_id: str = Field(..., description="小说项目 ID")
    source_location_id: str = Field(..., description="起点地点 ID")
    target_location_id: str = Field(..., description="终点地点 ID")
    relation_type: str = Field(
        ...,
        description="关系类型：road_to/river_to/inside/north_of/...",
    )
    direction_label: str | None = Field(
        default=None,
        max_length=64,
        description="方向描述",
    )
    distance_label: str | None = Field(
        default=None,
        max_length=64,
        description="距离描述",
    )
    travel_time: str | None = Field(
        default=None,
        max_length=64,
        description="通行时间",
    )
    difficulty: str | None = Field(
        default=None,
        max_length=32,
        description="通行难度",
    )
    visibility: str = Field(
        default="public",
        max_length=32,
        description="可见性",
    )
    condition_text: str | None = Field(
        default=None,
        description="通行条件",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
    )


class GeoEdgeUpdate(BaseModel):
    """更新地理关系边请求（所有字段可选）"""

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

    @field_validator(
        "id", "novel_id", "source_location_id", "target_location_id",
        mode="before",
    )
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
# GeoEra Schema
# ============================================================

class GeoEraCreate(BaseModel):
    """创建历史时期请求"""

    novel_id: str = Field(..., description="小说项目 ID")
    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="历史时期名称",
    )
    order_index: int = Field(
        ...,
        ge=0,
        description="时间顺序索引（小→大=古→今）",
    )
    summary: str | None = Field(default=None, description="时期概述")
    start_event_id: str | None = Field(default=None, description="起始事件 ID")
    end_event_id: str | None = Field(default=None, description="结束事件 ID")
    status: str = Field(default="canonical", max_length=32)


class GeoEraUpdate(BaseModel):
    """更新历史时期请求（所有字段可选）"""

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
# Facade 复合输出 Schema
# ============================================================

class LocationNode(BaseModel):
    """地点树节点"""

    id: str
    location_level: str
    position_label: str | None = None
    x: float | None = None
    y: float | None = None
    access_level: str = "normal"
    summary: str | None = None
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


class EraState(BaseModel):
    """地点在某个历史时期的状态"""

    era_id: str
    era_name: str
    era_order_index: int
    summary: str | None = None
    # 地点在该时期的状态变化
    location_state: dict = {}


class GeoContextBundle(BaseModel):
    """地理上下文组合 — 供其他模块（如 Context Compiler）读取"""

    location: GeoLocationResponse | None = None
    """当前地点信息"""
    parent_locations: list[GeoLocationResponse] = []
    """上级地点链（从父级到根）"""
    child_locations: list[GeoLocationResponse] = []
    """直接子地点"""
    edges: list[GeoEdgeResponse] = []
    """关联的地理关系边"""
    current_era: GeoEraResponse | None = None
    """当前所在历史时期"""
    era_states: list[EraState] = []
    """各历史时期下的地点状态"""
