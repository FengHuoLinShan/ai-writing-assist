"""
Memory 对外契约

定义其他模块可以安全依赖的数据接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Stable Scene-time state contract. Map/Atlas data is not Scene memory.
SCENE_MEMORY_DIMENSIONS = (
    "entities",
    "relations",
    "locations",
    "knowledge",
)


@dataclass(frozen=True)
class MemoryEventContract:
    """记忆事件契约"""

    id: str
    chapter_index: int
    event_type: str
    entity_id: str | None = None
    entity_type: str | None = None
    snapshot_after: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChapterPanoramaContract:
    """章节全景契约"""

    novel_id: str
    chapter_index: int
    entities: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    character_locations: dict[str, dict[str, Any]] = field(default_factory=dict)
    character_knowledge: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryContinuityEvidenceContract:
    """Stable memory continuity evidence for writing conflict checks."""

    source_module: str
    source_type: str
    source_id: str
    source_label: str
    source_field: str
    source_excerpt: str
    open_target: dict[str, Any]


@dataclass(frozen=True)
class MemoryDeltaEventIngest:
    """Typed delta event input owned by memory ingestion."""

    scene_index: int
    category: str
    field_path: str | None
    old_value: Any = None
    new_value: Any = None
    source: str = "deep_import"
    meta: dict[str, Any] = field(default_factory=dict)
    workflow_id: str | None = None
    scene_id: str | None = None
    scene_provenance_key: str | None = None
    context_snapshot_id: str | None = None
    source_chapter_index: int | None = None


@dataclass(frozen=True)
class MemoryDeltaIngestResult:
    """Stable result of a delta event ingestion batch."""

    count: int
    delta_logs: list[dict[str, Any]]


@dataclass(frozen=True)
class SceneCheckpointRepairResult:
    scene_id: str
    dimension: str
    rebuilt_scene_count: int
