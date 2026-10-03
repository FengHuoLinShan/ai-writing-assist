"""AI 整理输出 schema（计划 §3.7）— 全部 extra="forbid"，长度上限参照 p20_schemas。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CleanupField = Literal[
    "role",
    "appearance",
    "personality",
    "desire",
    "fear",
    "weakness",
    "current_goal",
    "current_state",
    "stance",
    "voice_style",
    "relationship_summary",
    "summary",
    "public_info",
]


class _AiItemBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_ref: str = Field(min_length=1, max_length=64)
    source_rows: list[str] = Field(default_factory=list, max_length=64)
    evidence: str = Field(default="", max_length=20_000)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=32)


class OutlineChapterPlanItem(_AiItemBase):
    chapter_start: int | None = Field(None, ge=1)
    chapter_end: int | None = Field(None, ge=1)
    title: str = Field(default="", max_length=255)
    must_happen: str = Field(default="", max_length=20_000)
    goal: str = Field(default="", max_length=20_000)
    core_conflict: str = Field(default="", max_length=20_000)
    emotional_beat: str = Field(default="", max_length=20_000)
    pov_name: str = Field(default="", max_length=255)


class OutlineArcItem(_AiItemBase):
    title: str = Field(min_length=1, max_length=255)
    chapter_start: int | None = Field(None, ge=1)
    chapter_end: int | None = Field(None, ge=1)
    arc_goal: str = Field(default="", max_length=20_000)
    core_conflict: str = Field(default="", max_length=20_000)
    climax: str = Field(default="", max_length=20_000)
    result: str = Field(default="", max_length=20_000)
    next_hook: str = Field(default="", max_length=20_000)


class OutlineThreadItem(_AiItemBase):
    name: str = Field(min_length=1, max_length=255)
    thread_type: str = Field(default="", max_length=32)
    summary: str = Field(default="", max_length=20_000)
    visible_goal: str = Field(default="", max_length=20_000)
    hidden_truth: str = Field(default="", max_length=20_000)


class OutlineForeshadowingItem(_AiItemBase):
    name: str = Field(min_length=1, max_length=255)
    surface_meaning: str = Field(default="", max_length=20_000)
    hidden_meaning: str = Field(default="", max_length=20_000)
    seed_chapter: int | None = Field(None, ge=1)
    payoff_chapter: int | None = Field(None, ge=1)
    reinforce_chapters: list[int] = Field(default_factory=list, max_length=128)


class OutlineCreativeCoreItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    premise: str = Field(default="", max_length=20_000)
    tone_and_reader_promise: str = Field(default="", max_length=20_000)
    story_engine: str = Field(default="", max_length=20_000)
    ending_direction: str = Field(default="", max_length=20_000)


class SpreadsheetOutlineConversion(BaseModel):
    """大纲/细纲/总纲结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    creative_core: OutlineCreativeCoreItem | None = None
    arcs: list[OutlineArcItem] = Field(default_factory=list, max_length=200)
    threads: list[OutlineThreadItem] = Field(default_factory=list, max_length=500)
    chapter_plans: list[OutlineChapterPlanItem] = Field(
        default_factory=list,
        max_length=1500,
    )
    foreshadowing: list[OutlineForeshadowingItem] = Field(
        default_factory=list,
        max_length=500,
    )
    unmapped_rows: list[str] = Field(default_factory=list, max_length=500)


class CellCleanupFieldItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: CleanupField
    value: str = Field(min_length=1, max_length=20_000)


class SpreadsheetCellCleanup(BaseModel):
    """长单元格拆字段输出。"""

    model_config = ConfigDict(extra="forbid")

    proposal_ref: str = Field(min_length=1, max_length=64)
    source_rows: list[str] = Field(default_factory=list, max_length=64)
    evidence: str = Field(default="", max_length=20_000)
    uncertain_fields: list[str] = Field(default_factory=list, max_length=32)
    fields: list[CellCleanupFieldItem] = Field(default_factory=list, max_length=16)
    remainder: str = Field(default="", max_length=20_000)


__all__ = [
    "CellCleanupFieldItem",
    "CleanupField",
    "OutlineArcItem",
    "OutlineChapterPlanItem",
    "OutlineCreativeCoreItem",
    "OutlineForeshadowingItem",
    "OutlineThreadItem",
    "SpreadsheetCellCleanup",
    "SpreadsheetOutlineConversion",
]
