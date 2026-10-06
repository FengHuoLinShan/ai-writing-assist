"""World Bible 工作稿、修订、模板、梗概与投影 schema。"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.llm_schemas import GeneratedWorldGenerationDecisionState
from modules.world.schemas._common import OptionalUuidStr, UuidStr
from modules.world.schemas.generation import WorldBibleSourceRef
from modules.world.schemas.workspace import (
    WorldBibleSection,
    _reject_executable_template_values,
    _validate_world_bible_sections,
)


class WorldBiblePageDraftCreate(BaseModel):
    novel_id: str
    page_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    page_type: str | None = Field(default=None, min_length=1, max_length=64)
    page_meta_json: dict[str, Any] | None = None
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
    page_meta_json: dict[str, Any] | None = None
    free_text: str | None = None
    sections_json: list[WorldBibleSection] | None = Field(default=None, max_length=64)
    linked_asset_refs_json: list[dict[str, Any]] | None = None
    sort_order: int | None = None
    template_key: str | None = Field(default=None, max_length=128)
    template_version: int | None = Field(default=None, ge=1)
    updated_by: str | None = Field(default=None, max_length=64)
    expected_updated_at: datetime | None = Field(
        default=None,
        description="编辑基线；缺失或过期返回 409，不接受无条件覆盖",
    )

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> WorldBiblePageDraftUpdate:
        for field_name in {
            "title",
            "page_type",
            "page_meta_json",
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

    id: UuidStr
    novel_id: UuidStr
    page_id: OptionalUuidStr = None
    base_version_number: int | None = None
    title: str
    page_type: str
    page_meta_json: dict[str, Any] = Field(default_factory=dict)
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


class WorldBibleDraftPublicationResponse(BaseModel):
    page_id: uuid.UUID
    version_number: int = Field(ge=1)


class WorldBiblePageDraftListResponse(BaseModel):
    items: list[WorldBiblePageDraftResponse]
    total: int


def _validate_world_policy_regex(pattern: str) -> str:
    if (
        len(pattern) > 500
        or any(char in pattern for char in "()|")
        or re.search(
            r"\\[1-9]|(?:[+*?]|\{\d+(?:,\d*)?\})\s*(?:[+*?]|\{)",
            pattern,
        )
    ):
        raise ValueError("regex uses an unsafe construct")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError("regex is invalid") from exc
    return pattern


class WorldBiblePageRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UuidStr
    novel_id: UuidStr
    page_id: UuidStr
    version_number: int
    snapshot_json: dict = Field(default_factory=dict)
    revision_digest: str
    revision_reason: str
    created_at: datetime | None = None
    writing_chapter_index: int | None = None
    change_note: str | None = None
    changed_fields: list[str] | None = None


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

    id: UuidStr
    novel_id: UuidStr
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


class WorldBiblePageTemplateListResponse(BaseModel):
    items: list[WorldBiblePageTemplateResponse]
    total: int


class WorldBiblePageTemplateRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UuidStr
    novel_id: UuidStr
    template_id: UuidStr
    version_number: int
    snapshot_json: dict = Field(default_factory=dict)
    content_hash: str
    revision_reason: str
    created_by: str | None = None
    created_at: datetime | None = None


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
    knowledge_review: dict[str, Any] | None = None

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

    id: UuidStr
    novel_id: UuidStr
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

    id: UuidStr
    novel_id: UuidStr
    page_id: UuidStr
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


class ProjectionRefreshResponse(BaseModel):
    task_id: str
    status: str
    existing: bool = False
    projection_type: str
