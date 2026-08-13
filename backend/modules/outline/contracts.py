from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

SceneSemanticFieldStatus = Literal["present", "not_applicable", "uncertain"]
SCENE_SEMANTIC_FIELD_STATUSES = {
    "present",
    "not_applicable",
    "uncertain",
}
SCENE_SEMANTIC_FIELDS = {
    "core_conflict",
    "emotional_beat",
    "must_happen",
    "must_not_happen",
    "narrative_tag",
    "narrative_function",
}
SceneNarrativeTag = Literal[
    "draft",
    "hook",
    "inciting_incident",
    "rising_action",
    "climax",
    "valley",
    "transition",
    "payoff",
]
SceneBoundaryRelation = Literal[
    "same_scene",
    "duplicate",
    "overlap",
    "separate",
    "uncertain",
]
SceneFusionIntent = Literal[
    "integrate_both",
    "left_is_fragment",
    "right_is_fragment",
]


class SceneBoundaryAssessmentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_candidate_id: str = Field(..., min_length=1)
    right_candidate_id: str = Field(..., min_length=1)
    relation: SceneBoundaryRelation
    fusion_intent: SceneFusionIntent | None = None
    basis: str = ""
    uncertainties: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_fusion_intent(self) -> SceneBoundaryAssessmentContract:
        if self.relation in {"same_scene", "duplicate"}:
            if self.fusion_intent is None:
                raise ValueError("same_scene/duplicate requires fusion_intent")
        elif self.fusion_intent is not None:
            raise ValueError("fusion_intent is only valid for same_scene/duplicate")
        if self.left_candidate_id == self.right_candidate_id:
            raise ValueError("boundary candidates must be distinct")
        return self


class SceneCandidateConcernContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(..., min_length=1)
    concern: str = Field(..., min_length=1)
    basis: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SceneBoundaryReviewOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boundaries: list[SceneBoundaryAssessmentContract] = Field(default_factory=list)
    candidate_concerns: list[SceneCandidateConcernContract] = Field(
        default_factory=list
    )


