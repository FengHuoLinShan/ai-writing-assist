"""
World Pydantic Schema 定义 — v3 因果时空网

用于 API 请求/响应校验和 Facade 输出。
包含 AI 提取契约、CRUD Schema、Facade 输出 Schema。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from modules.world.llm_schemas import (
    GeneratedWorldCoreConvergence,
    GeneratedWorldGenerationDecisionState,
)

# ============================================================
# 内部工具
# ============================================================


def _uuid_validator(v: object) -> str:
    """将 UUID 原始值转为字符串"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _optional_uuid_validator(v: object) -> str | None:
    """将可空 UUID 转为字符串"""
    if v is None:
        return None
    return _uuid_validator(v)


def _validate_lower_sha256(value: str, field_name: str) -> str:
    if value != value.lower() or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _normalize_system_entity_type(v: str) -> str:
    """Lazy import to avoid schemas <-> services package initialization cycles."""
    from modules.world.services.core.entity_types import normalize_system_entity_type

    return normalize_system_entity_type(v)


def _normalize_author_entity_type(v: str) -> str:
    from modules.world.services.core.entity_types import normalize_author_entity_type

    return normalize_author_entity_type(v)


# ============================================================
# AI 提取契约
# ============================================================


class ExtractedEntity(BaseModel):
    """AI 提取的实体"""

    entity_type: str = Field(
        ...,
        description="受支持实体类型（如 character/faction/item）",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="实体名称",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="别名列表",
    )
    summary: str | None = Field(
        None,
        description="概要描述",
    )
    content_json: dict = Field(
        default_factory=dict,
        description="扩展属性 JSON",
    )

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type_field(cls, v: str) -> str:
        return _normalize_system_entity_type(v)


class ExtractedRelationship(BaseModel):
    """AI 提取的关系"""

    source_name: str = Field(
        ...,
        min_length=1,
        description="源实体名称",
    )
    target_name: str = Field(
        ...,
        min_length=1,
        description="目标实体名称",
    )
    relation_type: str = Field(
        ...,
        description="关系类型（自由字符串）",
    )
    description: str | None = Field(
        None,
        description="关系描述",
    )
    quote: str = Field(
        ...,
        description="原文依据",
    )


class ExtractionOutput(BaseModel):
    """AI 提取输出"""

    entities: list[ExtractedEntity] = Field(
        default_factory=list,
        description="提取的实体列表",
    )
    relationships: list[ExtractedRelationship] = Field(
        default_factory=list,
        description="提取的关系列表",
    )


class WorldAliasRelationExtractRequest(BaseModel):
    """手动别名/关系补抽请求。"""

    novel_id: str
    context_confirmation_id: str
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)
    scene_ids: list[str] | None = Field(default=None)
    operation_id: uuid.UUID | None = None


class WorldAliasRelationExtractResponse(BaseModel):
    """手动别名/关系补抽入队响应。"""

    task_id: str
    status: str = "pending"


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
    pass


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
    revises_suggestion_id: str | None = None
    exploration_selection: WorldGenerationExplorationSelection | None = None

    @field_validator("revises_suggestion_id", mode="before")
    @classmethod
    def coerce_revision_parent_uuid(cls, value: object) -> str | None:
        return _optional_uuid_validator(value)

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


class AskWorldQuestionRequest(BaseModel):
    novel_id: str
    question: str = Field(..., min_length=2, max_length=2000)


class AskWorldCitation(BaseModel):
    citation_key: str = Field(..., min_length=1, max_length=160)
    kind: Literal["world_bible_page", "world_object", "manuscript"]
    title: str = Field(..., min_length=1, max_length=255)
    snippet: str = Field(default="", max_length=2000)
    source_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    source_version: int | None = Field(default=None, ge=1)
    page_id: str | None = None
    chapter_index: int | None = Field(default=None, ge=1)
    source_ref: dict[str, Any] | None = None
    target_ref: dict[str, Any] | None = None
    index_fresh: bool = True


class AskWorldClaim(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    citation_keys: list[str] = Field(..., min_length=1, max_length=3)


class AskWorldEvidenceTrace(BaseModel):
    included_titles: list[str] = Field(default_factory=list, max_length=5)
    excluded_count: int = Field(default=0, ge=0)
    truncated_titles: list[str] = Field(default_factory=list, max_length=5)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    degraded: bool = False
    checks_run: list[str] = Field(default_factory=list, max_length=10)
    not_run: list[str] = Field(default_factory=list, max_length=10)


class AskWorldResponse(BaseModel):
    question: str
    answer: str
    claims: list[AskWorldClaim] = Field(default_factory=list, max_length=8)
    uncertainty: str = Field(default="", max_length=2000)
    no_answer: bool = False
    citations: list[AskWorldCitation] = Field(default_factory=list, max_length=5)
    response_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    evidence_trace: AskWorldEvidenceTrace
    model: str = ""
    provider: str = ""
    context_snapshot_id: str | None = None

    @model_validator(mode="after")
    def validate_citations(self) -> AskWorldResponse:
        known = {item.citation_key for item in self.citations}
        if any(key not in known for claim in self.claims for key in claim.citation_keys):
            raise ValueError("claim references an unknown citation")
        if self.no_answer and self.claims:
            raise ValueError("no-answer response cannot contain claims")
        return self


class AskWorldSaveRequest(BaseModel):
    novel_id: str
    question: str = Field(..., min_length=2, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=6000)
    claims: list[AskWorldClaim] = Field(..., min_length=1, max_length=8)
    uncertainty: str = Field(default="", max_length=2000)
    citations: list[AskWorldCitation] = Field(..., min_length=1, max_length=5)
    response_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_citations(self) -> AskWorldSaveRequest:
        known = {item.citation_key for item in self.citations}
        if len(known) != len(self.citations):
            raise ValueError("citation keys must be unique")
        if any(key not in known for claim in self.claims for key in claim.citation_keys):
            raise ValueError("claim references an unknown citation")
        return self


class AskWorldCitationOpenRequest(BaseModel):
    novel_id: str
    citation: AskWorldCitation


class AskWorldCitationOpenResponse(BaseModel):
    status: Literal["current", "stale", "unavailable"]
    kind: Literal["world_bible_page", "world_object", "manuscript"]
    title: str
    text: str = ""
    source_hash: str | None = None
    page_id: str | None = None
    chapter_index: int | None = None
    warnings: list[str] = Field(default_factory=list, max_length=10)


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

    @field_validator("entity_type")
    @classmethod
    def normalize_author_entity_type_field(cls, value: str) -> str:
        return _normalize_author_entity_type(value)


class EntityRelationSuggestionPayload(BaseModel):
    """待处理关系建议；确认后由 world 创建已采用关系。"""

    source_id: str
    target_id: str
    relation_type: str = Field(..., min_length=1, max_length=64)
    description: str | None = None
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    source_chapter_id: str | None = None
    quote: str | None = None
    source_refs: list[WorldBibleSourceRef] = Field(default_factory=list)

    @field_validator("source_id", "target_id", "source_chapter_id")
    @classmethod
    def coerce_optional_relation_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(uuid.UUID(value))


class EntityAliasSuggestionPayload(BaseModel):
    """待处理别名建议；确认后内联写入目标 CoreEntity。"""

    entity_id: str
    alias: str = Field(..., min_length=1, max_length=255)
    alias_type: str = Field(default="name", max_length=20)
    source_chapter_index: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_refs: list[WorldBibleSourceRef] = Field(default_factory=list)

    @field_validator("entity_id")
    @classmethod
    def coerce_alias_entity_uuid(cls, value: str) -> str:
        return str(uuid.UUID(value))


# ============================================================
# CoreEntity Schema
# ============================================================


class CoreEntityCreate(BaseModel):
    """创建核心实体请求"""

    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="受支持实体类型",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="实体名称",
    )
    summary: str | None = Field(
        None,
        max_length=5000,
        description="概要",
    )
    public_info: str | None = Field(
        None,
        description="对外公开信息",
    )
    hidden_truth: str | None = Field(
        None,
        description="隐藏真相（仅作者视角）",
    )
    content_json: dict | None = Field(
        default=None,
        description="扩展信息 JSON",
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="重要性 0.0~1.0",
    )
    importance_level: str = Field(
        default="normal",
        max_length=16,
        description="重要性级别：core/important/normal/temporary",
    )
    reveal_level: str = Field(
        default="author_only",
        max_length=16,
        description="揭示层级：author_only/hinted/revealed/fully_known",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )
    created_by: str | None = Field(
        None,
        max_length=64,
        description="创建者标识",
    )
    approved_by: str | None = Field(
        None,
        max_length=64,
        description="采用者标识；已采用对象默认与创建者一致",
    )
    force_create: bool = Field(
        default=False,
        description="强制创建，跳过去重检查（当前 create 不主动去重）",
    )

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type_field(cls, v: str) -> str:
        return _normalize_author_entity_type(v)


