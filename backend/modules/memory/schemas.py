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
    character_locations: dict[str, CharacterLocationInPanorama] = Field(
        default_factory=dict
    )
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
    scene_id: str | None = None
    scene_index: int | None = None
    scene_sequence: int | None = None
    dimension: str | None = None

    @field_validator("id", "novel_id", "entity_id", "scene_id", mode="before")
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


SCENE_MEMORY_DIMENSIONS = (
    "entities",
    "relations",
    "locations",
    "knowledge",
)


class SceneCheckpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    scene_id: str
    scene_index: int
    stage_index: int
    dimension: str
    status: str
    source: str
    confirmed: bool
    state_json: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    display_summary: str = ""
    gap_reason: str | None = None
    retry_count: int = 0
    decision_summary: str | None = None
    created_at: datetime | None = None

    @field_validator("id", "novel_id", "scene_id", mode="before")
    @classmethod
    def coerce_checkpoint_uuid(cls, value: object) -> str:
        return str(value)


class SceneCheckpointSetResponse(BaseModel):
    novel_id: str
    scene_id: str
    scene_index: int
    stage_index: int
    scene_title: str | None = None
    coverage_status: str
    items: list[SceneCheckpointResponse] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)


class SceneCheckpointEnsureRequest(BaseModel):
    scene_id: str


class SceneCheckpointRebuildRequest(BaseModel):
    from_scene_id: str | None = None
    dimensions: list[str] = Field(default_factory=lambda: list(SCENE_MEMORY_DIMENSIONS))

    @field_validator("dimensions")
    @classmethod
    def validate_dimensions(cls, value: list[str]) -> list[str]:
        unique = list(dict.fromkeys(value))
        if not unique or any(item not in SCENE_MEMORY_DIMENSIONS for item in unique):
            raise ValueError("unknown memory checkpoint dimension")
        return unique


class SceneCheckpointRepairRequest(BaseModel):
    scene_id: str
    dimension: str
    expected_checkpoint_id: str
    decision: str
    decision_summary: str = Field(..., min_length=2, max_length=2000)
    replacement_summary: str | None = Field(default=None, max_length=12000)
    confirmed: bool = False

    @field_validator("decision_summary")
    @classmethod
    def normalize_decision_summary(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("decision_summary must contain at least 2 characters")
        return normalized

    @field_validator("replacement_summary")
    @classmethod
    def normalize_replacement_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("dimension")
    @classmethod
    def validate_dimension(cls, value: str) -> str:
        if value not in SCENE_MEMORY_DIMENSIONS:
            raise ValueError("unknown memory checkpoint dimension")
        return value

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        if value not in {"keep_current", "replace_with_summary", "confirm_empty"}:
            raise ValueError("unsupported repair decision")
        return value

    @field_validator("confirmed")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("confirmed=true is required")
        return value


class SceneCheckpointRepairResponse(BaseModel):
    scene_id: str
    dimension: str
    rebuilt_scene_count: int
    checkpoint: SceneCheckpointResponse
