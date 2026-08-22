"""深度导入流水线 LLM 结构化输出 Schema。

Phase 1 (Scene 切分) 与 Phase 2 (按 Scene 实体提取) 的真实 LLM 输出必须
先经过本文件的 Pydantic schema 校验，再写入数据库。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

AliasKind = Literal["name", "title", "identity"]
RelationKind = Literal[
    "state",
    "social",
    "spatial",
    "causal",
    "temporal",
    "epistemic",
    "intentional",
]

_AI_WORLD_ENTITY_TYPES = {
    "character",
    "location",
    "faction",
    "organization",
    "species",
    "group",
    "item",
    "object",
    "event",
    "rule",
    "power_system",
    "secret",
    "legend",
    "resource",
    "concept",
    "creature",
    "skill",
    "ability",
    "artifact",
    "other",
}
_AI_WORLD_ENTITY_TYPE_ALIASES = {
    "人物": "character",
    "人": "character",
    "角色": "character",
    "地点": "location",
    "场所": "location",
    "位置": "location",
    "组织": "organization",
    "势力": "faction",
    "派系": "faction",
    "势力/派系": "faction",
    "种族": "species",
    "族群": "species",
    "群体": "group",
    "团体": "group",
    "物品": "item",
    "道具": "item",
    "物品/装备": "item",
    "物体": "object",
    "对象": "object",
    "事件": "event",
    "事件/活动": "event",
    "规则": "rule",
    "规则/系统": "rule",
    "力量体系": "power_system",
    "超凡体系": "power_system",
    "秘密": "secret",
    "秘密/真相": "secret",
    "设定": "secret",
    "传说": "legend",
    "传说/神话": "legend",
    "资源": "resource",
    "资源/材料": "resource",
    "概念": "concept",
    "概念（抽象）": "concept",
    "生物": "creature",
    "怪物": "creature",
    "生物/怪物": "creature",
    "技能": "skill",
    "能力": "ability",
    "技能/能力": "skill",
    "rule/power_system": "rule",
    "secret/legend": "secret",
    "神器": "artifact",
    "遗物": "artifact",
    "神器/遗物": "artifact",
    "其他": "other",
    "character_ref": "character",
}


def _normalize_ai_world_entity_type(value: Any) -> str:
    text = _coerce_short_text(value).strip()
    normalized = _AI_WORLD_ENTITY_TYPE_ALIASES.get(text, text.lower())
    if normalized not in _AI_WORLD_ENTITY_TYPES:
        raise ValueError(f"Unsupported AI entity_type: {text!r}")
    return normalized


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
    core_conflict: str | None = Field(default=None)
    core_conflict_status: Literal["present", "not_applicable", "uncertain"] = "uncertain"
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int = Field(default=1, ge=1)
    start_anchor: str = Field(default="")
    end_anchor: str = Field(default="")
    boundary_status: Literal["complete", "continues_right", "uncertain"] = "uncertain"
    boundary_basis: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator(
        "title",
        "goal",
        "start_anchor",
        "end_anchor",
        "boundary_basis",
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

    @field_validator("core_conflict", mode="before")
    @classmethod
    def _normalize_optional_conflict(cls, value: Any) -> str | None:
        conflict = _coerce_short_text(value).strip()
        return conflict or None

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_scene_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.0)

    @model_validator(mode="after")
    def _validate_conflict_status(self) -> SceneSliceItem:
        if self.core_conflict_status == "present" and not self.core_conflict:
            raise ValueError(
                "core_conflict is required when core_conflict_status is present"
            )
        if self.core_conflict_status == "not_applicable" and self.core_conflict:
            raise ValueError(
                "core_conflict must be empty when core_conflict_status is not_applicable"
            )
        return self


class SceneWindowEdges(BaseModel):
    """Phase 1a interpretation of text outside the owned window."""

    leading_relation: Literal["new_scene", "continues_from_left", "uncertain"] = (
        "uncertain"
    )
    trailing_relation: Literal["ends_in_input", "continues_right", "uncertain"] = (
        "uncertain"
    )
    reason: str = Field(default="")

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()


class SceneSlicingOutput(BaseModel):
    """Phase 1a LLM output: text window -> locked Scene fields."""

    scenes: list[SceneSliceItem] = Field(default_factory=list)
    window_edges: SceneWindowEdges = Field(default_factory=SceneWindowEdges)


class SceneAnchorRepairOutput(BaseModel):
    """Small-context retry for one unresolved Phase 1a Scene boundary."""

    status: Literal["resolved", "partial", "unresolved"] = "resolved"
    start_anchor: str | None = Field(default=None, min_length=4, max_length=80)
    end_anchor: str | None = Field(default=None, min_length=4, max_length=80)
    reason: str = Field(default="")

    @field_validator("start_anchor", "end_anchor", mode="before")
    @classmethod
    def _normalize_anchor(cls, value: Any, info: ValidationInfo) -> str | None:
        anchor = _coerce_short_text(value).strip()
        if not anchor:
            return None
        if len(anchor) <= 80:
            return anchor
        if info.field_name == "end_anchor":
            return anchor[-80:]
        return anchor[:80]

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_repair_reason(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @model_validator(mode="after")
    def _validate_repair_status(self) -> SceneAnchorRepairOutput:
        supplied = sum(
            anchor is not None for anchor in (self.start_anchor, self.end_anchor)
        )
        if self.status == "resolved" and supplied != 2:
            raise ValueError("resolved anchor repair requires both anchors")
        if self.status == "partial" and supplied != 1:
            raise ValueError("partial anchor repair requires exactly one anchor")
        if self.status == "unresolved" and supplied:
            raise ValueError("unresolved anchor repair must not include anchors")
        return self


class SceneRecoverySegment(BaseModel):
    """One exact, ordered portion of a continuous Phase 1a coverage gap."""

    disposition: Literal["extend_left", "new_scene", "extend_right"]
    start_chapter: int = Field(ge=1)
    end_chapter: int = Field(ge=1)
    start_anchor: str = Field(min_length=4, max_length=80)
    end_anchor: str = Field(min_length=4, max_length=80)
    boundary_basis: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    title: str = Field(default="")
    goal: str = Field(default="")
    core_conflict: str | None = Field(default=None)
    core_conflict_status: Literal["present", "not_applicable", "uncertain"] = "uncertain"
    boundary_status: Literal["complete", "continues_right", "uncertain"] = "uncertain"

    @field_validator(
        "start_anchor",
        "end_anchor",
        "boundary_basis",
        "title",
        "goal",
        mode="before",
    )
    @classmethod
    def _normalize_recovery_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("core_conflict", mode="before")
    @classmethod
    def _normalize_recovery_conflict(cls, value: Any) -> str | None:
        conflict = _coerce_short_text(value).strip()
        return conflict or None

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_recovery_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.0)

    @model_validator(mode="after")
    def _validate_recovery_segment(self) -> SceneRecoverySegment:
        if self.end_chapter < self.start_chapter:
            raise ValueError("end_chapter must not precede start_chapter")
        if self.core_conflict_status == "present" and not self.core_conflict:
            raise ValueError(
                "core_conflict is required when core_conflict_status is present"
            )
        if self.core_conflict_status == "not_applicable" and self.core_conflict:
            raise ValueError(
                "core_conflict must be empty when core_conflict_status is not_applicable"
            )
        if self.disposition == "new_scene":
            if not self.title or not self.goal:
                raise ValueError("new_scene recovery segments require title and goal")
        elif (
            self.title
            or self.goal
            or self.core_conflict
            or self.core_conflict_status != "uncertain"
        ):
            raise ValueError(
                "extend recovery segments must not carry Scene semantic fields"
            )
        return self


class SceneRecoveryOutput(BaseModel):
    """One atomic decision for a continuous Phase 1a coverage gap."""

    status: Literal["resolved", "uncertain"] = "uncertain"
    segments: list[SceneRecoverySegment] = Field(default_factory=list)
    left_right_relation: Literal["separate", "same_scene", "uncertain"] = "uncertain"
    reason: str = Field(default="")

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_recovery_reason(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @model_validator(mode="after")
    def _validate_resolved_segments(self) -> SceneRecoveryOutput:
        if self.status == "resolved" and not self.segments:
            raise ValueError("resolved recovery requires at least one segment")
        if self.status == "uncertain" and self.segments:
            raise ValueError("uncertain recovery must not include segments")
        return self


class SceneEnrichmentOutput(BaseModel):
    """Phase 1b LLM output; locked Scene fields are intentionally absent."""

    emotional_beat: str | None = Field(default=None)
    must_happen: str | None = Field(default=None)
    must_not_happen: str | None = Field(default=None)
    narrative_tag: Literal[
        "draft",
        "hook",
        "inciting_incident",
        "rising_action",
        "climax",
        "valley",
        "transition",
        "payoff",
    ] = "draft"
    narrative_function: str = Field(default="")
    basis: str = Field(default="")
    uncertain_fields: list[
        Literal[
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "narrative_function",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)

    @field_validator(
        "emotional_beat",
        "must_happen",
        "must_not_happen",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        text = _coerce_short_text(value).strip()
        return text or None

    @field_validator("narrative_function", "basis", mode="before")
    @classmethod
    def _normalize_enrichment_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("uncertain_fields", mode="after")
    @classmethod
    def _deduplicate_uncertain_fields(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value, default=0.7)


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
    evidence_quotes: list[str] = Field(default_factory=list)

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
    def _normalize_optional_text(cls, value: Any, info: ValidationInfo) -> str:
        if info.field_name == "entity_type":
            return _normalize_ai_world_entity_type(value)
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

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _normalize_evidence_quotes(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


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
    """P14 alias judgment before deterministic identity materialization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    entity_ref: str = Field(..., min_length=1)
    alias: str = Field(..., min_length=1)
    alias_kind: AliasKind | None = None
    alias_type: str = Field(default="alias", min_length=1, max_length=20)
    identity_scope: Literal["durable", "context_bound", "uncertain"]
    identity_basis: str = Field(..., min_length=1)
    evidence_quotes: list[str] = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value)

    @field_validator("alias", "alias_type", "identity_basis", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _normalize_evidence_quotes(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class Phase2bRelationObservation(BaseModel):
    """P14 relation judgment before deterministic endpoint materialization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_ref: str = Field(..., min_length=1)
    target_ref: str = Field(..., min_length=1)
    relation_kind: RelationKind | None = None
    relation_type: str = Field(..., min_length=1)
    persistence_scope: Literal["enduring", "stateful", "episodic", "uncertain"]
    directionality: Literal["directed", "symmetric"]
    claim_status: Literal["established", "reaffirmed", "changed", "ended"]
    previous_relation_ref: str | None = None
    description: str = Field(..., min_length=1)
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    basis: str = Field(..., min_length=1)
    evidence_quotes: list[str] = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("strength", "confidence", mode="before")
    @classmethod
    def _normalize_scores(cls, value: Any, info: ValidationInfo) -> float | None:
        if info.field_name == "strength" and (value is None or value == ""):
            return None
        return _coerce_score(value)

    @field_validator(
        "relation_type",
        "previous_relation_ref",
        "description",
        "basis",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _coerce_optional_short_text(value)

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _normalize_evidence_quotes(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @model_validator(mode="after")
    def _validate_relation_identity(self) -> Phase2bRelationObservation:
        if self.source_ref == self.target_ref:
            raise ValueError("relation endpoints must be distinct")
        if self.claim_status == "established" and self.previous_relation_ref:
            raise ValueError("established relation cannot reference a previous relation")
        if self.claim_status != "established" and not self.previous_relation_ref:
            raise ValueError(
                "reaffirmed, changed, or ended relation requires previous_relation_ref"
            )
        return self


class Phase2bUncertainItem(BaseModel):
    """Useful P14 alias/relation observation that cannot be safely materialized."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal[
        "alias_identity",
        "relation_endpoint",
        "relation_type",
        "relation_change",
    ]
    related_refs: list[str] = Field(default_factory=list)
    mention_or_claim: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    evidence_quotes: list[str] = Field(default_factory=list)

    @field_validator("mention_or_claim", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("related_refs", "evidence_quotes", mode="before")
    @classmethod
    def _normalize_string_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class AliasRelationExtractionOutput(BaseModel):
    """P14 LLM contract: current Scene -> aliases/relations/uncertainty."""

    model_config = ConfigDict(extra="forbid")

    aliases: list[ExtractedAlias] = Field(default_factory=list)
    relations: list[Phase2bRelationObservation] = Field(default_factory=list)
    uncertain_items: list[Phase2bUncertainItem] = Field(default_factory=list)

    @field_validator("aliases", "relations", "uncertain_items", mode="before")
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


class Phase2aEntityObservation(BaseModel):
    """P13 entity judgment before deterministic identity materialization."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1)
    entity_type: str = Field(default="other")
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    identity_disposition: Literal["new", "existing", "uncertain"]
    matched_existing_ref: str | None = None
    basis: str = ""
    uncertainties: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_entity_type(cls, value: Any) -> str:
        return _normalize_ai_world_entity_type(value)

    @field_validator("importance", "confidence", mode="before")
    @classmethod
    def _normalize_scores(cls, value: Any) -> float:
        return _coerce_score(value)

    @field_validator(
        "summary",
        "public_info",
        "hidden_truth",
        "matched_existing_ref",
        mode="before",
    )
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        return _coerce_optional_short_text(value)

    @field_validator("basis", mode="before")
    @classmethod
    def _normalize_basis(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("uncertainties", "evidence_quotes", mode="before")
    @classmethod
    def _normalize_string_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @model_validator(mode="after")
    def _validate_identity_reference(self) -> Phase2aEntityObservation:
        if self.identity_disposition == "existing" and not self.matched_existing_ref:
            raise ValueError("existing identity requires matched_existing_ref")
        if self.identity_disposition == "new" and self.matched_existing_ref:
            raise ValueError("new identity cannot reference an existing object")
        return self


class Phase2aDeltaObservation(BaseModel):
    """P13 durable state change with exact current-Scene evidence."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    subject_name: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    field: str | None = None
    old: Any | None = None
    new: Any | None = None
    description: str = ""
    basis: str = ""
    uncertainties: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(..., min_length=1)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator(
        "subject_name",
        "category",
        "field",
        "description",
        "basis",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str | None:
        return _coerce_optional_short_text(value)

    @field_validator("uncertainties", "evidence_quotes", mode="before")
    @classmethod
    def _normalize_string_lists(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: Any) -> float:
        return _coerce_score(value)


class Phase2aUncertainItem(BaseModel):
    """Useful P13 observation that cannot safely materialize as an asset."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    description: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    evidence_quotes: list[str] = Field(default_factory=list)

    @field_validator("description", "reason", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _coerce_short_text(value).strip()

    @field_validator("evidence_quotes", mode="before")
    @classmethod
    def _normalize_evidence_quotes(cls, value: Any) -> list[str]:
        return _coerce_string_list(value)


class Phase2aSceneExtractionOutput(BaseModel):
    """P13 LLM contract: current Scene -> durable world continuity observations."""

    model_config = ConfigDict(extra="forbid")

    entities: list[Phase2aEntityObservation] = Field(default_factory=list)
    delta_events: list[Phase2aDeltaObservation] = Field(default_factory=list)
    uncertain_items: list[Phase2aUncertainItem] = Field(default_factory=list)

    @field_validator(
        "entities",
        "delta_events",
        "uncertain_items",
        mode="before",
    )
    @classmethod
    def _normalize_optional_lists(cls, value: Any) -> list[Any]:
        return _coerce_list_or_empty(value)


class SceneEntityExtractionOutput(BaseModel):
    """Materialized Phase 2a result consumed by deterministic persistence."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    delta_events: list[DeltaEvent] = Field(default_factory=list)
    uncertain_items: list[Phase2aUncertainItem] = Field(default_factory=list)

    @field_validator(
        "entities",
        "relations",
        "delta_events",
        "uncertain_items",
        mode="before",
    )
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
    def _normalize_text(cls, value: Any, info: ValidationInfo) -> str:
        if info.field_name == "entity_type":
            return _normalize_ai_world_entity_type(value)
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

    @field_validator(
        "objects",
        "relations",
        "deltas",
        "uncertain_items",
        mode="before",
    )
    @classmethod
    def _normalize_optional_lists(cls, value: Any) -> list[Any]:
        return _coerce_list_or_empty(value)