class CoreEntityUpdate(BaseModel):
    """更新核心实体请求（所有字段可选）"""

    entity_type: Annotated[
        str | None,
        Field(None, min_length=1, max_length=64, description="受支持实体类型"),
    ]
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    summary: Annotated[str | None, Field(None)]
    public_info: Annotated[str | None, Field(None)]
    hidden_truth: Annotated[str | None, Field(None)]
    content_json: Annotated[dict | None, Field(None)]
    importance: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    importance_level: Annotated[str | None, Field(None, max_length=16)]
    reveal_level: Annotated[str | None, Field(None, max_length=16)]
    status: Annotated[str | None, Field(None, max_length=32)]
    approved_by: Annotated[str | None, Field(None, max_length=64)]

    @field_validator("entity_type")
    @classmethod
    def normalize_entity_type_field(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_author_entity_type(v)


class EntityRankingResponse(BaseModel):
    semantic_importance: float = Field(ge=0.0, le=1.0)
    recent_heat: float = Field(ge=0.0, le=1.0)
    combined_score: float = Field(ge=0.0, le=1.0)
    labels: list[Literal["important", "hot"]] = Field(default_factory=list)
    last_appearance_chapter: int | None = Field(default=None, ge=1)
    recent_12_chapter_occurrences: int = Field(default=0, ge=0)


class EntityTypeFacet(BaseModel):
    entity_type: str
    count: int = Field(ge=0)


class EntityRankingFacets(BaseModel):
    important: int = Field(default=0, ge=0)
    hot: int = Field(default=0, ge=0)
    other: int = Field(default=0, ge=0)
    by_type: list[EntityTypeFacet] = Field(default_factory=list)


class EntityRankingContext(BaseModel):
    version: Literal["importance_recent_v1"] = "importance_recent_v1"
    status: Literal["ready", "partial", "unavailable"] = "unavailable"
    as_of_chapter: int | None = Field(default=None, ge=1)
    covered_chapters: int = Field(default=0, ge=0)
    total_chapters: int = Field(default=0, ge=0)
    half_life_chapters: int = 6
    importance_weight: float = 0.65
    heat_weight: float = 0.35


class CoreEntityResponse(BaseModel):
    """核心实体响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    content_json: dict | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    embedding_text: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    ranking: EntityRankingResponse | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @model_validator(mode="after")
    def derive_author_state(self) -> CoreEntityResponse:
        from modules.world.asset_state import project_entity_state

        projection = project_entity_state(
            status=self.status,
            content_json=self.content_json,
            created_by=self.created_by,
        )
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        if self.suggested_action is None:
            self.suggested_action = projection["suggested_action"]
        return self


class CoreEntityListResponse(BaseModel):
    """核心实体列表响应"""

    items: list[CoreEntityResponse]
    total: int
    facets: EntityRankingFacets | None = None
    ranking_context: EntityRankingContext | None = None


class EntityTypeOption(BaseModel):
    value: str
    label: str
    kind: Literal["system", "custom"]


class EntityTypeCatalogResponse(BaseModel):
    items: list[EntityTypeOption]


class EntityPromoteRequest(BaseModel):
    """采用兼容 draft/candidate 实体的请求。

    可选编辑字段与采用在同一事务中完成，供作者在采用前微调待处理对象。
    """

    approved_by: str | None = Field(
        default="manual",
        max_length=64,
        description="确认者标识",
    )
    entity_type: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=5000)

    @field_validator("entity_type")
    @classmethod
    def normalize_optional_entity_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_author_entity_type(value)


class EntityPromoteResponse(BaseModel):
    """实体提升响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    entity_id: str
    status: str
    approved_by: str | None = None

    @field_validator("entity_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# Auto-Ingest Batch Schema
# ============================================================


class AutoIngestBatchItem(BaseModel):
    """自动入库批次内的实体概要"""

    id: str
    name: str
    entity_type: str


class AutoIngestBatchResponse(BaseModel):
    """自动入库批次分组响应"""

    batch_id: str
    ingested_at: str = ""
    entity_count: int = 0
    entities: list[AutoIngestBatchItem] = []


# ============================================================
# Event Schema
# ============================================================


class EventCreate(BaseModel):
    """创建事件请求"""

    entity_id: str = Field(
        ...,
        description="事件实体 ID（CoreEntity）",
    )
    source_chapter_id: str = Field(
        ...,
        description="来源章节 ID",
    )
    location_entity_id: str = Field(
        ...,
        description="事件发生地实体 ID",
    )
    timeline_order: int = Field(
        ...,
        ge=0,
        description="时间线顺序",
    )
    occurrence_time_label: str | None = Field(
        None,
        max_length=100,
        description="发生时间标签",
    )


class EventUpdate(BaseModel):
    """更新事件请求（所有字段可选）"""

    source_chapter_id: Annotated[str | None, Field(None)]
    location_entity_id: Annotated[str | None, Field(None)]
    timeline_order: Annotated[int | None, Field(None, ge=0)]
    occurrence_time_label: Annotated[str | None, Field(None, max_length=100)]


class EventResponse(BaseModel):
    """事件响应"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    novel_id: str
    source_chapter_id: str
    location_entity_id: str
    timeline_order: int
    occurrence_time_label: str | None = None

    @field_validator(
        "entity_id",
        "novel_id",
        "source_chapter_id",
        "location_entity_id",
        mode="before",
    )
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class EventListResponse(BaseModel):
    """事件列表响应"""

    items: list[EventResponse]
    total: int


# ============================================================
# EntityRelation Schema
# ============================================================


class EntityRelationCreate(BaseModel):
    """创建关系请求"""

    source_id: str = Field(
        ...,
        description="源实体 ID",
    )
    target_id: str = Field(
        ...,
        description="目标实体 ID",
    )
    relation_type: str = Field(
        ...,
        max_length=64,
        description="关系类型（自由字符串）",
    )
    description: str | None = Field(
        None,
        description="关系描述",
    )
    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="关系强度 0.0~1.0",
    )
    source_chapter_id: str | None = Field(
        None,
        description="来源章节 ID",
    )
    caused_by_event_id: str | None = Field(
        None,
        description="导致此关系的事件 ID",
    )
    quote: str | None = Field(
        None,
        description="原文依据",
    )
    status: str = Field(
        default="canonical",
        max_length=16,
        description="状态",
    )
    review_meta: dict[str, Any] | None = Field(
        default=None,
        description="来源与人工复核审计元数据",
    )


class EntityRelationUpdate(BaseModel):
    """更新关系请求（所有字段可选）"""

    relation_type: Annotated[str | None, Field(None, max_length=64)]
    description: Annotated[str | None, Field(None)]
    strength: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    status: Annotated[str | None, Field(None, max_length=16)]


class EntityRelationReviewEditRequest(BaseModel):
    """编辑待复核关系并可同步确认。"""

    source_id: Annotated[str | None, Field(None)] = None
    target_id: Annotated[str | None, Field(None)] = None
    relation_type: Annotated[str | None, Field(None, min_length=1, max_length=64)] = None
    description: str | None = None
    strength: Annotated[float | None, Field(None, ge=0.0, le=1.0)] = None
    confirm_review: bool = True

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("relation_type cannot be blank")
        return normalized


class EntityRelationResponse(BaseModel):
    """关系响应"""

    # ``EntityRelation`` already exposes an ORM relationship named ``source``.
    # Read the author-facing provenance from a non-colliding validation alias;
    # the public serialized field remains ``source``.
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    source_id: str
    source_name: str | None = None
    target_id: str
    target_name: str | None = None
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    source_chapter_id: str | None = None
    caused_by_event_id: str | None = None
    quote: str | None = None
    review_meta: dict | None = None
    status: str = "canonical"
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = Field(default=None, validation_alias="author_source")
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "source_id",
        "target_id",
        "source_chapter_id",
        "caused_by_event_id",
        mode="before",
    )
    @classmethod
    def coerce_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)

    @model_validator(mode="after")
    def derive_author_state(self) -> EntityRelationResponse:
        from modules.world.asset_state import project_relation_state

        projection = project_relation_state(
            status=self.status,
            review_meta=self.review_meta,
        )
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        if self.suggested_action is None:
            self.suggested_action = projection["suggested_action"]
        return self


class EntityRelationListResponse(BaseModel):
    """关系列表响应"""

    items: list[EntityRelationResponse]
    total: int


class ReviewTypeCatalogItem(BaseModel):
    value: str
    label: str
    category: str
    synonyms: list[str] = Field(default_factory=list)


class ReviewTypeCatalogResponse(BaseModel):
    version: int = 1
    custom_allowed: bool = True
    relation_types: list[ReviewTypeCatalogItem] = Field(default_factory=list)
    alias_types: list[ReviewTypeCatalogItem] = Field(default_factory=list)


class EntityRelationReviewMember(EntityRelationResponse):
    suggested_relation_type: str | None = None
    type_kind: Literal["recommended", "custom"] = "custom"
    evidence_summary: dict[str, Any] = Field(default_factory=dict)


class EntityRelationReviewGroup(BaseModel):
    group_id: str
    source_id: str
    source_name: str | None = None
    target_id: str
    target_name: str | None = None
    member_count: int
    type_variants: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    scene_indices: list[int] = Field(default_factory=list)
    source_chapter_indices: list[int] = Field(default_factory=list)
    members: list[EntityRelationReviewMember] = Field(default_factory=list)
    canonical_relations: list[EntityRelationResponse] = Field(default_factory=list)
    reverse_candidate_count: int = 0
    reverse_type_variants: list[str] = Field(default_factory=list)
    reverse_canonical_relations: list[EntityRelationResponse] = Field(
        default_factory=list
    )
    execution_fingerprint: str = Field(..., min_length=64, max_length=64)


class EntityRelationReviewGroupListResponse(BaseModel):
    groups: list[EntityRelationReviewGroup] = Field(default_factory=list)
    group_total: int = 0
    item_total: int = 0
    skip: int = 0
    limit: int = 20


class EntityRelationReviewBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_decision_id: str = Field(..., min_length=1, max_length=64)
    action: Literal["accept", "merge", "ignore"]
    group_id: str = Field(..., min_length=1, max_length=80)
    member_relation_ids: list[str] = Field(..., min_length=1, max_length=50)
    primary_relation_id: str | None = None
    expected_execution_fingerprint: str = Field(..., min_length=64, max_length=64)
    source_id: str | None = None
    target_id: str | None = None
    relation_type: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = None
    strength: float | None = Field(None, ge=0.0, le=1.0)

    @field_validator("relation_type")
    @classmethod
    def normalize_relation_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("relation_type cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_decision(self) -> EntityRelationReviewBatchDecision:
        member_ids = list(dict.fromkeys(self.member_relation_ids))
        if len(member_ids) != len(self.member_relation_ids):
            raise ValueError("member_relation_ids must be unique")
        if self.action == "accept" and len(member_ids) != 1:
            raise ValueError("accept requires exactly one relation")
        if self.action == "merge" and len(member_ids) < 2:
            raise ValueError("merge requires at least two relations")
        if self.action in {"accept", "merge"}:
            if self.primary_relation_id not in member_ids:
                raise ValueError("primary_relation_id must be selected")
            if not self.source_id or not self.target_id or not self.relation_type:
                raise ValueError("accepted relation fields are required")
        return self


class EntityRelationReviewBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False
    decisions: list[EntityRelationReviewBatchDecision] = Field(
        ..., min_length=1, max_length=20
    )

    @model_validator(mode="after")
    def validate_batch(self) -> EntityRelationReviewBatchRequest:
        if not self.confirmed:
            raise ValueError("confirmed=true is required")
        decision_ids = [item.client_decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("client_decision_id must be unique")
        relation_ids = [
            relation_id
            for decision in self.decisions
            for relation_id in decision.member_relation_ids
        ]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("a relation may only appear in one batch decision")
        if len(relation_ids) > 50:
            raise ValueError("a batch may reference at most 50 relations")
        return self


class ReviewBatchItemResult(BaseModel):
    client_decision_id: str
    status: Literal["success", "stale", "failed"]
    action: str
    affected_ids: list[str] = Field(default_factory=list)
    canonical_relation_id: str | None = None
    archived_relation_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None


class ReviewBatchResponse(BaseModel):
    requested_count: int
    succeeded_count: int
    stale_count: int
    failed_count: int
    results: list[ReviewBatchItemResult] = Field(default_factory=list)


# ============================================================
# EntityRevision Schema
# ============================================================


class RevisionListResponse(BaseModel):
    """版本列表响应"""

    items: list[dict[str, Any]]
    total: int


class RollbackRequest(BaseModel):
    """回滚请求"""

    target_revision_id: str = Field(
        ...,
        description="目标版本 ID",
    )


class EntityRollbackRequest(BaseModel):
    """实体按 Scene 索引回滚请求"""

    target_scene_index: int = Field(
        ...,
        ge=0,
        description="目标 Scene 索引",
    )


class EntityMergeRequest(BaseModel):
    """实体合并请求"""

    target_entity_id: str = Field(
        ...,
        description="合并目标实体 ID",
    )


class EntityMergeResponse(BaseModel):
    """实体合并响应"""

    target_entity_id: str
    candidate_entity_id: str | None = None
    affected_ids: list[str] = Field(default_factory=list)
    merged_ids: list[str] = Field(default_factory=list)


class EntityFusionSuggestionRequest(BaseModel):
    """请求生成世界对象 LLM 融合/合并建议。"""

    novel_id: str
    entity_type: str | None = Field(None, max_length=64)
    status: str | None = Field(None, max_length=32)
    limit: int = Field(default=200, ge=2, le=1000)
    max_suggestions: int = Field(default=50, ge=1, le=200)
    operation_id: uuid.UUID | None = None


class EntityFusionSuggestionResponse(BaseModel):
    """世界对象融合建议任务响应。"""

    task_id: str
    status: str = "pending"


class EntityFusionApplyItem(BaseModel):
    """一条用户确认要应用的融合建议。"""

    action: str = Field(..., pattern="^(merge|alias_only)$")
    source_entity_id: str
    target_entity_id: str
    alias: str | None = Field(None, max_length=255)
    allow_canonical_merge: bool = False
    allow_canonical_alias: bool = False


class EntityFusionApplyRequest(BaseModel):
    """应用已确认的融合建议。"""

    novel_id: str
    confirmed: bool = False
    suggestions: list[EntityFusionApplyItem] = Field(..., min_length=1)


class EntityFusionApplyResponse(BaseModel):
    """应用融合建议的结果。"""

    applied: int = 0
    skipped: int = 0
    results: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EntityRollbackResponse(BaseModel):
    """实体回滚响应"""

    entity_id: str
    target_scene_index: int | None
    restored_fields: list[str]
    warnings: list[str]


class EntityRevisionListResponse(BaseModel):
    """实体版本列表响应"""

    items: list[dict[str, Any]]
    total: int


class TextArchiveSeedRequest(BaseModel):
    """E2E 测试专用：写入 TextArchive 归档请求"""

    novel_id: str
    field_name: str = "summary"
    text_content: str
    scene_index: int = 0


class TextArchiveSeedResponse(BaseModel):
    """E2E 测试专用：写入 TextArchive 归档响应"""

    status: str = "ok"
    entity_id: str
    field_name: str
    archive_id: str


# ============================================================
# Character Schema（从 character 模块迁入）
# ============================================================


class CharacterCreate(BaseModel):
    """创建人物请求。novel_id 由 service 注入 (per ADR-0002),
    Create schema 不再要求, 但保留字段以兼容外部测试 fixture 显式传值。"""

    novel_id: str | None = Field(
        default=None,
        description="小说项目 ID (由 service 注入, 通常不传)",
    )
    entity_id: str = Field(
        ...,
        description="关联的核心实体 ID",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="人物名称",
    )
    aliases: list[dict] = Field(
        default_factory=list,
        description="别名列表 JSONB（[{alias: str, type: str}]）",
    )
    role: str | None = Field(
        None,
        max_length=64,
        description="角色定位",
    )
    appearance: str | None = Field(
        None,
        description="外貌描述",
    )
    personality: str | None = Field(
        None,
        description="性格描述",
    )
    desire: str | None = Field(
        None,
        description="渴望/目标",
    )
    fear: str | None = Field(
        None,
        description="恐惧/软肋",
    )
    secret: str | None = Field(
        None,
        description="秘密（作者视角）",
    )
    weakness: str | None = Field(
        None,
        description="弱点",
    )
    current_goal: str | None = Field(
        None,
        description="当前短期目标",
    )
    current_state: str | None = Field(
        None,
        description="当前状态摘要",
    )
    current_emotion: str | None = Field(
        None,
        max_length=64,
        description="当前情绪",
    )
    stance: str | None = Field(
        None,
        description="人物立场/态度",
    )
    voice_style: str | None = Field(
        None,
        description="语言风格描述",
    )
    behavior_rules: list[dict] = Field(
        default_factory=list,
        max_length=50,
        description="行为规则列表 JSONB（最多 50 条）",
    )
    relationship_summary: str | None = Field(
        None,
        description="人物关系摘要",
    )
    meta: dict = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )


class CharacterUpdate(BaseModel):
    """更新人物请求（所有字段可选）"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    aliases: Annotated[list[dict] | None, Field(None)]
    role: Annotated[str | None, Field(None, max_length=64)]
    appearance: Annotated[str | None, Field(None)]
    personality: Annotated[str | None, Field(None)]
    desire: Annotated[str | None, Field(None)]
    fear: Annotated[str | None, Field(None)]
    secret: Annotated[str | None, Field(None)]
    weakness: Annotated[str | None, Field(None)]
    current_goal: Annotated[str | None, Field(None)]
    current_state: Annotated[str | None, Field(None)]
    current_emotion: Annotated[str | None, Field(None, max_length=64)]
    stance: Annotated[str | None, Field(None)]
    voice_style: Annotated[str | None, Field(None)]
    behavior_rules: Annotated[list[dict] | None, Field(None)]
    relationship_summary: Annotated[str | None, Field(None)]
    meta: Annotated[dict | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class CharacterResponse(BaseModel):
    """人物响应 — 从 ORM 转换"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    entity_id: str
    novel_id: str
    name: str

    @property
    def id(self) -> str:
        """向后兼容：旧代码使用 .id 访问人物 ID"""
        return self.entity_id

    aliases: list[dict] = []
    role: str | None = None
    appearance: str | None = None
    personality: str | None = None
    desire: str | None = None
    fear: str | None = None
    secret: str | None = None
    weakness: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = []
    relationship_summary: str | None = None
    meta: dict = {}
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("entity_id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str:
        return _uuid_validator(v)


class CharacterListResponse(BaseModel):
    """人物列表响应"""

    items: list[CharacterResponse]
    total: int


def _require_misconception_for_false_belief_or_misunderstood(
    model: BaseModel,
) -> BaseModel:
    """shared model_validator: false_belief/misunderstood 必须提供 misconception。"""
    if getattr(model, "knowledge_level") in {
        "false_belief",
        "misunderstood",
    } and not getattr(model, "misconception"):
        raise ValueError(
            "false_belief/misunderstood knowledge must provide misconception",
        )
    return model


class CharacterKnowledgeCreate(BaseModel):
    """创建人物知识记录请求。novel_id 由 service 注入。"""

    novel_id: str | None = Field(
        default=None,
        description="小说项目 ID (由 service 注入, 通常不传)",
    )
    character_id: str = Field(..., description="人物 ID")
    target_type: str = Field(
        ...,
        max_length=64,
        description="目标类型（entity/character/event/location 等）",
    )
    target_id: str = Field(..., description="目标对象 ID")
    knowledge_level: str = Field(
        ...,
        max_length=32,
        description="了解程度（unknown/rumor/partial/full/false_belief/restricted/misunderstood）",
    )
    known_content: str | None = Field(None, description="角色已知的内容")
    misconception: str | None = Field(
        None,
        description="角色的误解内容（false_belief 或 misunderstood 时使用）",
    )
    source_chapter_index: int | None = Field(None, ge=0, description="信息来源章节")
    is_public_baseline: bool = Field(
        default=False,
        description="无来源章节时，是否为人物从开场就已知的公开基线",
    )
    source_memory_id: str | None = Field(None, description="关联的 memory 记录 ID")
    status: str = Field(default="canonical", max_length=32, description="状态")

    require_misconception_for_false_belief_or_misunderstood = model_validator(
        mode="after",
    )(_require_misconception_for_false_belief_or_misunderstood)


class CharacterKnowledgeUpdate(BaseModel):
    """更新人物知识记录请求（所有字段可选）"""

    knowledge_level: Annotated[str | None, Field(None, max_length=32)]
    known_content: Annotated[str | None, Field(None)]
    misconception: Annotated[str | None, Field(None)]
    source_chapter_index: Annotated[int | None, Field(None, ge=0)]
    is_public_baseline: bool | None = None
    source_memory_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]

    require_misconception_for_false_belief_or_misunderstood = model_validator(
        mode="after",
    )(_require_misconception_for_false_belief_or_misunderstood)


class CharacterKnowledgeResponse(BaseModel):
    """人物知识响应 — 从 ORM 转换"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    character_id: str
    target_type: str
    target_id: str
    target_name: str | None = None
    target_entity_type: str | None = None
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None
    source_chapter_index: int | None = None
    is_public_baseline: bool = False
    source_memory_id: str | None = None
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "character_id",
        "target_id",
        "source_memory_id",
        mode="before",
    )
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)


class CharacterKnowledgeListResponse(BaseModel):
    """人物知识列表响应"""

    items: list[CharacterKnowledgeResponse]
    total: int


# ============================================================
# Facade 输出 Schema（供其他模块读取/使用）
# ============================================================


class WorldEntityContext(BaseModel):
    """世界对象上下文 — 供其他模块读取的简化对象信息"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    aliases: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)

    @field_validator("entity_id", mode="before")
    @classmethod
    def coerce_entity_id(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldContextBundle(BaseModel):
    """世界上下文组合包 — 供 Context Compiler 或其他模块使用"""

    novel_id: str
    entities: list[WorldEntityContext] = Field(default_factory=list)
    total_count: int = 0
    reveal_mode: str = "author_safe"


class CharacterContextItem(BaseModel):
    """人物上下文中单个人物的信息"""

    model_config = ConfigDict(from_attributes=True)

    character_id: str
    name: str
    role: str | None = None
    appearance: str | None = None
    personality: str | None = None
    desire: str | None = None
    fear: str | None = None
    secret: str | None = None
    weakness: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = []
    relationship_summary: str | None = None
    meta: dict = {}


class CharacterKnowledgeContext(BaseModel):
    """人物知识上下文 — 单条知识"""

    model_config = ConfigDict(from_attributes=True)

    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None


class CharacterContextBundle(BaseModel):
    """人物上下文聚合 — 返回给其他模块的完整人物信息包"""

    characters: list[CharacterContextItem] = Field(
        ...,
        description="人物列表",
    )
    total: int = Field(..., description="总人物数")
    reveal_mode: str = Field(
        default="author_safe",
        description="使用的揭示模式",
    )


class FilterContextRequest(BaseModel):
    """按人物知识过滤上下文的请求"""

    context_items: list[dict] = Field(
        ...,
        description="待过滤的上下文项列表",
    )


class FilterContextResponse(BaseModel):
    """按人物知识过滤上下文的结果"""

    filtered_items: list[dict] = Field(..., description="过滤后的上下文项列表")
    removed_count: int = Field(..., description="被移除的项数")
    replaced_count: int = Field(..., description="被替换为误解的项数")


class EventContext(BaseModel):
    """事件上下文 — 供其他模块使用"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    entity_name: str
    timeline_order: int
    occurrence_time_label: str | None = None
    location_name: str | None = None


class EventsContextBundle(BaseModel):
    """事件上下文组合包"""

    novel_id: str
    events: list[EventContext] = Field(default_factory=list)
    total_count: int = 0


# ============================================================
# 向后兼容 Schema（从旧 schema 迁出）
# ============================================================


class DuplicateSuggestionResult(BaseModel):
    """去重建议结果 — 向后兼容"""

    candidate_id: str = ""
    candidate_name: str = ""
    existing_entity_id: str = ""
    existing_entity_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""
    action: str = ""


# ============================================================
# 向后兼容别名（供其他模块引用）
# ============================================================

WorldEntityResponse = CoreEntityResponse
WorldEntityListResponse = CoreEntityListResponse
WorldEntityCreate = CoreEntityCreate
WorldEntityUpdate = CoreEntityUpdate
WorldEntityContext = WorldEntityContext
WorldContextBundle = WorldContextBundle


class EntityAliasCreate(BaseModel):
    """创建 core_entities.content_json.aliases 中的别名。"""

    entity_id: str = Field(..., description="所属核心实体 ID")
    alias: str = Field(..., min_length=1, max_length=255, description="别名文本")
    alias_type: str = Field(default="name", max_length=20, description="别名类型")
    source_chapter_index: int | None = Field(None, ge=0, description="首次出现的章节索引")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="确认置信度")
    status: str = Field(default="confirmed", max_length=32, description="状态")


