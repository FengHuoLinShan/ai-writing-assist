from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _uuid_validator(v: object) -> str:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


# ============================================================
# PlotThread
# ============================================================


class PlotThreadCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    thread_type: str = Field(..., max_length=32)
    summary: str | None = None
    visible_goal: str | None = None
    hidden_truth: str | None = None
    start_chapter: int | None = Field(None, ge=1)
    planned_payoff_chapter: int | None = Field(None, ge=1)
    current_stage: str | None = Field(None, max_length=32)
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_memory_ids: list[str] = []
    reader_known_state: str | None = None
    author_known_state: str | None = None
    status: str = "draft"


class PlotThreadUpdate(BaseModel):
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    thread_type: Annotated[str | None, Field(None, max_length=32)]
    summary: Annotated[str | None, Field(None)]
    visible_goal: Annotated[str | None, Field(None)]
    hidden_truth: Annotated[str | None, Field(None)]
    start_chapter: Annotated[int | None, Field(None, ge=1)]
    planned_payoff_chapter: Annotated[int | None, Field(None, ge=1)]
    current_stage: Annotated[str | None, Field(None, max_length=32)]
    related_character_ids: Annotated[list[str] | None, Field(None)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    related_memory_ids: Annotated[list[str] | None, Field(None)]
    reader_known_state: Annotated[str | None, Field(None)]
    author_known_state: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class PlotThreadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    name: str
    thread_type: str
    summary: str | None = None
    visible_goal: str | None = None
    hidden_truth: str | None = None
    start_chapter: int | None = None
    planned_payoff_chapter: int | None = None
    current_stage: str | None = None
    related_character_ids: list = []
    related_entity_ids: list = []
    related_memory_ids: list = []
    reader_known_state: str | None = None
    author_known_state: str | None = None
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class PlotThreadListResponse(BaseModel):
    items: list[PlotThreadResponse]
    total: int


# ============================================================
# OutlineArc
# ============================================================


class OutlineArcCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    arc_index: int | None = Field(None, ge=1)
    start_chapter: int | None = Field(None, ge=1)
    end_chapter: int | None = Field(None, ge=1)
    arc_goal: str | None = None
    core_conflict: str | None = None
    main_opposition: str | None = None
    entry_hook: str | None = None
    midpoint_turn: str | None = None
    climax: str | None = None
    result: str | None = None
    next_hook: str | None = None
    related_thread_ids: list[str] = []
    related_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    status: str = "draft"


class OutlineArcUpdate(BaseModel):
    title: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    arc_index: Annotated[int | None, Field(None, ge=1)]
    start_chapter: Annotated[int | None, Field(None, ge=1)]
    end_chapter: Annotated[int | None, Field(None, ge=1)]
    arc_goal: Annotated[str | None, Field(None)]
    core_conflict: Annotated[str | None, Field(None)]
    main_opposition: Annotated[str | None, Field(None)]
    entry_hook: Annotated[str | None, Field(None)]
    midpoint_turn: Annotated[str | None, Field(None)]
    climax: Annotated[str | None, Field(None)]
    result: Annotated[str | None, Field(None)]
    next_hook: Annotated[str | None, Field(None)]
    related_thread_ids: Annotated[list[str] | None, Field(None)]
    related_character_ids: Annotated[list[str] | None, Field(None)]
    related_entity_ids: Annotated[list[str] | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class OutlineArcResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    title: str
    arc_index: int | None = None
    start_chapter: int | None = None
    end_chapter: int | None = None
    arc_goal: str | None = None
    core_conflict: str | None = None
    main_opposition: str | None = None
    entry_hook: str | None = None
    midpoint_turn: str | None = None
    climax: str | None = None
    result: str | None = None
    next_hook: str | None = None
    related_thread_ids: list = []
    related_character_ids: list = []
    related_entity_ids: list = []
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class OutlineArcListResponse(BaseModel):
    items: list[OutlineArcResponse]
    total: int


# ============================================================
# Scene
# ============================================================


class SceneCreate(BaseModel):
    scene_index: int = Field(..., ge=0)
    title: str | None = Field(None, max_length=255)
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str = "draft"
    source: str = "manual"
    scene_chunks: list[dict] = []
    chapter_ids: list[str] = []
    pov_character_id: str | None = None
    status: str = "draft"


class SceneUpdate(BaseModel):
    scene_index: Annotated[int | None, Field(None, ge=0)]
    title: Annotated[str | None, Field(None, max_length=255)]
    goal: Annotated[str | None, Field(None)]
    core_conflict: Annotated[str | None, Field(None)]
    emotional_beat: Annotated[str | None, Field(None)]
    must_happen: Annotated[str | None, Field(None)]
    must_not_happen: Annotated[str | None, Field(None)]
    narrative_tag: Annotated[str | None, Field(None, max_length=32)]
    source: Annotated[str | None, Field(None, max_length=32)]
    scene_chunks: Annotated[list[dict] | None, Field(None)]
    chapter_ids: Annotated[list[str] | None, Field(None)]
    pov_character_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class SceneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    novel_id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str = "draft"
    source: str = "manual"
    scene_chunks: list = []
    chapter_ids: list = []
    pov_character_id: str | None = None
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class SceneReorderRequest(BaseModel):
    scene_ids: list[str] = Field(
        ..., min_length=1, description="按新顺序排列的 Scene ID 列表"
    )


class SceneReorderResponse(BaseModel):
    updated: int
    total: int


class SceneListResponse(BaseModel):
    items: list[SceneResponse]
    total: int


class SplitChaptersRequest(BaseModel):
    """断章请求：将章节从当前 Scene 移到目标 Scene"""

    chapter_index: int = Field(..., ge=1, description="从第几章开始断")
    target_scene_id: str | None = Field(
        None, description="目标 Scene ID，为空则新建 Scene"
    )
