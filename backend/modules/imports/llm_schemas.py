"""深度导入流水线 LLM 结构化输出 Schema。

Phase 1 (Scene 切分) 与 Phase 2 (按 Scene 实体提取) 的真实 LLM 输出必须
先经过本文件的 Pydantic schema 校验，再写入数据库。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SceneChunk(BaseModel):
    """Scene 在章节中的物理片段。"""

    chapter_index: int = Field(..., ge=1)
    start_paragraph: int = Field(default=0, ge=0)
    end_paragraph: int | None = Field(default=None, ge=0)


class SceneItem(BaseModel):
    """LLM 输出的单个 Scene。"""

    title: str = Field(default="")
    goal: str = Field(default="")
    core_conflict: str = Field(default="")
    emotional_beat: str = Field(default="")
    narrative_tag: str = Field(default="draft")
    scene_chunks: list[SceneChunk] = Field(default_factory=list)

    @field_validator("scene_chunks")
    @classmethod
    def _ensure_at_least_one_chunk(cls, v: list[SceneChunk]) -> list[SceneChunk]:
        if not v:
            return [SceneChunk(chapter_index=1)]
        return v


class SceneSegmentationOutput(BaseModel):
    """Phase 1 LLM 输出结构：章节正文 → scenes[]。"""

    scenes: list[SceneItem] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    """Phase 2 LLM 输出的单个世界对象。"""

    name: str = Field(..., min_length=1)
    entity_type: str = Field(default="character")
    summary: str = Field(default="")
    public_info: str = Field(default="")
    hidden_truth: str = Field(default="")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    suggested_action: str = Field(default="create_new")
    suggested_existing_entity_name: str | None = Field(default=None)
    candidate_reason: str = Field(default="")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    aliases: list[dict] | None = Field(default=None)


class ExtractedRelation(BaseModel):
    """Phase 2 LLM 输出的实体关系。"""

    source_name: str = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1)
    relation_type: str = Field(..., min_length=1)
    description: str | None = Field(default=None)
    quote: str | None = Field(default=None)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)


class DeltaEvent(BaseModel):
    """Phase 2 LLM 输出的结构化 Delta。"""

    category: str = Field(default="ENTITY_UPDATED")
    field: str | None = Field(default=None)
    old: Any | None = Field(default=None)
    new: Any | None = Field(default=None)
    meta: dict = Field(default_factory=dict)


class SceneEntityExtractionOutput(BaseModel):
    """Phase 2 LLM 输出结构：Scene 正文 → entities/relations/delta_events。"""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    delta_events: list[DeltaEvent] = Field(default_factory=list)