class EntityAliasUpdate(BaseModel):
    """更新 core_entities.content_json.aliases 中单个别名的复核元数据。"""

    status: Annotated[str | None, Field(None, max_length=32)]
    needs_review: bool | None = None
    reviewed_at: Annotated[str | None, Field(None, max_length=64)]
    reviewed_by: Annotated[str | None, Field(None, max_length=64)]
    reviewed_from: Annotated[str | None, Field(None, max_length=64)]


class EntityAliasEditRequest(BaseModel):
    """编辑或移动 core_entities.content_json.aliases 中单个别名。"""

    target_entity_id: Annotated[str | None, Field(None)] = None
    alias: Annotated[str | None, Field(None, min_length=1, max_length=255)] = None
    alias_type: Annotated[str | None, Field(None, max_length=20)] = None
    confirm_review: bool = True


class EntityAliasReviewItem(BaseModel):
    entity_id: str
    entity_name: str | None = None
    alias: str
    alias_type: str
    status: str | None = None
    source: str | None = None
    workflow_id: str | None = None
    scene_id: str | None = None
    scene_index: int | None = None
    source_chapter_index: int | None = None
    confidence: float | None = None
    needs_review: bool | None = None
    quote: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    suggested_alias_type: str | None = None
    type_kind: Literal["recommended", "custom"] = "custom"
    display_state: Literal["active", "review", "archived"] | None = None
    managed_by_suggestion: bool = False
    suggestion_id: str | None = None
    execution_fingerprint: str = Field(..., min_length=64, max_length=64)


