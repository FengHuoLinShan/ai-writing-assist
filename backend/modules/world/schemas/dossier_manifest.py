"""Bounded author-facing JSON interchange for one World object dossier."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.world.schemas.dossier import (
    DossierAnchor,
    DossierEvidenceRef,
    DossierFacingRef,
    DossierStateField,
    DossierTemplateField,
    DossierValidity,
)

MANIFEST_FORMAT = "novelcraft.world.dossier-manifest"
MAX_MANIFEST_ENTRIES = 250
MAX_MANIFEST_TEXT_CHARS = 1_000_000


class DossierManifestTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_type: str = Field(min_length=1, max_length=64)
    source_template_id: uuid.UUID
    source_revision_id: uuid.UUID
    source_version_number: int = Field(ge=1)
    revision_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    fields: list[DossierTemplateField] = Field(default_factory=list, max_length=128)
    state_fields: list[DossierStateField] = Field(default_factory=list, max_length=64)
    borrowed_facings: list[DossierFacingRef] = Field(default_factory=list, max_length=128)


class DossierManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_entry_group_id: uuid.UUID
    source_revision_id: uuid.UUID
    source_revision_number: int = Field(ge=1)
    previous_revision_id: uuid.UUID | None = None
    facing: DossierFacingRef
    facing_label: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)
    story_field_key: str | None = Field(
        default=None, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$"
    )
    tags: list[str] = Field(default_factory=list, max_length=24)
    evidence: list[DossierEvidenceRef] = Field(default_factory=list, max_length=16)
    quote_text: str | None = Field(default=None, max_length=4000)
    source: Literal[
        "author",
        "author_assistant",
        "evolution_adoption",
        "spreadsheet_migration",
        "legacy_import",
        "object_completion",
    ]
    visibility: Literal["public", "secret"]
    validity: DossierValidity | None = None

    @model_validator(mode="after")
    def nonblank_content(self):
        if not self.content.strip():
            raise ValueError("档案条目内容不能为空")
        return self


class DossierManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["novelcraft.world.dossier-manifest"] = MANIFEST_FORMAT
    format_version: Literal[1] = 1
    created_at: datetime
    source_project_id: uuid.UUID
    source_entity_id: uuid.UUID
    source_entity_type: str = Field(min_length=1, max_length=64)
    source_entity_name: str = Field(min_length=1, max_length=255)
    template: DossierManifestTemplate | None = None
    entries: list[DossierManifestEntry] = Field(max_length=MAX_MANIFEST_ENTRIES)

    @model_validator(mode="after")
    def bound_text(self):
        groups = [item.source_entry_group_id for item in self.entries]
        revisions = [item.source_revision_id for item in self.entries]
        if len(groups) != len(set(groups)) or len(revisions) != len(set(revisions)):
            raise ValueError("档案清单不能重复引用同一来源条目或修订")
        chars = len(self.source_entity_name) + sum(
            len(item.content)
            + len(item.quote_text or "")
            + sum(len(ref.quote or "") for ref in item.evidence)
            + sum(len(tag) for tag in item.tags)
            for item in self.entries
        )
        if chars > MAX_MANIFEST_TEXT_CHARS:
            raise ValueError("档案清单总文本超过 1 MB 上限")
        return self


class DossierManifestFacingMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DossierFacingRef
    target: DossierFacingRef


class DossierManifestAnchorMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DossierAnchor
    target: DossierAnchor


class DossierManifestTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: DossierManifest
    facing_mappings: list[DossierManifestFacingMapping] = Field(
        default_factory=list, max_length=128
    )
    expected_template_version_number: int | None = Field(default=None, ge=1)
    template_mapping_confirmed: bool = False
    story_field_mappings: dict[str, str] = Field(default_factory=dict, max_length=64)
    anchor_mappings: list[DossierManifestAnchorMapping] = Field(
        default_factory=list, max_length=500
    )
    skip_conflicts: list[uuid.UUID] = Field(
        default_factory=list, max_length=MAX_MANIFEST_ENTRIES
    )

    @model_validator(mode="after")
    def unique_mappings(self):
        keys = [_facing_ref_key(item.source) for item in self.facing_mappings]
        if len(keys) != len(set(keys)):
            raise ValueError("同一来源面向只能映射一次")
        if len(self.skip_conflicts) != len(set(self.skip_conflicts)):
            raise ValueError("同一条目不能重复选择跳过")
        anchors = [_anchor_key(item.source) for item in self.anchor_mappings]
        if len(anchors) != len(set(anchors)):
            raise ValueError("同一来源锚点只能映射一次")
        return self


class DossierManifestPreviewRequest(DossierManifestTransferRequest):
    pass


class DossierManifestApplyRequest(DossierManifestTransferRequest):
    expected_preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


class DossierManifestConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_revision_id: uuid.UUID
    facing_label: str
    reason: Literal["already_changed", "target_group_collision", "target_facing_changed"]


class DossierManifestPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_entity_name: str
    create_count: int = Field(ge=0)
    update_count: int = Field(ge=0)
    already_imported_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    conflicts: list[DossierManifestConflict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    can_apply: bool


class DossierManifestApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    already_imported_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def _facing_ref_key(facing: DossierFacingRef) -> str:
    if facing.kind == "project":
        return f"project:{facing.term_id}"
    return f"core:{facing.key}"


def _anchor_key(anchor: DossierAnchor) -> str:
    return f"{anchor.kind}:{anchor.id}"


__all__ = [
    "DossierManifest",
    "DossierManifestApplyRequest",
    "DossierManifestApplyResponse",
    "DossierManifestAnchorMapping",
    "DossierManifestConflict",
    "DossierManifestEntry",
    "DossierManifestFacingMapping",
    "DossierManifestPreviewRequest",
    "DossierManifestPreviewResponse",
    "DossierManifestTemplate",
    "DossierManifestTransferRequest",
    "MAX_MANIFEST_ENTRIES",
    "MAX_MANIFEST_TEXT_CHARS",
]
