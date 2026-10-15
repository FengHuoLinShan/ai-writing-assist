"""Author-facing contracts for the Story scene director."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DirectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _uuid(value: str | uuid.UUID) -> str:
    return str(uuid.UUID(str(value)))


class DirectorBudgetPreviewRequest(DirectorModel):
    operation_id: uuid.UUID
    novel_id: str
    scene_id: str
    character_ids: list[str] = Field(min_length=1)
    rounds: int = Field(default=1, ge=1)
    related_object_ids: list[str] = Field(default_factory=list)
    primary_character_ids: list[str] = Field(default_factory=list)
    instructions: str = Field(default="", max_length=6000)
    intervention: str = Field(default="", max_length=3000)
    public_stimulus: str = Field(default="", max_length=3000)

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return _uuid(value)

    @field_validator("character_ids", "related_object_ids")
    @classmethod
    def normalize_ids(cls, values: list[str]) -> list[str]:
        result = [_uuid(value) for value in values]
        if len(result) != len(set(result)):
            raise ValueError("object selections must be unique")
        return result

    @field_validator("primary_character_ids")
    @classmethod
    def normalize_primary_ids(cls, values: list[str]) -> list[str]:
        result = [_uuid(value) for value in values]
        if len(result) != len(set(result)):
            raise ValueError("primary_character_ids must be unique")
        return result

    @model_validator(mode="after")
    def primary_subset(self):
        if set(self.primary_character_ids) - set(self.character_ids):
            raise ValueError("primary characters must be selected participants")
        return self


class DirectorStartRequest(DirectorBudgetPreviewRequest):
    request_limit: int = Field(ge=1)
    token_limit: int = Field(ge=1)
    time_budget_seconds: int = Field(default=3600, ge=1)
    instructions: str = Field(default="", max_length=6000)
    divergence: Literal["conservative", "balanced", "bold"] = "balanced"
    selected_alternative: str | None = Field(default=None, max_length=120)
    intervention: str = Field(default="", max_length=3000)
    context_confirmation_id: str = Field(min_length=1, max_length=128)
    public_stimulus: str = Field(default="", max_length=3000)
    budget_preview_hash: str = Field(pattern="^[a-f0-9]{64}$")


class DirectorContinueRequest(DirectorModel):
    novel_id: str
    context_confirmation_id: str
    operation_id: uuid.UUID
    parent_round_id: uuid.UUID
    branch_kind: Literal["continue", "reroll", "intervene", "rewrite_character"] = (
        "continue"
    )
    rounds: int = Field(default=1, ge=1)
    additional_requests: int = Field(default=0, ge=0)
    additional_tokens: int = Field(default=0, ge=0)
    basis_choice: Literal["current", "frozen"]
    allow_possible_duplicate_charge: bool = False
    instructions: str = Field(default="", max_length=6000)
    divergence: Literal["conservative", "balanced", "bold"] | None = None
    selected_alternative: str | None = Field(default=None, max_length=120)
    intervention: str = Field(default="", max_length=3000)
    public_stimulus: str = Field(default="", max_length=3000)
    rewrite_character_id: str | None = None
    budget_preview_hash: str = Field(pattern="^[a-f0-9]{64}$")

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)

    @field_validator("rewrite_character_id")
    @classmethod
    def normalize_rewrite_character_id(cls, value: str | None) -> str | None:
        return _uuid(value) if value else None


class DirectorContinueBudgetPreviewRequest(DirectorModel):
    operation_id: uuid.UUID
    novel_id: str
    parent_round_id: uuid.UUID
    rounds: int = Field(default=1, ge=1)
    basis_choice: Literal["current", "frozen"]
    branch_kind: Literal["continue", "reroll", "intervene", "rewrite_character"] = (
        "continue"
    )
    rewrite_character_id: str | None = None
    selected_alternative: str | None = Field(default=None, max_length=120)
    instructions: str = Field(default="", max_length=6000)
    intervention: str = Field(default="", max_length=3000)
    public_stimulus: str = Field(default="", max_length=3000)

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)

    @field_validator("rewrite_character_id")
    @classmethod
    def normalize_rewrite_character_id(cls, value: str | None) -> str | None:
        return _uuid(value) if value else None


class DirectorAdvanceRequest(DirectorContinueRequest):
    """One paid round inside the already authorized root budget."""

    rounds: Literal[1] = 1
    additional_requests: Literal[0] = 0
    additional_tokens: Literal[0] = 0
    allow_possible_duplicate_charge: Literal[False] = False


class DirectorHistoryReadRequest(DirectorModel):
    novel_id: str
    scene_id: str

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return _uuid(value)


class DirectorConsistencyCheckRequest(DirectorModel):
    novel_id: str
    round_id: uuid.UUID

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorDeleteBranchRequest(DirectorModel):
    novel_id: str
    confirm: bool = False

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorDeleteUnstarredRequest(DirectorModel):
    novel_id: str
    scene_id: str
    confirm: bool = False

    @field_validator("novel_id", "scene_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return _uuid(value)


class DirectorCompareRequest(DirectorModel):
    novel_id: str
    round_ids: list[uuid.UUID] = Field(min_length=2, max_length=2)

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorPerformanceBasis(DirectorModel):
    source_kind: Literal[
        "world_dossier",
        "continuity",
        "character_pattern",
        "story_character_card",
        "observed_event",
        "director_inference",
    ]
    source_id: str | None = None
    source_fingerprint: str | None = Field(default=None, pattern="^[a-f0-9]{64}$")
    note: str = Field(min_length=1, max_length=500)


class DirectorPerformance(DirectorModel):
    character_id: str
    action: str = Field(min_length=1, max_length=1800)
    expression: str = Field(min_length=1, max_length=1200)
    body_language: str = Field(min_length=1, max_length=1600)
    voice_and_dialogue: str = Field(min_length=1, max_length=1800)
    subtext: str = Field(min_length=1, max_length=1000)
    motive_and_emotion: str = Field(min_length=1, max_length=1600)
    trigger_and_defense: str = Field(min_length=1, max_length=1200)
    attention: str = Field(min_length=1, max_length=1200)
    ignored: str = Field(min_length=1, max_length=1000)
    change_from_previous: str = Field(min_length=1, max_length=1200)
    basis: list[DirectorPerformanceBasis] = Field(min_length=1, max_length=12)


class DirectorMaterial(DirectorModel):
    material_id: str = Field(min_length=1, max_length=120)
    category: Literal["environment", "object", "crowd", "mood", "pacing", "time"]
    content: str = Field(min_length=1, max_length=1600)
    object_refs: list[dict[str, Any]] = Field(default_factory=list, max_length=16)
    perceiver_ids: list[str] = Field(default_factory=list)
    senses: list[Literal["sight", "sound", "smell", "touch", "taste", "inner"]] = Field(
        default_factory=list
    )
    source_kind: Literal[
        "world_dossier",
        "continuity",
        "character_pattern",
        "story_character_card",
        "observed_event",
        "director_inference",
        "candidate",
    ]
    source_ids: list[str] = Field(default_factory=list)
    source_fingerprints: dict[str, str] = Field(default_factory=dict)
    conflict_status: Literal["clear", "conflict", "unknown"] = "unknown"
    candidate_only: bool = False
    internal_character_id: str | None = None
    perception_status: Literal["known", "impossible", "unknown"] = "unknown"
    perception_note: str = "感知范围无法由当前结构化资料核实"
    disabled_for_character_ids: list[str] = Field(default_factory=list)


class DirectorAngle(DirectorModel):
    angle_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    viewpoint_kind: Literal["character", "omniscient"]
    viewpoint_character_id: str | None = None
    narrative_distance: Literal["interior", "close", "external", "omniscient"]
    focus: str = Field(min_length=1, max_length=600)
    detail_and_pacing: str = Field(min_length=1, max_length=600)
    material_ids: list[str] = Field(default_factory=list)
    disabled_material_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_viewpoint(self):
        if (self.viewpoint_kind == "character") != bool(self.viewpoint_character_id):
            raise ValueError("character viewpoints need exactly one character ID")
        if self.viewpoint_kind == "character" and self.narrative_distance == "omniscient":
            raise ValueError("character viewpoints cannot use omniscient distance")
        return self


class DirectorAlternative(DirectorModel):
    alternative_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)
    branch_instruction: str = Field(min_length=1, max_length=1000)
    divergence: Literal["conservative", "balanced", "bold"]


class DirectorCandidateEvent(DirectorModel):
    candidate_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=180)
    description: str = Field(min_length=1, max_length=1600)
    timepoint: Literal["this_scene", "later"] = "this_scene"
    references: list[dict[str, Any]] = Field(default_factory=list)
    basis: list[DirectorPerformanceBasis] = Field(default_factory=list)
    candidate_only: Literal[True] = True
    applied_to_state: Literal[False] = False


class DirectorSceneMaterials(DirectorModel):
    materials: list[DirectorMaterial] = Field(default_factory=list)
    recommended_angles: list[DirectorAngle] = Field(min_length=2, max_length=3)
    alternatives: list[DirectorAlternative] = Field(min_length=2, max_length=3)
    candidate_events: list[DirectorCandidateEvent] = Field(default_factory=list)


class DirectorConsistencyFinding(DirectorModel):
    severity: Literal["conflict", "unknown", "notice"]
    subject_id: str | None = None
    field: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=1000)
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class DirectorConsistency(DirectorModel):
    coverage: Literal["complete", "partial", "unknown"]
    checked_facts: list[str] = Field(default_factory=list)
    unavailable_checks: list[str] = Field(default_factory=list)
    findings: list[DirectorConsistencyFinding] = Field(default_factory=list)


class DirectorRoundResult(DirectorModel):
    round_number: int = Field(ge=1)
    performances: list[DirectorPerformance] = Field(default_factory=list)
    materials: list[DirectorMaterial] = Field(default_factory=list)
    groups: dict[str, Any] = Field(default_factory=dict)
    omitted: list[dict[str, Any]] = Field(default_factory=list)
    recommended_angles: list[DirectorAngle] = Field(default_factory=list)
    alternatives: list[DirectorAlternative] = Field(default_factory=list)
    candidate_events: list[DirectorCandidateEvent] = Field(default_factory=list)
    consistency: DirectorConsistency
    warnings: list[str] = Field(default_factory=list)
    state_delta: list[dict[str, Any]] = Field(default_factory=list)
    state_after: dict[str, Any] = Field(default_factory=dict)
    observed_events: list[dict[str, Any]] = Field(default_factory=list)


class DirectorUpdateMetadata(DirectorModel):
    novel_id: str
    starred: bool | None = None
    name: str | None = Field(default=None, max_length=180)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorSaveReferenceRequest(DirectorModel):
    novel_id: str
    name: str = Field(min_length=1, max_length=180)
    source_round_id: uuid.UUID
    material_ids: list[str] = Field(min_length=1)
    angle: DirectorAngle
    annotation: str = Field(default="", max_length=3000)

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorPreferenceUpdate(DirectorModel):
    novel_id: str
    cliche_phrases: list[str] = Field(max_length=100)

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorReferenceUpdate(DirectorModel):
    novel_id: str
    name: str | None = Field(default=None, max_length=180)
    annotation: str | None = Field(default=None, max_length=3000)

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorTaskAccepted(DirectorModel):
    task_id: uuid.UUID
    status: str
    run_id: uuid.UUID
    root_id: uuid.UUID


class DirectorMutationRequest(DirectorModel):
    novel_id: str

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorCandidateTransferRequest(DirectorModel):
    novel_id: str
    scene_id: uuid.UUID
    confirmed: Literal[True]
    candidate_id: str = Field(min_length=1, max_length=120)
    entity_type: Literal["character", "item", "location", "concept", "event"]
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("novel_id")
    @classmethod
    def normalize_project(cls, value: str) -> str:
        return _uuid(value)


class DirectorCandidateTransferOperationRequest(DirectorCandidateTransferRequest):
    round_id: uuid.UUID


class DirectorCandidateTransferReceipt(DirectorModel):
    round_id: uuid.UUID
    candidate_id: str
    world_candidate_id: uuid.UUID
    entity_type: str
    status: Literal["candidate"] = "candidate"
    repeated: bool = False
