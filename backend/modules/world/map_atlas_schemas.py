"""Validated contracts for AI map-atlas planning, review, and display."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

AtlasLevel = Literal["cover", "world", "region", "city", "district", "street", "interior"]
ATLAS_LEVEL_RANK: dict[str, int] = {
    "cover": 0,
    "world": 1,
    "region": 2,
    "city": 3,
    "district": 4,
    "street": 5,
    "interior": 6,
}
AtlasRunKind = Literal["initial", "update", "rebuild", "edit", "regenerate", "upload"]
SpatialFactType = Literal[
    "containment",
    "direction",
    "distance_or_travel",
    "adjacency",
    "route",
    "landmark",
    "terrain_or_water",
    "entrance_or_layout",
    "scale",
]
SpatialFactBasis = Literal["explicit", "inferred", "conflicting"]
AtlasRunStatus = Literal[
    "planning",
    "prompt_review",
    "generating",
    "review_ready",
    "partial",
    "paused",
    "failed",
    "completed",
]
PageGenerationStatus = Literal[
    "prepared",
    "provider_in_flight",
    "uploaded",
    "review_ready",
    "prompt_only",
    "failed",
    "retry_requires_confirmation",
]
PageReviewStatus = Literal["candidate", "adopted", "rejected", "deprecated"]


class AtlasSourceRef(BaseModel):
    model_config = {"extra": "forbid"}

    source_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1, max_length=1000)
    open_target: dict[str, Any] | None = None
    source_hash: str | None = Field(default=None, max_length=128)
    source_status: str | None = Field(default=None, max_length=32)


class AtlasEvidence(BaseModel):
    model_config = {"extra": "forbid"}

    supported: list[str] = Field(default_factory=list, max_length=50)
    visual_fill: list[str] = Field(default_factory=list, max_length=50)
    conflicts: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("supported", "visual_fill", "conflicts")
    @classmethod
    def normalize_items(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("evidence items must be unique")
        return normalized


class SpatialFact(BaseModel):
    """Bounded, server-anchored spatial evidence for atlas image prompts."""

    model_config = {"extra": "forbid"}

    location_key: str = Field(min_length=1, max_length=128)
    fact_type: SpatialFactType
    statement: str = Field(min_length=1, max_length=1000)
    basis: SpatialFactBasis
    source_keys: list[str] = Field(min_length=1, max_length=5)


class SpatialFactBatchResult(BaseModel):
    model_config = {"extra": "forbid"}

    facts: list[SpatialFact] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def validate_fact_limits(self) -> SpatialFactBatchResult:
        per_location: dict[str, int] = {}
        for fact in self.facts:
            per_location[fact.location_key] = per_location.get(fact.location_key, 0) + 1
            if per_location[fact.location_key] > 12:
                raise ValueError("at most 12 spatial facts per location")
        if len(per_location) > 5:
            raise ValueError("at most 5 locations per spatial batch")
        return self


class MapAtlasEvidenceSummary(BaseModel):
    """Safe, small progress summary; never exposes prompts or source identities."""

    model_config = {"extra": "forbid"}

    locations_checked: int = Field(ge=0)
    wiki_pages_used: int = Field(ge=0)
    rag_chunks_used: int = Field(ge=0)
    spatial_facts_used: int = Field(ge=0)
    conflicts: int = Field(ge=0)
    degraded: bool = False
    message: str = Field(default="", max_length=500)

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> MapAtlasEvidenceSummary | None:
        evidence = snapshot.get("spatial_evidence")
        if not isinstance(evidence, dict):
            return None
        return cls.model_validate(
            {
                key: evidence.get(key, 0 if key != "message" else "")
                for key in cls.model_fields
            }
        )


class AtlasAnnotationPlan(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=255)
    position_x: float = Field(ge=0, le=1)
    position_y: float = Field(ge=0, le=1)
    target_plan_key: str | None = Field(default=None, max_length=128)
    source_ref: AtlasSourceRef | None = None


class AtlasNodePlan(BaseModel):
    model_config = {"extra": "forbid"}

    plan_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._:-]*$",
    )
    parent_plan_key: str | None = Field(default=None, max_length=128)
    existing_parent_node_id: str | None = None
    location_entity_id: str | None = None
    title: str = Field(min_length=1, max_length=255)
    level: AtlasLevel
    summary: str = Field(min_length=1, max_length=2000)
    visual_brief: str = Field(min_length=1, max_length=6000)
    evidence: AtlasEvidence = Field(default_factory=AtlasEvidence)
    sources: list[AtlasSourceRef] = Field(default_factory=list, max_length=50)
    annotations: list[AtlasAnnotationPlan] = Field(default_factory=list, max_length=100)


class MapAtlasNodeProposal(BaseModel):
    """Candidate-only node metadata, applied atomically when its page is adopted."""

    model_config = {"extra": "forbid"}

    node_id: UUID
    parent_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    level: AtlasLevel
    summary: str | None = Field(default=None, max_length=2000)
    sort_order: int = Field(ge=0)
    base_node_updated_at: datetime | None = None


class AtlasPlan(BaseModel):
    model_config = {"extra": "forbid"}

    style_brief: str = Field(min_length=1, max_length=4000)
    nodes: list[AtlasNodePlan] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> AtlasPlan:
        location_ids = [
            node.location_entity_id for node in self.nodes if node.location_entity_id
        ]
        if len(location_ids) != len(set(location_ids)):
            raise ValueError("atlas locations must be unique")
        seen: set[str] = set()
        levels: dict[str, AtlasLevel] = {}
        all_keys = {node.plan_key for node in self.nodes}
        if len(all_keys) != len(self.nodes):
            raise ValueError("atlas plan keys must be unique")
        for node in self.nodes:
            if node.evidence.supported and not node.sources:
                raise ValueError("supported atlas evidence requires a retained source")
            if node.parent_plan_key and node.existing_parent_node_id:
                raise ValueError(
                    "atlas node cannot have both a planned and existing parent"
                )
            if node.level in {"cover", "world"} and (
                node.parent_plan_key or node.existing_parent_node_id
            ):
                raise ValueError("atlas cover and world nodes must be roots")
            if node.parent_plan_key is not None and node.parent_plan_key not in seen:
                raise ValueError("atlas parents must appear before their children")
            if node.parent_plan_key is not None:
                parent_level = levels[node.parent_plan_key]
                if ATLAS_LEVEL_RANK[parent_level] >= ATLAS_LEVEL_RANK[node.level]:
                    raise ValueError(
                        "atlas parent level must be strictly above its child"
                    )
            for annotation in node.annotations:
                if (
                    annotation.target_plan_key is not None
                    and annotation.target_plan_key not in all_keys
                ):
                    raise ValueError("annotation target is not part of the atlas plan")
            seen.add(node.plan_key)
            levels[node.plan_key] = node.level
        return self


class MapAtlasRunCreate(BaseModel):
    model_config = {"extra": "forbid"}

    style_note: str | None = Field(default=None, max_length=2000)
    include_working_drafts: bool = False
    include_interiors: bool = False
    layout: Literal["landscape", "square"] = "landscape"
    quality: Literal["standard", "fine"] = "standard"
    full_rebuild: bool = False
    review_image_prompts: bool = False

    @field_validator("style_note")
    @classmethod
    def normalize_style_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MapAtlasRunResponse(BaseModel):
    model_config = {"from_attributes": True, "extra": "forbid"}

    id: str
    novel_id: str
    task_id: str | None = None
    run_kind: AtlasRunKind
    status: AtlasRunStatus
    style_note: str | None = None
    include_working_drafts: bool
    include_interiors: bool
    review_image_prompts: bool
    layout: str
    quality: str
    page_limit: int
    planned_page_count: int
    completed_page_count: int
    stop_requested: bool
    error_code: str | None = None
    error_message: str | None = None
    evidence_summary: MapAtlasEvidenceSummary | None = None
    created_at: datetime
    updated_at: datetime | None = None


class MapAtlasAnnotationResponse(BaseModel):
    model_config = {"from_attributes": True, "extra": "forbid"}

    id: str
    page_id: str
    target_node_id: str | None = None
    label: str
    position_x: float
    position_y: float
    source_ref: dict[str, Any]
    sort_order: int
    updated_at: datetime | None = None


class MapAtlasPageResponse(BaseModel):
    model_config = {"from_attributes": True, "extra": "forbid"}

    id: str
    novel_id: str
    run_id: str
    node_id: str
    derived_from_page_id: str | None = None
    generation_status: PageGenerationStatus
    generation_choice: Literal["internal", "external"]
    review_status: PageReviewStatus
    title: str
    visual_brief: str
    has_generation_prompt: bool
    evidence: dict[str, Any]
    source_manifest: list[dict[str, Any]]
    reference_page_ids: list[str]
    image_url: str | None = None
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None
    sort_order: int
    review_note: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    annotations: list[MapAtlasAnnotationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None


class MapAtlasNodeResponse(BaseModel):
    model_config = {"from_attributes": True, "extra": "forbid"}

    id: str
    novel_id: str
    parent_id: str | None = None
    location_entity_id: str | None = None
    title: str
    level: AtlasLevel
    status: Literal["provisional", "adopted"]
    summary: str | None = None
    sort_order: int
    updated_at: datetime | None = None
    pages: list[MapAtlasPageResponse] = Field(default_factory=list)
    children: list[MapAtlasNodeResponse] = Field(default_factory=list)


class MapAtlasTreeResponse(BaseModel):
    model_config = {"extra": "forbid"}

    mode: Literal["review", "atlas"]
    run: MapAtlasRunResponse | None = None
    nodes: list[MapAtlasNodeResponse] = Field(default_factory=list)
    total_pages: int = 0


class MapAtlasReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}

    expected_updated_at: datetime
    review_note: str | None = Field(default=None, max_length=1000)
    confirm_conflicts: bool = False


class MapAtlasAnnotationUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    label: str | None = Field(default=None, min_length=1, max_length=255)
    position_x: float | None = Field(default=None, ge=0, le=1)
    position_y: float | None = Field(default=None, ge=0, le=1)
    target_node_id: str | None = None
    expected_updated_at: datetime


class MapAtlasRetryRequest(BaseModel):
    model_config = {"extra": "forbid"}

    confirm_possible_duplicate_charge: bool = False


class MapAtlasDerivedRequest(BaseModel):
    model_config = {"extra": "forbid"}

    instruction: str | None = Field(default=None, max_length=4000)
    reference_page_ids: list[str] = Field(default_factory=list, max_length=7)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @field_validator("reference_page_ids")
    @classmethod
    def unique_reference_pages(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(set(normalized)) != len(
            normalized
        ):
            raise ValueError("reference page ids must be unique and non-empty")
        return normalized


class MapAtlasStopResponse(BaseModel):
    model_config = {"extra": "forbid"}

    run_id: str
    stop_requested: bool


class MapAtlasImageConnectionRequired(BaseModel):
    model_config = {"extra": "forbid"}

    code: Literal["image_connection_required"] = "image_connection_required"
    message: str = "请先在账户设置中连接 OpenAI 图片服务"


class MapAtlasPromptResponse(BaseModel):
    model_config = {"extra": "forbid"}

    page_id: str
    prompt: str
    generation_choice: Literal["internal", "external"]
    editable: bool
    updated_at: datetime | None = None


class MapAtlasPromptUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    prompt: str = Field(min_length=1, max_length=65536)
    generation_choice: Literal["internal", "external"]
    expected_updated_at: datetime

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt must not be empty")
        return normalized


class MapAtlasPromptConfirmation(BaseModel):
    model_config = {"extra": "forbid"}

    page_id: UUID
    expected_updated_at: datetime


class MapAtlasConfirmPromptsRequest(BaseModel):
    model_config = {"extra": "forbid"}

    pages: list[MapAtlasPromptConfirmation] = Field(min_length=1, max_length=20)

    @field_validator("pages")
    @classmethod
    def unique_pages(
        cls, value: list[MapAtlasPromptConfirmation]
    ) -> list[MapAtlasPromptConfirmation]:
        if len({item.page_id for item in value}) != len(value):
            raise ValueError("prompt confirmation pages must be unique")
        return value


class MapAtlasNodeUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    parent_id: UUID | None = None
    level: AtlasLevel | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    before_node_id: UUID | None = None
    expected_updated_at: datetime

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be empty")
        return normalized
