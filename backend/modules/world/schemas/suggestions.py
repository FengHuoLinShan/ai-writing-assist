"""建议队列决策、冲突队列、知识标签排除与读者安全 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from modules.world.llm_schemas import GeneratedWorldGenerationDecisionState
from modules.world.schemas._common import (
    OptionalUuidStr,
    UuidStr,
    _normalize_author_entity_type,
)
from modules.world.schemas.bible import (
    WorldBiblePageDraftResponse,
    WorldBiblePageDraftSuggestionPayload,
)
from modules.world.schemas.generation import (
    CoreEntityDraftSuggestionPayload,
    GenerationContextUsage,
    WorldGenerationSourceSnapshot,
)
from modules.world.schemas.workspace import TargetRefSchema


class CreationSuggestionRevisionLink(BaseModel):
    predecessor_suggestion_id: OptionalUuidStr = None
    successor_suggestion_id: OptionalUuidStr = None

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


class CreationSuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UuidStr
    novel_id: UuidStr
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
    knowledge_review: dict[str, Any] | None = None


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

    id: UuidStr
    novel_id: UuidStr
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


class ConflictQueueListResponse(BaseModel):
    items: list[ConflictQueueResponse]
    total: int
    skip: int = 0
    limit: int | None = None


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
