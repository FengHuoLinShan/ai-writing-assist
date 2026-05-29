"""Context Compiler 类型定义"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompileOptions:
    """编译选项"""

    novel_id: str
    task: str
    scope: str
    chapter_index: int | None = None
    arc_id: str | None = None
    entity_ids: list[str] | None = None
    character_ids: list[str] | None = None
    location_ids: list[str] | None = None
    reveal_mode: str = "author_safe"
    """揭示模式：author_safe / author_full / reader / character"""
    viewpoint_character_id: str | None = None
    """视角人物 ID（reveal_mode="character" 时必填）"""
    enable_geo_filter: bool = False
