"""深度导入流水线 LLM 结构化输出 Schema。

Phase 1 (Scene 切分) 与 Phase 2 (按 Scene 实体提取) 的真实 LLM 输出必须
先经过本文件的 Pydantic schema 校验，再写入数据库。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


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


def _coerce_short_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        for key in ("summary", "description", "text", "value", "content", "name"):
            if value.get(key):
                return _coerce_short_text(value[key])
        return "；".join(
            f"{key}: {item}"
            for key, item in value.items()
            if item is not None and str(item).strip()
        )
    return str(value)


def _coerce_optional_short_text(value: Any) -> str | None:
    text = _coerce_short_text(value).strip()
    return text or None


def _coerce_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list | tuple | set):
        return [
            str(item).strip() for item in value if item is not None and str(item).strip()
        ]
    if isinstance(value, str):
        parts = [
            part.strip()
            for chunk in value.splitlines()
            for part in chunk.replace("，", ",").replace("；", ",").split(",")
        ]
        return [part for part in parts if part]
    return [str(value).strip()] if str(value).strip() else []


def _coerce_list_or_empty(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


class SceneChunk(BaseModel):
    """Scene 在章节中的物理片段。"""

    chapter_index: int = Field(..., ge=1)
    start_paragraph: int = Field(default=0, ge=0)
    end_paragraph: int | None = Field(default=None, ge=0)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    source_draft_id: str | None = None
    source_content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    anchor_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    anchor_excerpt: str | None = None

    @model_validator(mode="after")
    def _validate_offsets(self) -> SceneChunk:
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset <= self.start_offset
        ):
            raise ValueError("end_offset must be greater than start_offset")
        return self


class SceneItem(BaseModel):
    """LLM 输出的单个 Scene。"""

    title: str = Field(default="")
    goal: str = Field(default="")
    core_conflict: str = Field(default="")
    emotional_beat: str = Field(default="")
    must_happen: str = Field(default="")
    must_not_happen: str = Field(default="")
    narrative_tag: str = Field(default="draft")
    scene_chunks: list[SceneChunk] = Field(default_factory=list)

    @field_validator("must_happen", "must_not_happen", mode="before")
    @classmethod
    def _normalize_constraint_text(cls, value: Any) -> str:
        return _coerce_short_text(value)

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

    @field_validator("boundary_status", mode="before")
    @classmethod
    def _normalize_boundary_status(cls, value: Any) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, dict):
            for key in ("status", "type", "boundary_status"):
                if value.get(key):
                    return str(value[key])
            return "uncertain"
        return str(value)

    @field_validator("evidence_anchors", "merge_hints", "split_hints", mode="before")
    @classmethod
    def _normalize_diagnostic_list(cls, value: Any) -> list[Any]:
        return _coerce_list_or_empty(value)

    @field_validator("missing_or_uncertain_items", mode="before")
    @classmethod
    def _normalize_missing_items(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class SceneSliceItem(BaseModel):
    """Phase 1a final Scene boundary candidate before enrichment."""

    title: str = Field(default="")
    goal: str = Field(default="")
    core_conflict: str = Field(default="")
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int = Field(default=1, ge=1)
    start_anchor: str = Field(default="")
    end_anchor: str = Field(default="")
    boundary_status: str = Field(default="uncertain")

    @field_validator(
        "title",
        "goal",
        "core_conflict",
        "start_anchor",
        "end_anchor",
        "boundary_status",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("start_chapter", "end_chapter", mode="before")
    @classmethod
    def _normalize_chapter(cls, value: Any) -> int:
        try:
            chapter = int(value)
        except (TypeError, ValueError):
            return 1
        return max(1, chapter)


class SceneSlicingOutput(BaseModel):
    """Phase 1a LLM output: text window -> locked Scene fields."""

    scenes: list[SceneSliceItem] = Field(default_factory=list)


class SceneAnchorRepairOutput(BaseModel):
    """Small-context retry for one unresolved Phase 1a Scene boundary."""

    start_anchor: str = Field(min_length=4, max_length=80)
    end_anchor: str = Field(min_length=4, max_length=80)

    @field_validator("start_anchor", "end_anchor", mode="before")
    @classmethod
    def _normalize_anchor(cls, value: Any, info: ValidationInfo) -> str:
        anchor = _coerce_short_text(value).strip()
        if len(anchor) <= 80:
            return anchor
        if info.field_name == "end_anchor":
            return anchor[-80:]
        return anchor[:80]


class SceneEnrichmentOutput(BaseModel):
    """Phase 1b LLM output; locked Scene fields are intentionally absent."""

    emotional_beat: str = Field(default="")
    must_happen: str = Field(default="")
    must_not_happen: str = Field(default="")
    narrative_tag: str = Field(default="imported")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: str = Field(default="")

    @field_validator(
        "emotional_beat",
        "must_happen",
        "must_not_happen",
        "narrative_tag",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.7)

    @field_validator("needs_review", mode="before")
    @classmethod
    def _normalize_needs_review(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None or value == "":
            return False
        if isinstance(value, int | float):
            return bool(value)
        return str(value).strip().lower() in {"true", "1", "yes", "y", "是", "需要"}


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
    quote: str | None = Field(default=None)
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
        return _coerce_short_text(value)

    @field_validator("quote", mode="before")
    @classmethod
    def _normalize_quote(cls, value: Any) -> str | None:
        return _coerce_optional_short_text(value)

    @field_validator("aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> list[dict] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            value = [value]
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

    @field_validator("relation_type", mode="before")
    @classmethod
    def _normalize_relation_type(cls, value: Any) -> str:
        text = _coerce_short_text(value).strip()
        return text or "related_to"

    @field_validator("description", "quote", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        return _coerce_optional_short_text(value)


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

    @field_validator("quote", mode="before")
    @classmethod
    def _normalize_quote(cls, value: Any) -> str | None:
        return _coerce_optional_short_text(value)


class AliasRelationExtractionOutput(BaseModel):
    """Phase 2b LLM 输出结构：Scene 正文 + 对象索引 → aliases/relations。"""

    aliases: list[ExtractedAlias] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)

    @field_validator("aliases", "relations", mode="before")
    @classmethod
    def _normalize_optional_lists(cls, value: Any) -> list[Any]:
        return _coerce_list_or_empty(value)


class DeltaEvent(BaseModel):
    """Phase 2 LLM 输出的结构化 Delta。"""

    category: str = Field(default="ENTITY_UPDATED")
    field: str | None = Field(default=None)
    old: Any | None = Field(default=None)
    new: Any | None = Field(default=None)
    meta: dict = Field(default_factory=dict)

    @field_validator("meta", mode="before")
    @classmethod
    def _normalize_meta(cls, value: Any) -> dict[str, Any]:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        note = _coerce_optional_short_text(value)
        return {"note": note} if note else {}


class SceneEntityExtractionOutput(BaseModel):
    """Phase 2 LLM 输出结构：Scene 正文 → entities/relations/delta_events。"""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    delta_events: list[DeltaEvent] = Field(default_factory=list)

    @field_validator("entities", "relations", "delta_events", mode="before")
    @classmethod
    def _normalize_optional_lists(cls, value: Any) -> list[Any]:
        return _coerce_list_or_empty(value)


class Phase2WorldObject(BaseModel):
    """Window-level Phase 2 world asset extracted from Scene + text evidence."""

    name: str = Field(..., min_length=1)
    entity_type: str = Field(default="other")
    summary: str = Field(default="")
    aliases: list[str] = Field(default_factory=list)
    suggested_action: str = Field(default="create")
    suggested_existing_name: str = Field(default="")
    importance: str = Field(default="medium")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: str = Field(default="")
    supporting_scene_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "entity_type",
        "summary",
        "suggested_action",
        "suggested_existing_name",
        "importance",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("aliases", "supporting_scene_ids", mode="before")
    @classmethod
    def _normalize_string_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.7)


class Phase2WorldRelation(BaseModel):
    """Window-level Phase 2 relation with Scene evidence."""

    source_name: str = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1)
    relation_type: str = Field(default="related_to")
    description: str = Field(default="")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: str = Field(default="")
    supporting_scene_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "source_name",
        "target_name",
        "relation_type",
        "description",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("supporting_scene_ids", mode="before")
    @classmethod
    def _normalize_scene_ids(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.7)


class Phase2WorldDelta(BaseModel):
    """Window-level Phase 2 durable state change."""

    subject_name: str = Field(default="")
    category: str = Field(default="other")
    field: str = Field(default="")
    old: Any | None = None
    new: Any | None = None
    description: str = Field(default="")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    needs_review: bool = False
    review_reason: str = Field(default="")
    supporting_scene_ids: list[str] = Field(default_factory=list)

    @field_validator(
        "subject_name",
        "category",
        "field",
        "description",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("supporting_scene_ids", mode="before")
    @classmethod
    def _normalize_scene_ids(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.7)


class Phase2WorldUncertainItem(BaseModel):
    """Phase 2 item that should be reviewed instead of written as an asset."""

    description: str = Field(default="")
    reason: str = Field(default="")
    supporting_scene_ids: list[str] = Field(default_factory=list)

    @field_validator("description", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("supporting_scene_ids", mode="before")
    @classmethod
    def _normalize_scene_ids(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class Phase2WorldExtractionOutput(BaseModel):
    """Simplified Phase 2 output: window text + Scene cards -> world assets."""

    objects: list[Phase2WorldObject] = Field(default_factory=list)
    relations: list[Phase2WorldRelation] = Field(default_factory=list)
    deltas: list[Phase2WorldDelta] = Field(default_factory=list)
    uncertain_items: list[Phase2WorldUncertainItem] = Field(default_factory=list)

    @field_validator("objects", "relations", "deltas", "uncertain_items", mode="before")
    @classmethod
    def _normalize_optional_lists(cls, value: Any) -> list[Any]:
        return _coerce_list_or_empty(value)
