"""
Memory 对外契约

定义其他模块可以安全依赖的数据接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Stable Scene-time state contract. Map/Atlas data is not Scene memory.
SCENE_MEMORY_CONTRACT_V1 = 1
SCENE_MEMORY_CONTRACT_V2 = 2
CURRENT_SCENE_MEMORY_CONTRACT_VERSION = SCENE_MEMORY_CONTRACT_V2

SCENE_MEMORY_DIMENSIONS_V1 = (
    "entities",
    "relations",
    "locations",
    "knowledge",
)
SCENE_MEMORY_DIMENSIONS_V2 = (
    *SCENE_MEMORY_DIMENSIONS_V1,
    "timeline",
    "causality",
)
SCENE_MEMORY_DIMENSIONS = SCENE_MEMORY_DIMENSIONS_V2


def scene_memory_dimensions(contract_version: int) -> tuple[str, ...]:
    """Return the exact dimensions covered by a persisted contract version."""
    if contract_version == SCENE_MEMORY_CONTRACT_V1:
        return SCENE_MEMORY_DIMENSIONS_V1
    if contract_version == SCENE_MEMORY_CONTRACT_V2:
        return SCENE_MEMORY_DIMENSIONS_V2
    raise ValueError(f"unsupported Scene memory contract version: {contract_version}")


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