class EntityAliasReviewGroup(BaseModel):
    group_id: str
    entity_id: str
    entity_name: str | None = None
    member_count: int
    members: list[EntityAliasReviewItem] = Field(default_factory=list)


class EntityAliasReviewGroupListResponse(BaseModel):
    groups: list[EntityAliasReviewGroup] = Field(default_factory=list)
    group_total: int = 0
    item_total: int = 0
    skip: int = 0
    limit: int = 20


class EntityAliasReviewBatchDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_decision_id: str = Field(..., min_length=1, max_length=64)
    action: Literal["accept", "ignore"]
    entity_id: str
    original_alias: str = Field(..., min_length=1, max_length=255)
    expected_execution_fingerprint: str = Field(..., min_length=64, max_length=64)
    target_entity_id: str | None = None
    alias: str | None = Field(None, min_length=1, max_length=255)
    alias_type: str | None = Field(None, min_length=1, max_length=20)

    @field_validator("alias_type")
    @classmethod
    def normalize_alias_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("alias_type cannot be blank")
        return normalized


class EntityAliasReviewBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool = False
    decisions: list[EntityAliasReviewBatchDecision] = Field(
        ..., min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def validate_batch(self) -> EntityAliasReviewBatchRequest:
        if not self.confirmed:
            raise ValueError("confirmed=true is required")
        decision_ids = [item.client_decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("client_decision_id must be unique")
        alias_keys = [
            (item.entity_id, item.original_alias.casefold()) for item in self.decisions
        ]
        if len(alias_keys) != len(set(alias_keys)):
            raise ValueError("an alias may only appear once in a batch")
        return self


class EntityResolveAsAliasRequest(BaseModel):
    """将候选实体确认为已有对象的别名。"""

    target_entity_id: str = Field(..., description="目标核心实体 ID")
    alias: str = Field(..., min_length=1, max_length=255, description="别名文本")
    alias_type: str = Field(default="alias", max_length=20, description="别名类型")


# ============================================================
# Worldbuilding Workspace v1
# ============================================================


class TargetRefSchema(BaseModel):
    """Worldbuilding TargetRef wire shape."""

    target_type: str = Field(..., min_length=1, max_length=64)
    target_id: str = Field(..., min_length=1, max_length=255)
    target_path: str = Field(default="", max_length=512)


class WorldProfileUpsertRequest(BaseModel):
    """Create or update a strong/generic worldbuilding profile."""

    status: str = Field(default="draft", max_length=32)
    source: str = Field(default="manual", max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs_json: list[dict[str, Any]] = Field(default_factory=list)
    extra_json: dict[str, Any] = Field(default_factory=dict)
    data_json: dict[str, Any] | None = Field(default=None)

    origin_summary: str | None = None
    physiology_summary: str | None = None
    lifespan: str | None = None
    abilities_json: list[dict[str, Any]] | None = None
    weaknesses_json: list[dict[str, Any]] | None = None
    culture_summary: str | None = None
    language_summary: str | None = None
    public_baseline: bool | None = None

    ideology_summary: str | None = None
    leader_entity_ids_json: list[str] | None = None
    member_rules: str | None = None
    territory_refs_json: list[dict[str, Any]] | None = None
    resources_json: list[dict[str, Any]] | None = None

    map_refs_json: list[dict[str, Any]] | None = None
    climate: str | None = None
    population_summary: str | None = None
    hazards_json: list[dict[str, Any]] | None = None
    controlling_faction_ids_json: list[str] | None = None

    rule_domain: str | None = None
    principle_summary: str | None = None
    constraints_json: list[dict[str, Any]] | None = None
    exceptions_json: list[dict[str, Any]] | None = None
    consequences_json: list[dict[str, Any]] | None = None

    item_class: str | None = None
    powers_json: list[dict[str, Any]] | None = None
    limitations_json: list[dict[str, Any]] | None = None
    owner_entity_ids_json: list[str] | None = None

    truth_summary: str | None = None
    holder_entity_ids_json: list[str] | None = None
    risk_level: str | None = None
    reveal_status: str | None = None
    linked_target_refs_json: list[dict[str, Any]] | None = None


class WorldProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    novel_id: str
    entity_type: str
    profile_kind: str
    status: str
    source: str = "manual"
    confidence: float | None = None
    evidence_refs_json: list = Field(default_factory=list)
    extra_json: dict = Field(default_factory=dict)
    data_json: dict | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorldProfileListResponse(BaseModel):
    items: list[WorldProfileResponse]
    total: int


class WorldProfileMigrateResponse(BaseModel):
    entity_id: str
    migrated: bool
    profile: WorldProfileResponse


class WorldBibleSection(BaseModel):
    section_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    section_type: Literal["markdown", "checklist", "asset_collection"] = "markdown"
    title: str = Field(..., min_length=1, max_length=120)
    body_markdown: str = Field(default="", max_length=30000)
    sort_order: int = Field(default=0, ge=-100000, le=100000)
    linked_asset_ref_hashes: list[str] = Field(default_factory=list, max_length=100)
    projection_policy: Literal["eligible", "excluded"] = "eligible"
    sensitivity_hint: Literal[
        "author_only",
        "author_safe",
        "public_baseline",
    ] = "author_safe"

    @field_validator("linked_asset_ref_hashes")
    @classmethod
    def validate_ref_hashes(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            current = str(value).strip().removeprefix("sha256:")
            if len(current) != 64 or any(ch not in "0123456789abcdef" for ch in current):
                raise ValueError(
                    "linked asset ref hashes must be lowercase sha256 values"
                )
            if current not in normalized:
                normalized.append(current)
        return normalized


def _validate_world_bible_sections(
    sections: list[WorldBibleSection],
) -> list[WorldBibleSection]:
    ids = [section.section_id for section in sections]
    if len(ids) != len(set(ids)):
        raise ValueError("World Bible section_id must be unique within a page")
    return sorted(sections, key=lambda item: (item.sort_order, item.section_id))


_FORBIDDEN_PAGE_TEMPLATE_KEYS = frozenset(
    {
        "api_key",
        "depth",
        "macro",
        "outlet",
        "prompt",
        "provider",
        "role",
        "system",
        "tool",
        "tools",
    }
)


def _reject_executable_template_values(value: Any, *, path: str = "template") -> Any:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_PAGE_TEMPLATE_KEYS:
                raise ValueError(f"{path}.{key} is not allowed in a page template")
            _reject_executable_template_values(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_executable_template_values(child, path=f"{path}[{index}]")
    return value


class WorldBiblePageCreate(BaseModel):
    novel_id: str
    page_type: str = Field(default="custom", max_length=64)
    page_key: str | None = Field(default=None, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)
    status: str = Field(default="draft", max_length=32)
    page_meta_json: dict[str, Any] = Field(default_factory=dict)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] = Field(default_factory=list, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] = Field(default_factory=list)
    activation_defaults_json: dict[str, Any] = Field(default_factory=dict)
    template_key: str | None = Field(default=None, max_length=128)
    sort_order: int = 0
    created_by: str | None = Field(default=None, max_length=64)

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection],
    ) -> list[WorldBibleSection]:
        return _validate_world_bible_sections(value)


class WorldBiblePageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, max_length=32)
    page_meta_json: dict[str, Any] | None = None
    free_text: str | None = None
    sections_json: list[WorldBibleSection] | None = Field(default=None, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] | None = None
    activation_defaults_json: dict[str, Any] | None = None
    template_key: str | None = Field(default=None, max_length=128)
    sort_order: int | None = None
    updated_by: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldBiblePageUpdate:
        for field_name in {
            "title",
            "status",
            "page_meta_json",
            "linked_asset_refs_json",
            "activation_defaults_json",
            "sections_json",
            "sort_order",
        }:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection] | None,
    ) -> list[WorldBibleSection] | None:
        return None if value is None else _validate_world_bible_sections(value)


