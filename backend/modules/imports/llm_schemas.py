"""深度导入流水线 LLM 结构化输出 Schema。

Phase 1 (Scene 切分) 与 Phase 2 (按 Scene 实体提取) 的真实 LLM 输出必须
先经过本文件的 Pydantic schema 校验，再写入数据库。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


def _coerce_score(value: Any, *, default: float = 0.5) -> float:
    """Normalize common LLM confidence/importance spellings to a 0-1 score."""

    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        score = float(value)
        return max(0.0, min(score / 100 if score > 1 else score, 1.0))
    if isinstance(value, str):
        text = value.strip().lower()
        label_scores = {
            "高": 0.9,
            "较高": 0.8,
            "很高": 0.95,
            "中": 0.6,
            "中等": 0.6,
            "一般": 0.5,
            "低": 0.3,
            "较低": 0.25,
            "high": 0.9,
            "medium": 0.6,
            "mid": 0.6,
            "low": 0.3,
        }
        if text in label_scores:
            return label_scores[text]
        if text.endswith("%"):
            text = text[:-1].strip()
            try:
                return max(0.0, min(float(text) / 100, 1.0))
            except ValueError:
                return default
        try:
            score = float(text)
        except ValueError:
            return default
        return max(0.0, min(score / 100 if score > 1 else score, 1.0))
    return default


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


class SceneCandidateOutput(BaseModel):
    """Phase 0/1a 中间候选输出，不直接写入正式 Scene 表。"""

    scenes: list[dict] = Field(default_factory=list)
    boundary_status: str | None = None
    evidence_anchors: list[Any] = Field(default_factory=list)
    merge_hints: list[Any] = Field(default_factory=list)
    split_hints: list[Any] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    missing_or_uncertain_items: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float | None:
        if value is None:
            return None
        return _coerce_score(value)


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

    @field_validator("importance", "confidence", mode="before")
    @classmethod
    def _normalize_scores(cls, value: Any) -> float:
        return _coerce_score(value)

    @field_validator(
        "entity_type",
        "summary",
        "public_info",
        "hidden_truth",
        "suggested_action",
        "candidate_reason",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    @field_validator("aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> list[dict] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            return None
        aliases: list[dict] = []
        for item in value:
            if isinstance(item, str):
                alias = item.strip()
                if alias:
                    aliases.append({"alias": alias, "type": "name"})
            elif isinstance(item, dict):
                alias = str(item.get("alias") or item.get("name") or "").strip()
                if alias:
                    aliases.append(
                        {
                            **item,
                            "alias": alias,
                            "type": item.get("type", "name"),
                        }
                    )
        return aliases or None


class ExtractedRelation(BaseModel):
    """Phase 2 LLM 输出的实体关系。"""

    source_name: str = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1)
    relation_type: str = Field(..., min_length=1)
    description: str | None = Field(default=None)
    quote: str | None = Field(default=None)
    strength: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("strength", mode="before")
    @classmethod
    def _normalize_strength(cls, value: Any) -> float:
        return _coerce_score(value)


class ExtractedAlias(BaseModel):
    """Phase 2b LLM 输出的实体别名候选。"""

    entity_name: str = Field(..., min_length=1)
    alias: str = Field(..., min_length=1)
    alias_type: str = Field(default="alias")
    quote: str | None = Field(default=None)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value)

    @field_validator("alias_type", mode="before")
    @classmethod
    def _normalize_alias_type(cls, value: Any) -> str:
        if value is None:
            return "alias"
        text = str(value).strip()
        return text or "alias"


class AliasRelationExtractionOutput(BaseModel):
    """Phase 2b LLM 输出结构：Scene 正文 + 对象索引 → aliases/relations。"""

    aliases: list[ExtractedAlias] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


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
