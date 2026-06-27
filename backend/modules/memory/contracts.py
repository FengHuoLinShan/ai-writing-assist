"""
Memory 对外契约

定义其他模块可以安全依赖的数据接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