class WorldBibleValidationReceipt(BaseModel):
    scope: Literal["targeted", "domain_full"]
    scope_label: str
    source_version: int = Field(..., ge=1)
    checked: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    impact_scope_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime


class WorldBiblePageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    page_type: str
    page_key: str
    title: str
    status: str
    page_meta_json: dict = Field(default_factory=dict)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] = Field(default_factory=list)
    linked_asset_refs_json: list = Field(default_factory=list)
    activation_defaults_json: dict = Field(default_factory=dict)
    template_key: str | None = None
    template_version: int = 1
    version_number: int = 1
    sort_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    validation_receipt: WorldBibleValidationReceipt | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_page_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldBiblePageListResponse(BaseModel):
    items: list[WorldBiblePageResponse]
    total: int


class WorldKnowledgeGraphNode(BaseModel):
    id: str
    kind: Literal["world_bible_page", "core_entity"]
    label: str
    status: str


class WorldKnowledgeGraphEdge(BaseModel):
    id: str
    kind: Literal["page_reference", "page_entity_reference", "entity_relation"]
    source_id: str
    target_id: str
    status: str = "canonical"
    authority: str | None = None
    source_ref: dict[str, str] | None = None
    revision: int | None = None
    source_hash: str | None = None
    provenance: dict[str, Any] | None = None
    via_relation_id: str | None = None


class WorldKnowledgeGraphResponse(BaseModel):
    nodes: list[WorldKnowledgeGraphNode] = Field(default_factory=list)
    edges: list[WorldKnowledgeGraphEdge] = Field(default_factory=list)
    truncated: bool = False
    truncation_reasons: list[str] = Field(default_factory=list)
    omitted_counts: dict[str, int] = Field(default_factory=dict)
    source_manifest: list[dict[str, str]] = Field(default_factory=list)
    source_hash: str
    dependency_coverage: bool = False
    note: str = "Relationships are associations, not change-impact dependencies."


