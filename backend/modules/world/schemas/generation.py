"""生成中心请求/响应 schema（提示词模板、收敛、探查、语义检视）。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from modules.world.llm_schemas import GeneratedWorldCoreConvergence
from modules.world.schemas._common import (
    AliasKind,
    OptionalUuidStr,
    _normalize_author_entity_type,
)

ObjectDraftTemplate = Literal[
    "none",
    "character",
    "event",
    "item",
    "location",
    "faction",
    "rule",
    "custom",
]

ObjectDraftQualityMode = Literal["fast", "pro"]
GenerationTemplateTargetKind = Literal["world_object"]
GenerationTemplateStatus = Literal["active", "archived"]
GenerationTemplateValidationState = Literal["valid", "warning", "invalid"]


class PromptTemplateVariable(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    label: str | None = Field(default=None, max_length=80)
    type: str = Field(default="text", max_length=32)
    required: bool = False
    default: str | None = Field(default=None, max_length=2000)
    help: str | None = Field(default=None, max_length=500)


class PromptTemplateIssue(BaseModel):
    severity: Literal["P1", "P2", "P3"]
    code: str
    message: str
    path: str | None = None


class GenerationPromptTemplateCreate(BaseModel):
    novel_id: str
    target_kind: GenerationTemplateTargetKind = "world_object"
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    object_template: ObjectDraftTemplate = "custom"
    prompt_text: str = Field(..., min_length=1, max_length=8000)
    variables_json: list[PromptTemplateVariable] = Field(default_factory=list)
    created_by: str | None = Field(default=None, max_length=64)


class GenerationPromptTemplateUpdate(BaseModel):
    template_version: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    object_template: ObjectDraftTemplate | None = None
    prompt_text: str | None = Field(default=None, min_length=1, max_length=8000)
    variables_json: list[PromptTemplateVariable] | None = None
    status: GenerationTemplateStatus | None = None
    updated_by: str | None = Field(default=None, max_length=64)


class GenerationPromptTemplateResponse(BaseModel):
    id: str
    novel_id: str | None = None
    target_kind: str = "world_object"
    template_key: str
    name: str
    description: str | None = None
    object_template: ObjectDraftTemplate = "custom"
    prompt_text: str
    variables_json: list[PromptTemplateVariable] = Field(default_factory=list)
    status: str = "active"
    is_builtin: bool = False
    version_number: int = 1
    content_hash: str = ""
    validation_state: GenerationTemplateValidationState = "valid"
    validation_issues: list[PromptTemplateIssue] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GenerationPromptTemplateListResponse(BaseModel):
    items: list[GenerationPromptTemplateResponse]
    total: int


class GenerationPromptTemplateRevisionResponse(BaseModel):
    id: str
    template_id: str
    novel_id: str
    version_number: int
    name: str
    description: str | None = None
    object_template: ObjectDraftTemplate = "custom"
    prompt_text: str
    variables_json: list[PromptTemplateVariable] = Field(default_factory=list)
    validation_state: GenerationTemplateValidationState = "valid"
    validation_issues: list[PromptTemplateIssue] = Field(default_factory=list)
    content_hash: str
    created_at: datetime | None = None


class PromptTemplateValidateRequest(BaseModel):
    novel_id: str | None = None
    target_kind: GenerationTemplateTargetKind = "world_object"
    object_template: ObjectDraftTemplate = "custom"
    prompt_text: str = Field(..., min_length=1, max_length=8000)
    variables_json: list[PromptTemplateVariable] = Field(default_factory=list)
    template_variables: dict[str, Any] = Field(default_factory=dict)


class PromptTemplateValidateResponse(BaseModel):
    validation_state: GenerationTemplateValidationState
    issues: list[PromptTemplateIssue] = Field(default_factory=list)
    content_hash: str


class PromptTemplatePreviewRequest(BaseModel):
    novel_id: str
    template_id: str | None = None
    template_version: int | None = None
    target_kind: GenerationTemplateTargetKind = "world_object"
    object_template: ObjectDraftTemplate = "custom"
    prompt_text: str | None = Field(default=None, max_length=8000)
    variables_json: list[PromptTemplateVariable] = Field(default_factory=list)
    template_variables: dict[str, Any] = Field(default_factory=dict)


class PromptTemplatePreviewResponse(BaseModel):
    rendered_template: str
    rendered_template_summary: str
    missing_variables: list[str] = Field(default_factory=list)
    token_estimate: int = 0
    validation_state: GenerationTemplateValidationState
    issues: list[PromptTemplateIssue] = Field(default_factory=list)
    content_hash: str
    template_version: int | None = None


class PromptTemplateCopyRequest(BaseModel):
    novel_id: str
    name: str | None = Field(default=None, max_length=80)
    created_by: str | None = Field(default=None, max_length=64)
    prompt_text: str | None = Field(default=None, max_length=8000)
    operation_id: uuid.UUID | None = None


class ObjectDraftChatMessage(BaseModel):
    """生成中心自由共创消息。"""

    role: Literal["user", "assistant"] = "user"
    content: str = Field(..., min_length=1, max_length=20000)


class GenerationContextUsage(BaseModel):
    included: bool = False
    section_key: str = "world_bible_synopsis"
    revision_id: str | None = None
    source_hash: str | None = None
    block_hash: str | None = None
    token_count: int = 0
    stale: bool = False
    fallback: bool = False
    status: str = "not_requested"
    warnings: list[str] = Field(default_factory=list)
    context_snapshot_id: str | None = None
    activation_profile_id: str | None = None
    activation_profile_version: int | None = None
    activation_rule_hash: str | None = None
    activation_source_hashes: list[str] = Field(default_factory=list)


class WorldGenerationProjectSource(BaseModel):
    """Use the project as the generation-center source."""

    kind: Literal["project"] = "project"


class WorldGenerationPublishedSourceBaseline(BaseModel):
    """The author expects the published page to be the active source."""

    kind: Literal["published"] = "published"
    page_version: int = Field(..., ge=1)


class WorldGenerationDraftSourceBaseline(BaseModel):
    """The author expects one exact working draft to be the active source."""

    kind: Literal["draft"] = "draft"
    page_version: int = Field(..., ge=1)
    draft_id: str
    draft_updated_at: datetime


WorldGenerationPageSourceBaseline = Annotated[
    WorldGenerationPublishedSourceBaseline | WorldGenerationDraftSourceBaseline,
    Field(discriminator="kind"),
]


class WorldGenerationPageSource(BaseModel):
    """Use a server-loaded World Bible page or working draft as source."""

    kind: Literal["world_bible_page"] = "world_bible_page"
    page_id: str
    baseline: WorldGenerationPageSourceBaseline


WorldGenerationSourceContext = Annotated[
    WorldGenerationProjectSource | WorldGenerationPageSource,
    Field(discriminator="kind"),
]


class WorldGenerationCoreEntityTarget(BaseModel):
    kind: Literal["core_entity"] = "core_entity"
    template: ObjectDraftTemplate = "none"
    template_name: str | None = Field(default=None, max_length=80)
    template_prompt: str | None = Field(default=None, max_length=8000)
    template_id: str | None = Field(default=None, max_length=128)
    template_version: int | None = Field(default=None, ge=1)
    template_variables: dict[str, Any] = Field(default_factory=dict)


class WorldGenerationExistingPageTarget(BaseModel):
    kind: Literal["world_bible_page"] = "world_bible_page"
    page_id: str


class WorldGenerationNewPageTarget(BaseModel):
    kind: Literal["world_bible_new_page"] = "world_bible_new_page"
    page_type: str = Field(..., min_length=1, max_length=64)
    page_template_key: str | None = Field(default=None, max_length=128)
    page_template_version: int | None = Field(default=None, ge=1)


WorldGenerationTarget = Annotated[
    WorldGenerationCoreEntityTarget
    | WorldGenerationExistingPageTarget
    | WorldGenerationNewPageTarget,
    Field(discriminator="kind"),
]


class WorldGenerationRequestBase(BaseModel):
    """Shared, author-selected inputs for world generation-center operations."""

    novel_id: str
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    expected_checkpoint_id: str | None = Field(default=None, min_length=1, max_length=64)
    selected_history_ids: list[uuid.UUID] = Field(default_factory=list, max_length=40)
    world_state_target_id: str | None = Field(default=None, max_length=128)
    world_state_sections: list[
        Literal[
            "premise",
            "knowledge_layers",
            "rules",
            "reproduction_loops",
            "facets",
            "coupling_chains",
            "situated_tests",
            "pressure_tests",
            "actors",
            "places",
            "institutions",
            "history",
            "dependencies",
            "fiction_core",
        ]
    ] = Field(default_factory=list, max_length=14)
    context_confirmation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    source_context: WorldGenerationSourceContext = Field(
        default_factory=WorldGenerationProjectSource
    )
    target: WorldGenerationTarget
    messages: list[ObjectDraftChatMessage] = Field(default_factory=list, max_length=40)
    pasted_context: str | None = Field(default=None, max_length=60000)
    selected_chapter_indices: list[int] = Field(default_factory=list, max_length=20)
    scene_id: str | None = None
    thread_ids: list[str] = Field(default_factory=list, max_length=20)
    character_ids: list[str] = Field(default_factory=list, max_length=20)
    entity_ids: list[str] = Field(default_factory=list, max_length=40)
    selected_asset_refs: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=40,
    )
    quality_mode: ObjectDraftQualityMode = "fast"
    include_world_synopsis: bool = True
    activation_profile_id: str | None = None
    activation_profile_version: int | None = Field(default=None, ge=1)
    workflow_preset: Literal["default", "world_core"] = "default"

    @model_validator(mode="after")
    def validate_source_target_pair(self) -> WorldGenerationRequestBase:
        selected_world_pages = sum(
            1
            for ref in self.selected_asset_refs
            if str(
                ref.get("type") or ref.get("source_type") or ref.get("target_type") or ""
            )
            in {"world_bible_page", "page"}
        )
        if selected_world_pages > 16:
            raise ValueError("selected_asset_refs supports at most 16 World Bible pages")
        if isinstance(self.target, WorldGenerationExistingPageTarget):
            if not isinstance(self.source_context, WorldGenerationPageSource):
                raise ValueError(
                    "world_bible_page target requires a world_bible_page source"
                )
            if self.target.page_id != self.source_context.page_id:
                raise ValueError("source and target World Bible page must match")
        if self.workflow_preset == "world_core" and not isinstance(
            self.target, WorldGenerationCoreEntityTarget
        ):
            raise ValueError("world_core workflow requires a core_entity target")
        return self


class WorldGenerationChatRequest(WorldGenerationRequestBase):
    operation_id: uuid.UUID | None = None


class WorldGenerationExternalPacket(BaseModel):
    """Client-computed identity for one bounded external return packet."""

    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    packet_index: int = Field(..., ge=1, le=10000)
    packet_total: int | None = Field(default=None, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_position(self) -> WorldGenerationExternalPacket:
        if self.packet_total is not None and self.packet_index > self.packet_total:
            raise ValueError("packet_index cannot exceed packet_total")
        return self


class WorldGenerationConvergenceRequest(WorldGenerationRequestBase):
    """Read-only convergence over the client-visible conversation window."""

    excluded_message_count: int = Field(default=0, ge=0, le=100000)
    external_packet: WorldGenerationExternalPacket | None = None

    @model_validator(mode="after")
    def validate_external_packet_hash(self) -> WorldGenerationConvergenceRequest:
        if self.external_packet is None:
            return self
        packet = (self.pasted_context or "").strip()
        if not packet:
            raise ValueError("external_packet requires pasted_context")
        if len(self.pasted_context or "") > 55_000:
            raise ValueError(
                "external_packet pasted_context cannot exceed 55000 characters"
            )
        actual = hashlib.sha256(self.pasted_context.encode("utf-8")).hexdigest()
        if actual != self.external_packet.sha256:
            raise ValueError("external_packet sha256 does not match pasted_context")
        return self


class WorldGenerationExplorationRequest(WorldGenerationRequestBase):
    """Read-only, one-hop exploration from one World Bible page."""

    depth: Literal[1] = 1

    @model_validator(mode="after")
    def validate_exploration_scope(self) -> WorldGenerationExplorationRequest:
        if not isinstance(self.source_context, WorldGenerationPageSource):
            raise ValueError("exploration requires a World Bible page source")
        if not isinstance(self.target, WorldGenerationNewPageTarget):
            raise ValueError("exploration currently supports one adjacent new page")
        return self


class WorldGenerationSemanticInspectionRequest(WorldGenerationRequestBase):
    """User-triggered semantic inspection of one exact World Bible page source."""

    @model_validator(mode="after")
    def validate_inspection_scope(self) -> WorldGenerationSemanticInspectionRequest:
        if not isinstance(self.source_context, WorldGenerationPageSource):
            raise ValueError("semantic inspection requires a World Bible page source")
        if not isinstance(self.target, WorldGenerationExistingPageTarget):
            raise ValueError("semantic inspection requires an existing World Bible page")
        return self


class WorldGenerationExplorationSelection(BaseModel):
    """The only adjacent target explicitly selected by the author."""

    depth: Literal[1] = 1
    request_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    item_id: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=160)
    gap: str = Field(..., min_length=1, max_length=800)
    why_it_matters: str = Field(..., min_length=1, max_length=1000)
    author_boundary: str = Field(..., min_length=1, max_length=800)
    reverse_check_focus: str = Field(..., min_length=1, max_length=800)
    source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        ...,
        min_length=1,
        max_length=8,
    )


class WorldGenerationSuggestionRequest(WorldGenerationRequestBase):
    revises_suggestion_id: OptionalUuidStr = None
    exploration_selection: WorldGenerationExplorationSelection | None = None

    @model_validator(mode="after")
    def validate_exploration_selection_scope(
        self,
    ) -> WorldGenerationSuggestionRequest:
        if self.exploration_selection is None:
            return self
        if not isinstance(self.source_context, WorldGenerationPageSource):
            raise ValueError("exploration selection requires a World Bible page source")
        if not isinstance(self.target, WorldGenerationNewPageTarget):
            raise ValueError("exploration selection requires an adjacent new page target")
        if self.revises_suggestion_id is not None:
            raise ValueError("exploration selection cannot revise an existing suggestion")
        return self


class WorldGenerationSuggestionTaskRequest(WorldGenerationSuggestionRequest):
    operation_id: uuid.UUID
    # 会话绑定（ADR-0021）：任务成功后把本轮回合与成果引用追加进持久化会话。
    session_id: str | None = Field(default=None, min_length=1, max_length=64)
    session_action: Literal["expand", "connect", "pressure", "consolidate"] | None = None


class WorldGenerationTaskResponse(BaseModel):
    task_id: str
    status: str = "pending"


class WorldGenerationSourceSnapshot(BaseModel):
    kind: Literal["project", "world_bible_page"]
    page_id: str | None = None
    page_version: int | None = None
    draft_id: str | None = None
    draft_updated_at: datetime | None = None
    content_hash: str | None = None
    title: str | None = None


class WorldGenerationChatResponse(BaseModel):
    reply: str
    model: str = ""
    provider: str = ""
    context_usage: GenerationContextUsage | None = None
    source_snapshot: WorldGenerationSourceSnapshot
    knowledge_review: dict[str, Any] | None = None


class WorldBibleSourceRef(BaseModel):
    """世界书 AI 建议来源引用。"""

    source_type: str = Field(..., min_length=1, max_length=64)
    source_id: str | None = None
    source_version: int | None = None
    source_hash: str | None = Field(default=None, max_length=64)
    block_hash: str | None = Field(default=None, max_length=64)
    page_id: str | None = None
    title: str | None = Field(default=None, max_length=255)
    chapter_index: int | None = None


class WorldGenerationConvergenceManifestItem(BaseModel):
    key: str = Field(..., min_length=1, max_length=128)
    kind: Literal[
        "conversation",
        "pasted_context",
        "source_page",
        "chapter",
        "asset",
        "project_background",
    ]
    label: str = Field(..., min_length=1, max_length=255)
    content_hash: str = Field(..., min_length=64, max_length=64)
    source_ref: WorldBibleSourceRef


class WorldGenerationExplorationTarget(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=160)
    gap: str = Field(..., min_length=1, max_length=800)
    why_it_matters: str = Field(..., min_length=1, max_length=1000)
    author_boundary: str = Field(..., min_length=1, max_length=800)
    reverse_check_focus: str = Field(..., min_length=1, max_length=800)
    source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        ...,
        min_length=1,
        max_length=8,
    )
    evidence: list[WorldGenerationConvergenceManifestItem] = Field(
        default_factory=list,
        min_length=1,
        max_length=8,
    )


class WorldGenerationExplorationResponse(BaseModel):
    depth: Literal[1] = 1
    targets: list[WorldGenerationExplorationTarget] = Field(
        default_factory=list,
        max_length=3,
    )
    stop_reason: str = Field(..., min_length=1, max_length=1000)
    request_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    model: str = ""
    provider: str = ""
    context_usage: GenerationContextUsage | None = None
    source_snapshot: WorldGenerationSourceSnapshot
    knowledge_review: dict[str, Any] | None = None


class WorldGenerationSemanticInspectionFinding(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=32)
    author_action: Literal["needs_decision", "can_improve"]
    finding_type: Literal[
        "authority_order",
        "open_question",
        "authorization",
        "projection_lag",
        "other",
    ]
    summary: str = Field(..., min_length=1, max_length=600)
    evidence: str = Field(..., min_length=1, max_length=1200)
    location: str = Field(..., min_length=1, max_length=500)
    next_step: str = Field(..., min_length=1, max_length=800)
    source_keys: list[str] = Field(..., min_length=1, max_length=8)
    evidence_refs: list[WorldGenerationConvergenceManifestItem] = Field(
        ...,
        min_length=1,
        max_length=8,
    )


class WorldGenerationSemanticInspectionReceipt(BaseModel):
    scope_label: str = Field(..., min_length=1, max_length=500)
    source_version: int = Field(..., ge=1)
    target_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    checks_run: list[str] = Field(..., min_length=1, max_length=8)
    not_run: list[str] = Field(..., min_length=1, max_length=12)
    omissions: list[str] = Field(default_factory=list, max_length=12)
    completed_at: datetime


class WorldGenerationSemanticInspectionResponse(BaseModel):
    findings: list[WorldGenerationSemanticInspectionFinding] = Field(
        default_factory=list,
        max_length=8,
    )
    queue_item_ids: list[str] = Field(default_factory=list, max_length=8)
    receipt: WorldGenerationSemanticInspectionReceipt
    model: str = ""
    provider: str = ""
    context_usage: GenerationContextUsage | None = None
    source_snapshot: WorldGenerationSourceSnapshot
    knowledge_review: dict[str, Any] | None = None


class WorldGenerationConvergenceCoverage(BaseModel):
    scope_label: str = Field(..., min_length=1, max_length=500)
    source_count: int = Field(..., ge=0, le=256)
    covered_source_keys: list[str] = Field(default_factory=list, max_length=256)
    missing_source_keys: list[str] = Field(default_factory=list, max_length=256)
    stale_source_keys: list[str] = Field(default_factory=list, max_length=256)
    excluded_message_count: int = Field(default=0, ge=0, le=100000)
    manifest_hash: str = Field(..., min_length=64, max_length=64)
    complete: bool = False
    issues: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list,
        max_length=20,
    )


class WorldGenerationConvergenceDetailSummary(BaseModel):
    before_grouping: int = Field(..., ge=0, le=10000)
    after_deduplication: int = Field(..., ge=0, le=10000)
    retained_in_sources: int = Field(..., ge=0, le=10000)


class WorldGenerationConvergenceDecisionItem(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=32)
    text: str = Field(..., min_length=1, max_length=600)
    suggested_disposition: Literal["include", "open", "discard"] = "open"
    world_core_rule_key: str | None = Field(default=None, min_length=1, max_length=64)
    external_disposition: (
        Literal[
            "compatible",
            "repair",
            "candidate",
            "unmapped",
            "exact_duplicate",
        ]
        | None
    ) = None


class WorldGenerationConvergenceDecisionCard(BaseModel):
    card_id: str = Field(..., min_length=1, max_length=32)
    title: str = Field(..., min_length=1, max_length=160)
    common_ground: list[Annotated[str, Field(max_length=600)]] = Field(
        default_factory=list,
        max_length=8,
    )
    items: list[WorldGenerationConvergenceDecisionItem] = Field(
        ...,
        min_length=1,
        max_length=12,
    )
    dependencies: list[Annotated[str, Field(max_length=600)]] = Field(
        default_factory=list,
        max_length=8,
    )
    affected_targets: list[str] = Field(default_factory=list, max_length=6)
    source_keys: list[str] = Field(..., min_length=1, max_length=256)
    why_now: str = Field(..., min_length=1, max_length=1000)


class WorldCoreHandoff(BaseModel):
    ready_for_handoff: bool = False
    issues: list[str] = Field(default_factory=list, max_length=20)
    author_seed_source_keys: list[str] = Field(default_factory=list, max_length=256)
    rule_count: int = Field(default=0, ge=0, le=7)
    snapshot: GeneratedWorldCoreConvergence | None = None


class WorldGenerationConvergenceResponse(BaseModel):
    coverage: WorldGenerationConvergenceCoverage
    manifest: list[WorldGenerationConvergenceManifestItem] = Field(
        default_factory=list,
        max_length=256,
    )
    detail_summary: WorldGenerationConvergenceDetailSummary
    decision_cards: list[WorldGenerationConvergenceDecisionCard] = Field(
        default_factory=list,
        max_length=7,
    )
    next_boundary: str = Field(default="", max_length=1200)
    model: str = ""
    provider: str = ""
    context_usage: GenerationContextUsage | None = None
    source_snapshot: WorldGenerationSourceSnapshot
    external_packet: WorldGenerationExternalPacket | None = None
    world_core: WorldCoreHandoff | None = None
    knowledge_review: dict[str, Any] | None = None


class CoreEntityDraftSuggestionPayload(BaseModel):
    entity_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=5000)
    public_info: str | None = None
    hidden_truth: str | None = None
    content_json: dict[str, Any] = Field(default_factory=dict)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    importance_level: str = Field(default="normal", max_length=16)
    reveal_level: str = Field(default="author_only", max_length=16)
    source_refs: list[WorldBibleSourceRef] = Field(default_factory=list)
    knowledge_review: dict[str, Any] | None = None

    @field_validator("entity_type")
    @classmethod
    def normalize_author_entity_type_field(cls, value: str) -> str:
        return _normalize_author_entity_type(value)


class EntityAliasSuggestionPayload(BaseModel):
    """待处理别名建议；确认后内联写入目标 CoreEntity。"""

    entity_id: str
    alias: str = Field(..., min_length=1, max_length=255)
    alias_type: str = Field(default="name", min_length=1, max_length=20)
    alias_kind: AliasKind | None = None
    source_chapter_index: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_refs: list[WorldBibleSourceRef] = Field(default_factory=list)
    knowledge_review: dict[str, Any] | None = None

    @field_validator("entity_id")
    @classmethod
    def coerce_alias_entity_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))