class SceneFusionSynthesisOutputContract(BaseModel):
    """Shared semantic result for Phase 1c and author-reviewed AI fusion."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    goal: str = Field(..., min_length=1)
    core_conflict: str | None = None
    core_conflict_status: SceneSemanticFieldStatus = "uncertain"
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: SceneNarrativeTag = "draft"
    narrative_function: str | None = None
    basis: str = ""
    uncertain_fields: list[
        Literal[
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "narrative_function",
        ]
    ] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator(
        "title",
        "goal",
        "core_conflict",
        "emotional_beat",
        "must_happen",
        "must_not_happen",
        "narrative_function",
        "basis",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            if info.field_name in {"title", "goal"}:
                raise ValueError(f"{info.field_name} must be a single string")
            parts: list[str] = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, (dict, list, tuple, set)):
                    raise ValueError(f"{info.field_name} contains non-scalar text")
                text = str(item).strip()
                if text:
                    parts.append(text.rstrip("；。"))
            return "；".join(parts) or None
        if isinstance(value, dict):
            raise ValueError(f"{info.field_name} must be text")
        text = str(value).strip()
        return text or None

    @field_validator("uncertain_fields", mode="after")
    @classmethod
    def dedupe_uncertain_fields(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_semantics(self) -> SceneFusionSynthesisOutputContract:
        if not self.title or not self.goal:
            raise ValueError("title and goal must be non-empty")
        if self.core_conflict_status == "present" and not self.core_conflict:
            raise ValueError("present core_conflict requires content")
        if self.core_conflict_status == "not_applicable" and self.core_conflict:
            raise ValueError("not_applicable core_conflict must be null")
        if (
            self.core_conflict_status == "uncertain"
            and "core_conflict" not in self.uncertain_fields
        ):
            self.uncertain_fields.append("core_conflict")
        return self

    def semantic_field_statuses(self) -> dict[str, SceneSemanticFieldStatus]:
        values: dict[str, Any] = {
            "core_conflict": self.core_conflict,
            "emotional_beat": self.emotional_beat,
            "must_happen": self.must_happen,
            "must_not_happen": self.must_not_happen,
            "narrative_tag": (
                None if self.narrative_tag == "draft" else self.narrative_tag
            ),
            "narrative_function": self.narrative_function,
        }
        return {
            field: (
                self.core_conflict_status
                if field == "core_conflict"
                else "uncertain"
                if field in self.uncertain_fields
                else "present"
                if value
                else "not_applicable"
            )
            for field, value in values.items()
        }


@dataclass
class PlotThreadContract:
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
    related_character_ids: list = field(default_factory=list)
    related_entity_ids: list = field(default_factory=list)
    reader_known_state: str | None = None
    author_known_state: str | None = None
    status: str = "draft"


@dataclass
class OutlineArcContract:
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
    related_thread_ids: list = field(default_factory=list)
    related_character_ids: list = field(default_factory=list)
    related_entity_ids: list = field(default_factory=list)
    status: str = "draft"


@dataclass
class SceneContract:
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
    scene_chunks: list = field(default_factory=list)
    chapter_ids: list = field(default_factory=list)
    pov_character_id: str | None = None
    structure_meta: dict = field(default_factory=dict)
    status: str = "draft"


@dataclass(frozen=True)
class SceneExecutionSceneContract:
    """The Scene fields frozen into an execution bundle."""

    id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    pov_character_id: str | None = None
    knowledge_boundary: Any = None
    entry_state: Any = None
    exit_state: Any = None
    outcome: Any = None
    cost: Any = None
    continuity: Any = None
    new_fact_candidates: Any = None
    must_happen: str | None = None
    must_not_happen: str | None = None


@dataclass(frozen=True)
class SceneExecutionBundleContract:
    """Version-pinned, read-only execution input for one Scene."""

    novel_id: str
    scene_id: str
    story_outline_revision_id: str | None
    story_outline_version: int | None
    story_outline_content_hash: str | None
    story_execution_profile: dict[str, Any] | None
    story_execution_profile_hash: str | None
    scene: SceneExecutionSceneContract
    missing_fields: list[str] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)
    upstream_manifest: list[dict[str, str]] = field(default_factory=list)
    contract_hash: str = ""


def scene_semantic_field_status(
    scene: Any,
    field: str,
) -> SceneSemanticFieldStatus | None:
    """Return a trusted semantic status without changing manual Scene semantics.

    Deep-import and author-reviewed fusion Scenes may explicitly distinguish a
    genuinely inapplicable field from an uncertain one.  Legacy/manual Scenes
    deliberately return ``None`` so their historical non-empty/empty behavior
    remains intact in downstream consumers.
    """

    if field not in SCENE_SEMANTIC_FIELDS:
        return None
    if isinstance(scene, dict):
        payload = scene
    elif is_dataclass(scene):
        payload = asdict(scene)
    else:
        payload = {
            "source": getattr(scene, "source", None),
            "structure_meta": getattr(scene, "structure_meta", None),
        }
    source = str(payload.get("source") or "")
    meta = payload.get("structure_meta")
    if not isinstance(meta, dict):
        return None
    semantic_origin = str(meta.get("semantic_origin") or "")
    trusted = source == "deep_import" or source == "manual_fusion" or semantic_origin in {
        "phase1b_enrichment",
        "phase1c_synthesis",
        "author_reviewed_fusion",
        "mechanical_fusion",
        "p20_planned_scene",
    }
    if not trusted:
        return None
    statuses = meta.get("semantic_field_statuses")
    if not isinstance(statuses, dict):
        statuses = meta.get("phase1b_field_statuses")
    status = statuses.get(field) if isinstance(statuses, dict) else None
    if field == "core_conflict" and status is None:
        status = meta.get("core_conflict_status")
    normalized = str(status or "")
    if normalized not in SCENE_SEMANTIC_FIELD_STATUSES:
        return None
    return normalized  # type: ignore[return-value]


@dataclass
class SceneSpanContract:
    id: str
    novel_id: str
    scene_id: str
    chapter_index: int
    content_mode: str = "canonical"
    source_draft_id: str | None = None
    source_content_hash: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    start_paragraph: int | None = None
    end_paragraph: int | None = None
    part_no: int = 0
    mapping_status: str = "chapter_only"
    anchor_hash: str | None = None
    source: str = "manual"
    status: str = "draft"


@dataclass(frozen=True)
class SceneSpanCoverageContract:
    """Project/content-mode SceneSpan location coverage summary."""

    novel_id: str
    content_mode: str
    scene_count: int = 0
    scene_with_span_count: int = 0
    scene_without_span_count: int = 0
    total_span_count: int = 0
    exact_count: int = 0
    reanchored_count: int = 0
    chapter_only_count: int = 0
    unresolved_count: int = 0
    precise_span_count: int = 0
    imprecise_span_count: int = 0
    precise_span_rate: float | None = None
    precise_spans: list[SceneSpanContract] = field(default_factory=list)


@dataclass
class SceneSummaryCheckpointContract:
    id: str
    novel_id: str
    scene_id: str
    content_mode: str
    through_chapter: int
    through_offset: int | None
    summary: str
    source_refs: list[dict] = field(default_factory=list)
    based_on_hash: str = ""
    source: str = "derived"
    status: str = "ready"


@dataclass
class NeighborSceneBriefContract:
    """A spoiler-safe prior Scene summary for context activation."""

    scene_id: str
    novel_id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    chapter_indices: list[int] = field(default_factory=list)
    scene_chunks: list[dict] = field(default_factory=list)


@dataclass
class SceneContextWindowContract:
    """Current Scene plus prior-only metadata exposed at the outline seam."""

    novel_id: str
    scene: SceneContract
    scene_spans: list[SceneSpanContract] = field(default_factory=list)
    previous_briefs: list[NeighborSceneBriefContract] = field(default_factory=list)


@dataclass(frozen=True)
class OutlineAnalysisContextContract:
    """Ordered outline assets that overlap one author-confirmed chapter range."""

    novel_id: str
    start_chapter: int
    end_chapter: int
    scenes: list[dict] = field(default_factory=list)
    arcs: list[dict] = field(default_factory=list)
    plot_threads: list[dict] = field(default_factory=list)
    foreshadowing_plans: list[dict] = field(default_factory=list)
    reveal_plans: list[dict] = field(default_factory=list)
    related_character_ids: list[str] = field(default_factory=list)
    related_entity_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReaderRevealDecisionContract:
    """Reader-visible state for one target at a conservative chapter cursor."""

    target_type: str
    target_id: str
    has_policy: bool = False
    revealed: bool = True
    reveal_chapter: int | None = None
    reveal_content: str | None = None