class WorldBibleCategoryCreate(BaseModel):
    novel_id: str
    category_key: str = Field(
        ...,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    color: str = Field(default="#64748B", pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str = Field(default="", max_length=16)
    sort_order: int = 100
    default_template_key: str | None = Field(default=None, max_length=128)


class WorldBibleCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    icon: str | None = Field(default=None, max_length=16)
    sort_order: int | None = None
    status: Literal["active", "archived"] | None = None
    default_template_key: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldBibleCategoryUpdate:
        for field_name in {"name", "color", "icon", "sort_order", "status"}:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class WorldBibleCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    category_key: str
    name: str
    description: str | None = None
    color: str
    icon: str
    sort_order: int
    status: str
    builtin: bool = False
    default_template_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_category_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldBibleCategoryListResponse(BaseModel):
    items: list[WorldBibleCategoryResponse]


class WorldBiblePageDraftCreate(BaseModel):
    novel_id: str
    page_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    page_type: str | None = Field(default=None, min_length=1, max_length=64)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] | None = Field(default=None, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] | None = None
    sort_order: int | None = None
    template_key: str | None = Field(default=None, max_length=128)
    template_version: int | None = Field(default=None, ge=1)
    created_by: str | None = Field(default=None, max_length=64)

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection] | None,
    ) -> list[WorldBibleSection] | None:
        return None if value is None else _validate_world_bible_sections(value)


class WorldBiblePageDraftUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    page_type: str | None = Field(default=None, min_length=1, max_length=64)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] | None = Field(default=None, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] | None = None
    sort_order: int | None = None
    template_key: str | None = Field(default=None, max_length=128)
    template_version: int | None = Field(default=None, ge=1)
    updated_by: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldBiblePageDraftUpdate:
        for field_name in {
            "title",
            "page_type",
            "linked_asset_refs_json",
            "sections_json",
            "sort_order",
            "template_version",
        }:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection] | None,
    ) -> list[WorldBibleSection] | None:
        return None if value is None else _validate_world_bible_sections(value)


class WorldBiblePageDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    page_id: str | None = None
    base_version_number: int | None = None
    title: str
    page_type: str
    free_text: str | None = None
    sections_json: list[WorldBibleSection] = Field(default_factory=list)
    linked_asset_refs_json: list = Field(default_factory=list)
    sort_order: int = 0
    template_key: str | None = None
    template_version: int = 1
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_draft_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @field_validator("page_id", mode="before")
    @classmethod
    def coerce_optional_page_uuid(cls, v: object) -> str | None:
        return _optional_uuid_validator(v)


class WorldBiblePageDraftListResponse(BaseModel):
    items: list[WorldBiblePageDraftResponse]
    total: int


class WorldBibleImpactPathNode(BaseModel):
    page_id: str
    title: str
    version_number: int = Field(..., ge=1)
    section_titles: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("page_id", mode="before")
    @classmethod
    def coerce_path_page_uuid(cls, value: object) -> str:
        return _uuid_validator(value)


class WorldBibleImpactedPage(BaseModel):
    page_id: str
    title: str
    page_type: str
    version_number: int = Field(..., ge=1)
    distance: int = Field(..., ge=1)
    path: list[WorldBibleImpactPathNode] = Field(..., min_length=2, max_length=256)

    @field_validator("page_id", mode="before")
    @classmethod
    def coerce_impacted_page_uuid(cls, value: object) -> str:
        return _uuid_validator(value)


class WorldBibleImpactOmission(BaseModel):
    reason: Literal[
        "invalid_page_reference",
        "unavailable_page_reference",
        "response_limit",
    ]
    referring_page_id: str | None = None
    referring_page_title: str | None = None
    count: int = Field(default=1, ge=1)

    @field_validator("referring_page_id", mode="before")
    @classmethod
    def coerce_optional_referring_page_uuid(cls, value: object) -> str | None:
        return _optional_uuid_validator(value)


class WorldBiblePublishImpactSource(BaseModel):
    draft_id: str
    page_id: str | None = None
    title: str
    page_version: int | None = Field(default=None, ge=1)
    draft_updated_at: datetime | None = None
    content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @field_validator("draft_id", mode="before")
    @classmethod
    def coerce_impact_draft_uuid(cls, value: object) -> str:
        return _uuid_validator(value)

    @field_validator("page_id", mode="before")
    @classmethod
    def coerce_optional_impact_page_uuid(cls, value: object) -> str | None:
        return _optional_uuid_validator(value)


