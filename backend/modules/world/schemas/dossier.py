"""Validated API contracts for World object dossiers and their templates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DossierAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["scene", "chapter"]
    id: uuid.UUID


class DossierValidity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: DossierAnchor | None = None
    end: DossierAnchor | None = None


class DossierFacingRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["core", "project"]
    key: str | None = Field(default=None, min_length=1, max_length=96)
    term_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> DossierFacingRef:
        if self.kind == "core" and (self.key is None or self.term_id is not None):
            raise ValueError("core 面向需要 key，且不能携带项目词条 ID")
        if self.kind == "project" and (self.term_id is None or self.key is not None):
            raise ValueError("项目面向需要词条 ID，且不能携带 core key")
        return self


class DossierEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_id: uuid.UUID | None = None
    chapter_id: uuid.UUID | None = None
    source_hash: str | None = Field(default=None, min_length=1, max_length=128)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    quote: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_range(self) -> DossierEvidenceRef:
        if self.start_offset is not None and self.end_offset is not None:
            if self.end_offset < self.start_offset:
                raise ValueError("证据区间结束位置不能早于起始位置")
        return self


class DossierEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facing: DossierFacingRef
    legacy_field_key: str | None = Field(default=None, min_length=1, max_length=96)
    content: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=24)
    evidence: list[DossierEvidenceRef] = Field(default_factory=list, max_length=16)
    quote_text: str | None = Field(default=None, max_length=4000)
    visibility: Literal["public", "secret"] = "public"
    validity: DossierValidity | None = None

    @field_validator("content")
    @classmethod
    def require_nonblank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("档案内容不能为空")
        return value


class DossierEntryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: uuid.UUID
    content: str | None = Field(default=None, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=24)
    evidence: list[DossierEvidenceRef] | None = Field(default=None, max_length=16)
    quote_text: str | None = Field(default=None, max_length=4000)
    visibility: Literal["public", "secret"] | None = None
    validity: DossierValidity | None = None

    @model_validator(mode="after")
    def require_change(self) -> DossierEntryUpdate:
        if not (self.model_fields_set - {"expected_revision_id"}):
            raise ValueError("请至少修改一项档案内容")
        return self


class DossierEntryRestore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: uuid.UUID
    expected_current_revision_id: uuid.UUID | None = None


class DossierTemplateField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    facing: DossierFacingRef
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    required: bool = False
    value_kind: Literal["text", "text_list"] = "text"


class DossierTemplateUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version_number: int | None = Field(default=None, ge=1)
    fields: list[DossierTemplateField] = Field(max_length=128)
    display_schema: dict = Field(default_factory=dict)


class DossierTemplateResponse(BaseModel):
    profile_type: str
    template_id: uuid.UUID
    revision_id: uuid.UUID
    version_number: int
    fields: list[DossierTemplateField] = Field(default_factory=list)
    display_schema: dict = Field(default_factory=dict)
    updated_at: datetime | None = None


class DossierTemplateHistoryResponse(BaseModel):
    profile_type: str
    items: list[dict] = Field(default_factory=list)
    total_count: int = Field(ge=0)


class DossierFacetOption(BaseModel):
    facing: DossierFacingRef
    label: str
    description: str = ""
    source: Literal["core", "project"]


class DossierFacetCatalog(BaseModel):
    entity_type: str
    items: list[DossierFacetOption] = Field(default_factory=list)
    total_count: int = Field(ge=0)


class DossierEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_group_id: uuid.UUID
    revision_number: int
    previous_revision_id: uuid.UUID | None = None
    entity_id: uuid.UUID
    facing: DossierFacingRef
    facing_label: str
    legacy_field_key: str | None = None
    content: str
    tags: list[str] = Field(default_factory=list)
    evidence: list[DossierEvidenceRef] = Field(default_factory=list)
    legacy_value: Any | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    quote_text: str | None = None
    source: str
    visibility: str
    status: str
    validity: DossierValidity | None = None
    anchor_problem: str | None = None
    effective_at_cutoff: bool | None = None
    revision_reason: str | None = None
    restored_from_id: uuid.UUID | None = None
    created_at: datetime | None = None


class DossierReadResponse(BaseModel):
    entity_id: uuid.UUID
    entity_type: str
    as_of_scene_id: uuid.UUID | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=250)
    entries: list[DossierEntryResponse] = Field(default_factory=list)
    total_count: int = Field(ge=0)
    omitted_count: int = Field(ge=0)
    dossier_fingerprint: str
    layers: list[Literal["world", "continuity", "evolution"]] = Field(
        default_factory=lambda: ["world"]
    )
    unavailable_layers: list[Literal["continuity", "evolution"]] = Field(
        default_factory=list
    )
    unknown: bool = False


class DossierHistoryResponse(BaseModel):
    entity_id: uuid.UUID
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)
    entries: list[DossierEntryResponse] = Field(default_factory=list)
    total_count: int = Field(ge=0)
    omitted_count: int = Field(default=0, ge=0)
