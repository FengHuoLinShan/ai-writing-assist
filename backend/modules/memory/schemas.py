"""
Memory Pydantic Schema

API 请求/响应和 Facade 输出类型。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# 枚举
# ============================================================

class EventType(StrEnum):
    """记忆事件类型"""
    entity_created = "entity_created"
    entity_updated = "entity_updated"
    entity_removed = "entity_removed"
    entity_moved = "entity_moved"
    relation_established = "relation_established"
    relation_ended = "relation_ended"
    knowledge_changed = "knowledge_changed"
    manual_correction = "manual_correction"


class EventSource(StrEnum):
    """事件来源"""
    ai_extraction = "ai_extraction"
    manual_edit = "manual_edit"


class SnapshotStatus(StrEnum):
    """快照状态"""
    current = "current"
    stale = "stale"


# ============================================================
# 全景子结构
# ============================================================

class EntityInPanorama(BaseModel):
    """全景中的单个实体"""
    id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"


class RelationInPanorama(BaseModel):
    """全景中的单个关系"""
    id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    status: str = "canonical"


class CharacterLocationInPanorama(BaseModel):
    """全景中的角色位置"""
    location_id: str
    text_state: str = ""
    chapter_index: int | None = None


class KnowledgeInPanorama(BaseModel):
    """全景中的角色知识"""
    id: str
    character_id: str
    target_type: str
    target_id: str | None = None
    knowledge_level: str
    known_content: str | None = None
    source_chapter_index: int | None = None
    status: str = "canonical"


# ============================================================
# 全景响应
# ============================================================

class ChapterPanorama(BaseModel):
    """章节关系全景 — memory 模块的核心输出"""

    novel_id: str
    chapter_index: int
    entities: list[EntityInPanorama] = Field(default_factory=list)
    relations: list[RelationInPanorama] = Field(default_factory=list)
    character_locations: dict[str, CharacterLocationInPanorama] = Field(default_factory=dict)
    character_knowledge: list[KnowledgeInPanorama] = Field(default_factory=list)


# ============================================================
# 事件响应
# ============================================================

class MemoryEventResponse(BaseModel):
    """记忆事件响应"""

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    chapter_index: int
    sequence: int
    event_type: str
    entity_id: str | None = None
    entity_type: str | None = None
    snapshot_before: dict[str, Any] | None = None
    snapshot_after: dict[str, Any] = {}
    source: str = "ai_extraction"
    created_at: datetime | None = None

    @field_validator("id", "novel_id", "entity_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str | None:
        if v is None:
            return None
        return str(v)


class EventListResponse(BaseModel):
    """事件列表响应"""
    items: list[MemoryEventResponse]
    total: int


# ============================================================
# 快照响应
# ============================================================

class SnapshotResponse(BaseModel):
    """快照响应"""

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    chapter_index: int
    status: str
    events_until: int | None = None
    created_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return str(v)


class SnapshotListResponse(BaseModel):
    """快照列表响应"""
    items: list[SnapshotResponse]
    total: int


# ============================================================
# 状态查询
# ============================================================

class MemoryStatusResponse(BaseModel):
    """memory 模块状态"""
    novel_id: str
    latest_chapter: int | None = None
    latest_snapshot_chapter: int | None = None
    has_stale: bool = False
    stale_from_chapter: int | None = None