class WorldBiblePublishImpactResponse(BaseModel):
    source: WorldBiblePublishImpactSource
    added_outgoing_refs: int = Field(default=0, ge=0)
    removed_outgoing_refs: int = Field(default=0, ge=0)
    affected_pages: list[WorldBibleImpactedPage] = Field(
        default_factory=list,
        max_length=200,
    )
    omissions: list[WorldBibleImpactOmission] = Field(default_factory=list)
    automatic_actions: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    complete: bool = True
    impact_scope_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class WorldBiblePageRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    page_id: str
    version_number: int
    snapshot_json: dict = Field(default_factory=dict)
    revision_reason: str
    created_at: datetime | None = None

    @field_validator("id", "novel_id", "page_id", mode="before")
    @classmethod
    def coerce_revision_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldBiblePageTemplateCreate(BaseModel):
    novel_id: str
    template_key: str = Field(
        ...,
        min_length=2,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    category_key_hint: str | None = Field(default=None, max_length=64)
    sections_schema_json: dict[str, Any] = Field(default_factory=dict)
    default_sections_json: list[WorldBibleSection] = Field(
        default_factory=list,
        max_length=64,
    )
    validation_rules_json: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_template(self) -> WorldBiblePageTemplateCreate:
        self.default_sections_json = _validate_world_bible_sections(
            self.default_sections_json
        )
        _reject_executable_template_values(self.sections_schema_json)
        _reject_executable_template_values(self.validation_rules_json)
        return self


class WorldBiblePageTemplateUpdate(BaseModel):
    base_version_number: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    category_key_hint: str | None = Field(default=None, max_length=64)
    sections_schema_json: dict[str, Any] | None = None
    default_sections_json: list[WorldBibleSection] | None = Field(
        default=None,
        max_length=64,
    )
    validation_rules_json: dict[str, Any] | None = None
    status: Literal["active", "archived"] | None = None
    updated_by: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_template(self) -> WorldBiblePageTemplateUpdate:
        for field_name in {
            "name",
            "sections_schema_json",
            "default_sections_json",
            "validation_rules_json",
            "status",
        }:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        if self.default_sections_json is not None:
            self.default_sections_json = _validate_world_bible_sections(
                self.default_sections_json
            )
        if self.sections_schema_json is not None:
            _reject_executable_template_values(self.sections_schema_json)
        if self.validation_rules_json is not None:
            _reject_executable_template_values(self.validation_rules_json)
        return self


class WorldBiblePageTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    template_key: str
    name: str
    description: str | None = None
    category_key_hint: str | None = None
    sections_schema_json: dict = Field(default_factory=dict)
    default_sections_json: list[WorldBibleSection] = Field(default_factory=list)
    validation_rules_json: dict = Field(default_factory=dict)
    version_number: int = 1
    status: str = "active"
    builtin: bool = False
    created_by: str | None = None
    updated_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_template_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldBiblePageTemplateListResponse(BaseModel):
    items: list[WorldBiblePageTemplateResponse]
    total: int


class WorldBiblePageTemplateRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    template_id: str
    version_number: int
    snapshot_json: dict = Field(default_factory=dict)
    content_hash: str
    revision_reason: str
    created_by: str | None = None
    created_at: datetime | None = None

    @field_validator("id", "novel_id", "template_id", mode="before")
    @classmethod
    def coerce_template_revision_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldBibleApplyTemplateRequest(BaseModel):
    template_key: str = Field(..., min_length=1, max_length=128)
    template_version: int | None = Field(default=None, ge=1)
    replace_sections: bool = False
    updated_by: str | None = Field(default=None, max_length=64)


class WorldBiblePageProposalContent(BaseModel):
    """Complete, editable World Bible working-draft content."""

    title: str = Field(..., min_length=1, max_length=255)
    page_type: str = Field(..., min_length=1, max_length=64)
    free_text: str | None = Field(default=None, max_length=30000)
    sections_json: list[WorldBibleSection] = Field(default_factory=list, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] = Field(
        default_factory=list,
        max_length=100,
    )

    @field_validator("sections_json")
    @classmethod
    def validate_sections(
        cls,
        value: list[WorldBibleSection],
    ) -> list[WorldBibleSection]:
        return _validate_world_bible_sections(value)


class WorldGenerationPageBaseline(BaseModel):
    page_id: str
    page_version: int
    draft_id: str | None = None
    draft_updated_at: datetime | None = None
    content_hash: str = Field(..., min_length=64, max_length=64)


class WorldBiblePageDraftSuggestionPayload(BaseModel):
    operation: Literal["replace_existing", "create_new"]
    target_page_id: str | None = None
    baseline: WorldGenerationPageBaseline | None = None
    template_key: str | None = Field(default=None, max_length=128)
    template_version: int | None = Field(default=None, ge=1)
    page: WorldBiblePageProposalContent
    design_rationale: str = Field(default="", max_length=4000)
    review_notes: list[str] = Field(default_factory=list, max_length=20)
    source_refs: list[WorldBibleSourceRef] = Field(default_factory=list)
    decision_state: GeneratedWorldGenerationDecisionState | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> WorldBiblePageDraftSuggestionPayload:
        if self.operation == "replace_existing":
            if not self.target_page_id or self.baseline is None:
                raise ValueError("replace_existing requires target_page_id and baseline")
            if self.target_page_id != self.baseline.page_id:
                raise ValueError("target_page_id must match baseline.page_id")
        elif self.target_page_id is not None:
            raise ValueError("create_new must not include target_page_id")
        return self


class WorldGenerationApplyPageDraftRequest(BaseModel):
    page: WorldBiblePageProposalContent | None = None
    updated_by: str | None = Field(default=None, max_length=64)


class WorldBibleSynopsisClaim(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    source_keys: list[str] = Field(default_factory=list, min_length=1, max_length=40)


class WorldBibleSynopsisSection(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    claims: list[WorldBibleSynopsisClaim] = Field(
        ...,
        min_length=1,
        max_length=40,
    )


class WorldBibleSynopsisStructuredOutput(BaseModel):
    sections: list[WorldBibleSynopsisSection] = Field(
        ...,
        min_length=1,
        max_length=20,
    )
    omitted_reasons: list[str] = Field(default_factory=list, max_length=40)


class WorldBibleSynopsisRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    version_number: int
    status: str
    rendered_text: str
    claims_json: list = Field(default_factory=list)
    source_manifest_json: list = Field(default_factory=list)
    source_hash: str
    token_estimate: int
    coverage_json: dict = Field(default_factory=dict)
    omitted_reasons_json: list = Field(default_factory=list)
    generation_meta_json: dict = Field(default_factory=dict)
    created_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_synopsis_revision_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldBibleSynopsisResponse(BaseModel):
    novel_id: str
    status: str
    stale: bool = True
    pinned: bool = False
    desired_source_hash: str = ""
    active_task_id: str | None = None
    auto_refresh_enabled: bool = False
    authorization: dict = Field(default_factory=dict)
    current_revision: WorldBibleSynopsisRevisionResponse | None = None
    warnings: list[str] = Field(default_factory=list)
    last_error_kind: str | None = None
    last_error_summary: str | None = None


class WorldBibleSynopsisRefreshResponse(BaseModel):
    task_id: str
    status: str
    existing: bool = False
    source_hash: str


class WorldBibleSynopsisAutoRefreshRequest(BaseModel):
    enabled: bool
    changed_by: str | None = Field(default=None, max_length=64)


class WorldBibleSynopsisRevisionListResponse(BaseModel):
    items: list[WorldBibleSynopsisRevisionResponse]
    total: int


class WorldBibleProjectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    page_id: str
    projection_type: str
    source_page_version: int = 0
    source_hash: str = ""
    status: str
    content: str | None = None
    token_estimate: int = 0
    stale: bool = True
    stale_checked_at: datetime | None = None
    error_kind: str | None = None
    error_summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "page_id", mode="before")
    @classmethod
    def coerce_projection_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class ProjectionRefreshResponse(BaseModel):
    task_id: str
    status: str
    existing: bool = False
    projection_type: str


class CreationSuggestionCreate(BaseModel):
    novel_id: str
    source_module: str = Field(default="manual", max_length=64)
    review_group: str = Field(default="manual", max_length=64)
    target_type: str = Field(..., max_length=64)
    action_schema: str = Field(default="v1", max_length=128)
    payload_json: dict[str, Any] = Field(default_factory=dict)
    evidence_refs_json: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: str = Field(default="medium", max_length=32)
    status: str = Field(default="pending", max_length=32)


class WorldCoreCheckpointDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(..., min_length=1, max_length=64)
    text: str = Field(..., min_length=1, max_length=600)
    disposition: Literal["locked", "open", "rejected"]
    rule_key: str | None = Field(default=None, min_length=1, max_length=64)
    source_keys: list[str] = Field(default_factory=list, max_length=16)


class WorldCoreCheckpointPayload(BaseModel):
    """Read-only convergence checkpoint; it can never be adopted."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_core_checkpoint.v1"]
    round_no: int = Field(..., ge=0)
    action: Literal["expand", "connect", "pressure", "consolidate"]
    parent_checkpoint_id: str | None = None
    source_manifest_hash: str = Field(..., min_length=64, max_length=64)
    seeds: list[WorldAdoptionSeed] = Field(default_factory=list, max_length=64)
    decision_state: GeneratedWorldGenerationDecisionState | None = None
    world_core: GeneratedWorldCoreConvergence | None = None
    decisions: list[WorldCoreCheckpointDecision] = Field(
        default_factory=list, max_length=64
    )

    @field_validator("source_manifest_hash")
    @classmethod
    def validate_source_manifest_hash(cls, value: str) -> str:
        return _validate_lower_sha256(value, "source_manifest_hash")


class WorldAdoptionSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal[
        "world_bible_page", "core_entity", "manuscript", "conversation", "external"
    ]
    source_id: str = Field(..., min_length=1, max_length=128)
    source_version: str | None = Field(default=None, max_length=128)
    source_hash: str = Field(..., min_length=64, max_length=64)
    range_start: int | None = Field(default=None, ge=0)
    range_end: int | None = Field(default=None, ge=0)
    scene_id: str | None = None
    workflow_id: str | None = Field(default=None, max_length=128)
    authorization_ref: str | None = Field(default=None, max_length=128)

    @field_validator("source_hash")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        return _validate_lower_sha256(value, "source_hash")

    @model_validator(mode="after")
    def validate_range(self) -> WorldAdoptionSourceRef:
        if (
            self.range_start is not None
            and self.range_end is not None
            and self.range_end < self.range_start
        ):
            raise ValueError("range_end must be greater than or equal to range_start")
        return self


class WorldAdoptionSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed_key: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    source_ref: WorldAdoptionSourceRef
    disposition: Literal["experience_promise", "included", "open", "rejected"]


class WorldCoreCheckpointSaveRequest(BaseModel):
    novel_id: str
    checkpoint: WorldCoreCheckpointPayload


class WorldAdoptionRelationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(..., min_length=1, max_length=128)
    target_ref: str = Field(..., min_length=1, max_length=128)
    relation_type: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=5000)


class WorldAdoptionCoreEntityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "promote"] = "create"
    entity_id: str | None = None
    entity: CoreEntityCreate | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> WorldAdoptionCoreEntityPayload:
        if self.operation == "create" and (self.entity is None or self.entity_id):
            raise ValueError(
                "create core entity item requires entity and forbids entity_id"
            )
        if self.operation == "promote" and (
            not self.entity_id or self.entity is not None
        ):
            raise ValueError(
                "promote core entity item requires entity_id and forbids entity"
            )
        return self


class WorldAdoptionPageClaimMapping(BaseModel):
    """One eligible page claim must name its adopted package evidence."""

    model_config = ConfigDict(extra="forbid")

    content_key: str = Field(..., min_length=1, max_length=64)
    claim: str = Field(..., min_length=1, max_length=5000)
    item_key: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    source_ref: WorldAdoptionSourceRef


class WorldAdoptionPagePayload(BaseModel):
    """Complete page proposal, published only through the existing lifecycle."""

    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "replace"]
    page_id: str | None = None
    expected_page_version: int | None = Field(default=None, ge=1)
    title: str = Field(..., min_length=1, max_length=255)
    page_type: str = Field(..., min_length=1, max_length=64)
    free_text: str | None = None
    sections_json: list[WorldBibleSection] = Field(default_factory=list, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] = Field(default_factory=list)
    sort_order: int = 0
    template_key: str | None = Field(default=None, max_length=128)
    template_version: int = Field(default=1, ge=1)
    claim_mappings: list[WorldAdoptionPageClaimMapping] = Field(
        default_factory=list, max_length=256
    )

    @model_validator(mode="after")
    def validate_page_target(self) -> WorldAdoptionPagePayload:
        if self.operation == "create" and (
            self.page_id is not None or self.expected_page_version is not None
        ):
            raise ValueError("new page proposal forbids page baseline")
        if self.operation == "replace" and (
            not self.page_id or self.expected_page_version is None
        ):
            raise ValueError("replace page proposal requires page_id and page version")
        return self


class WorldAdoptionBaseline(BaseModel):
    """Client-declared promotion expectation; server fingerprints remain authoritative."""

    model_config = ConfigDict(extra="forbid")

    expected_status: Literal["draft", "candidate"]
    expected_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("expected_fingerprint")
    @classmethod
    def validate_expected_fingerprint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_lower_sha256(value, "expected_fingerprint")


class WorldAdoptionPackageItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: Literal["core_entity", "entity_relation", "world_bible_page"]
    disposition: Literal["include", "open", "rejected"] = "open"
    authority_kind: Literal[
        "author_seed", "canonical_baseline", "manuscript_observation", "generated_bridge"
    ]
    source_refs: list[WorldAdoptionSourceRef] = Field(default_factory=list, max_length=16)
    baseline: WorldAdoptionBaseline | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_typed_payload(self) -> WorldAdoptionPackageItem:
        if self.kind == "core_entity":
            payload = WorldAdoptionCoreEntityPayload.model_validate(self.payload)
            if payload.operation == "promote" and self.baseline is None:
                raise ValueError("promote core entity item requires a typed baseline")
            if payload.operation == "create" and self.baseline is not None:
                raise ValueError("create core entity item forbids baseline")
        elif self.kind == "entity_relation":
            WorldAdoptionRelationPayload.model_validate(self.payload)
            if self.baseline is not None:
                raise ValueError("entity relation item forbids baseline")
        else:
            WorldAdoptionPagePayload.model_validate(self.payload)
            if self.baseline is not None:
                raise ValueError("World Bible page item forbids entity baseline")
        return self


class WorldAdoptionPackagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_adoption_package.v1"]
    checkpoint_suggestion_id: str | None = None
    checkpoint_manifest_hash: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    source_manifest_hash: str = Field(..., min_length=64, max_length=64)
    items: list[WorldAdoptionPackageItem] = Field(..., min_length=1, max_length=32)

    @field_validator("source_manifest_hash", "checkpoint_manifest_hash")
    @classmethod
    def validate_manifest_hash(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_lower_sha256(value, "manifest_hash")

    @model_validator(mode="after")
    def validate_item_keys(self) -> WorldAdoptionPackagePayload:
        if len({item.item_key for item in self.items}) != len(self.items):
            raise ValueError("world adoption package item_key values must be unique")
        if bool(self.checkpoint_suggestion_id) != bool(self.checkpoint_manifest_hash):
            raise ValueError(
                "package checkpoint lineage must include id and manifest hash"
            )
        return self


class WorldAdoptionPackageSaveRequest(BaseModel):
    novel_id: str
    package: WorldAdoptionPackagePayload


class WorldAdoptionPackagePreviewResponse(BaseModel):
    suggestion: CreationSuggestionResponse
    expected_preview_hash: str
    canon_diff: list[dict[str, Any]] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)


class WorldAdoptionPackageApplyRequest(BaseModel):
    expected_preview_hash: str = Field(..., min_length=64, max_length=64)


def _suggestion_decision_state(
    target_type: str,
    payload_json: dict[str, Any],
) -> GeneratedWorldGenerationDecisionState | None:
    if target_type == "world_bible_page_draft":
        raw = payload_json.get("decision_state")
    elif target_type in {"core_entity", "core_entity_draft"}:
        content = payload_json.get("content_json")
        meta = content.get("_meta") if isinstance(content, dict) else None
        raw = meta.get("author_decision_state") if isinstance(meta, dict) else None
    else:
        return None
    if raw is None:
        return None
    try:
        return GeneratedWorldGenerationDecisionState.model_validate(raw)
    except PydanticValidationError:
        return None


class CreationSuggestionRevisionLink(BaseModel):
    predecessor_suggestion_id: str | None = None
    successor_suggestion_id: str | None = None

    @field_validator(
        "predecessor_suggestion_id",
        "successor_suggestion_id",
        mode="before",
    )
    @classmethod
    def coerce_revision_uuid(cls, value: object) -> str | None:
        return _optional_uuid_validator(value)

    @model_validator(mode="after")
    def validate_linear_link(self) -> CreationSuggestionRevisionLink:
        if not self.predecessor_suggestion_id and not self.successor_suggestion_id:
            raise ValueError("revision link requires a predecessor or successor")
        if self.predecessor_suggestion_id == self.successor_suggestion_id:
            raise ValueError("revision predecessor and successor must differ")
        return self


def _suggestion_revision_link(
    result_ref_json: dict[str, Any],
) -> CreationSuggestionRevisionLink | None:
    raw = result_ref_json.get("revision_link")
    if raw is None:
        return None
    try:
        return CreationSuggestionRevisionLink.model_validate(raw)
    except PydanticValidationError:
        return None


class CreationSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    source_module: str
    review_group: str
    target_type: str
    action_schema: str
    payload_json: dict = Field(default_factory=dict)
    evidence_refs_json: list = Field(default_factory=list)
    risk_level: str
    status: str
    display_state: Literal["active", "review", "archived"] | None = None
    source: str | None = None
    attention_reasons: list[str] = Field(default_factory=list)
    suggested_action: str | None = None
    decision_state: GeneratedWorldGenerationDecisionState | None = None
    revision_link: CreationSuggestionRevisionLink | None = None
    result_ref_json: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_suggestion_uuid(cls, v: object) -> str:
        return _uuid_validator(v)

    @model_validator(mode="after")
    def derive_author_state(self) -> CreationSuggestionResponse:
        from modules.world.asset_state import project_suggestion_state

        projection = project_suggestion_state(
            status=self.status,
            source_module=self.source_module,
            risk_level=self.risk_level,
            payload_json=self.payload_json,
        )
        if self.display_state is None:
            self.display_state = projection["display_state"]
        if self.source is None:
            self.source = projection["source"]
        if not self.attention_reasons:
            self.attention_reasons = projection["attention_reasons"]
        if self.suggested_action is None:
            self.suggested_action = projection["suggested_action"]
        if self.decision_state is None:
            self.decision_state = _suggestion_decision_state(
                self.target_type,
                self.payload_json,
            )
        if self.revision_link is None:
            self.revision_link = _suggestion_revision_link(self.result_ref_json)
        return self


class AskWorldSaveResponse(BaseModel):
    suggestion: CreationSuggestionResponse


class WorldGenerationCoreEntityResult(BaseModel):
    kind: Literal["core_entity"] = "core_entity"
    suggestion: CreationSuggestionResponse
    proposal: CoreEntityDraftSuggestionPayload
    review_notes: list[str] = Field(default_factory=list)


class WorldGenerationPageResult(BaseModel):
    kind: Literal["world_bible_page", "world_bible_new_page"]
    suggestion: CreationSuggestionResponse
    proposal: WorldBiblePageDraftSuggestionPayload


WorldGenerationSuggestionResult = Annotated[
    WorldGenerationCoreEntityResult | WorldGenerationPageResult,
    Field(discriminator="kind"),
]


class WorldGenerationSuggestionResponse(BaseModel):
    result: WorldGenerationSuggestionResult
    source_revision: WorldGenerationPageResult | None = None
    decision_state: GeneratedWorldGenerationDecisionState | None = None
    model: str = ""
    provider: str = ""
    context_usage: GenerationContextUsage | None = None
    source_snapshot: WorldGenerationSourceSnapshot


class WorldGenerationApplyPageDraftResponse(BaseModel):
    suggestion: CreationSuggestionResponse
    draft: WorldBiblePageDraftResponse


class CreationSuggestionListResponse(BaseModel):
    items: list[CreationSuggestionResponse]
    total: int


class CoreEntitySuggestionEditConfirmRequest(BaseModel):
    """编辑世界对象建议，并在同一裁决中采用。"""

    entity_type: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    summary: str | None = Field(default=None, max_length=5000)
    public_info: str | None = None
    hidden_truth: str | None = None
    content_json: dict[str, Any] | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    importance_level: str | None = Field(default=None, max_length=16)
    reveal_level: str | None = Field(default=None, max_length=16)

    @field_validator("entity_type")
    @classmethod
    def normalize_optional_entity_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_author_entity_type(value)


class SuggestionDecisionResponse(BaseModel):
    status: str
    suggestion_status: str
    result_ref_json: dict[str, Any] = Field(default_factory=dict)


class ConflictQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    conflict_type: str
    severity: str
    source_module: str
    target: dict = Field(default_factory=dict)
    target_hash: str | None = None
    summary: str
    evidence_refs_json: list = Field(default_factory=list)
    resolution_json: dict = Field(default_factory=dict)
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_conflict_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


class ConflictQueueListResponse(BaseModel):
    items: list[ConflictQueueResponse]
    total: int


class ConflictResolveRequest(BaseModel):
    status: str = Field(default="resolved", max_length=32)
    resolution_json: dict[str, Any] = Field(default_factory=dict)


class KnowledgeTagExclusionRequest(BaseModel):
    novel_id: str
    reason: str | None = None


class KnowledgeTagExclusionResponse(BaseModel):
    character_id: str
    tag_id: str
    excluded: bool
    reason: str | None = None


class ReaderSafetyRequest(BaseModel):
    novel_id: str
    targets: list[TargetRefSchema]
    effective_chapter_index: int | None = Field(default=None, ge=0)
    scene_id: str | None = None


class ReaderSafetyItem(BaseModel):
    target: TargetRefSchema
    target_hash: str
    reader_safe: bool
    reveal_status: str
    public_baseline: bool = False
    diagnostics: list[str] = Field(default_factory=list)


class ReaderSafetyResponse(BaseModel):
    items: list[ReaderSafetyItem]
