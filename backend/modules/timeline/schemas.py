"""
Timeline Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# 请求 Schema
# ============================================================

class TimelineEventCreate(BaseModel):
    """创建时间线事件请求"""

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="事件标题",
    )
    summary: str = Field(
        ...,
        min_length=1,
        description="事件摘要",
    )
    order_index: int = Field(
        ...,
        ge=0,
        description="事件顺序索引",
    )
    chapter_index: int | None = Field(
        None,
        ge=1,
        description="所属章节索引",
    )
    event_type: str | None = Field(
        None,
        max_length=64,
        description="事件类型",
    )
    related_character_ids: list[str] = Field(
        default_factory=list,
        description="关联角色 ID 列表",
    )
    related_entity_ids: list[str] = Field(
        default_factory=list,
        description="关联世界对象 ID 列表",
    )
    related_thread_ids: list[str] = Field(
        default_factory=list,
        description="关联剧情线 ID 列表",
    )
    related_location_ids: list[str] = Field(
        default_factory=list,
        description="关联地点 ID 列表",
    )
    geo_effects: list[dict[str, Any]] = Field(
        default_factory=list,
        description="地理影响列表",
    )
    visibility: str = Field(
        default="author_only",
        max_length=32,
        description="可见性",
    )
    known_by_character_ids: list[str] = Field(
        default_factory=list,
        description="已知该事件的角色 ID 列表",
    )
    status: str = Field(
        default="candidate",
        max_length=32,
        description="状态",
    )


class TimelineEventUpdate(BaseModel):
    """更新时间线事件请求（所有字段可选）"""

    title: str | None = Field(None, max_length=255, min_length=1)
    summary: str | None = Field(None, min_length=1)
    order_index: int | None = Field(None, ge=0)
    chapter_index: int | None = Field(None, ge=1)
    event_type: str | None = Field(None, max_length=64)
    related_character_ids: list[str] | None = None
    related_entity_ids: list[str] | None = None
    related_thread_ids: list[str] | None = None
    related_location_ids: list[str] | None = None
    geo_effects: list[dict[str, Any]] | None = None
    visibility: str | None = Field(None, max_length=32)
    known_by_character_ids: list[str] | None = None
    status: str | None = Field(None, max_length=32)


# ============================================================
# 响应 Schema
# ============================================================

class TimelineEventResponse(BaseModel):
    """时间线事件响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    title: str
    summary: str
    order_index: int
    chapter_index: int | None = None
    event_type: str | None = None
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    related_location_ids: list[str] = []
    geo_effects: list[dict[str, Any]] = []
    visibility: str = "author_only"
    known_by_character_ids: list[str] = []
    status: str = "candidate"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)

    @field_validator(
        "related_character_ids",
        "related_entity_ids",
        "related_thread_ids",
        "related_location_ids",
        "known_by_character_ids",
        mode="before",
    )
    @classmethod
    def coerce_jsonb_list(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x) if isinstance(x, uuid.UUID) else x for x in v]
        return list(v) if v else []


class TimelineEventListResponse(BaseModel):
    """时间线事件列表响应"""

    items: list[TimelineEventResponse]
    total: int


# ============================================================
# Facade 输出 Schema
# ============================================================

class TimelineEventContext(BaseModel):
    """时间线事件上下文 — 供其他模块读取"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    summary: str
    order_index: int
    chapter_index: int | None = None
    event_type: str | None = None
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_thread_ids: list[str] = []
    related_location_ids: list[str] = []
    geo_effects: list[dict[str, Any]] = []
    visibility: str = "author_only"
    known_by_character_ids: list[str] = []

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)

    @field_validator(
        "related_character_ids",
        "related_entity_ids",
        "related_thread_ids",
        "related_location_ids",
        "known_by_character_ids",
        mode="before",
    )
    @classmethod
    def coerce_jsonb_list(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x) if isinstance(x, uuid.UUID) else x for x in v]
        return list(v) if v else []


class TimelineConflictWarning(BaseModel):
    """时间线冲突警告"""

    type: str = Field(..., description="冲突类型")
    description: str = Field(..., description="冲突描述")
    severity: str = Field(
        default="warning",
        description="严重程度（info / warning / error）",
    )
    source_event_ids: list[str] = Field(
        default_factory=list,
        description="相关事件 ID",
    )
    suggestion: str | None = Field(
        None,
        description="修改建议",
    )
