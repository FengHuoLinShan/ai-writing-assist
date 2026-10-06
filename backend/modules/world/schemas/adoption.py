"""检查点与采用包 schema（创建建议载体）。"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.llm_schemas import (
    GeneratedWorldCoreConvergence,
    GeneratedWorldGenerationDecisionState,
)
from modules.world.schemas._common import AliasKind, RelationKind, _validate_lower_sha256
from modules.world.schemas.entities import CoreEntityCreate
from modules.world.schemas.suggestions import CreationSuggestionResponse
from modules.world.schemas.workspace import WorldBibleSection


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
        "world_bible_page",
        "core_entity",
        "manuscript",
        "conversation",
        "external",
        "author_decision",
    ]
    source_id: str = Field(..., min_length=1, max_length=128)
    source_version: str | None = Field(default=None, max_length=128)
    source_hash: str = Field(..., min_length=64, max_length=64)
    range_start: int | None = Field(default=None, ge=0)
    range_end: int | None = Field(default=None, ge=0)
    scene_id: str | None = None
    workflow_id: str | None = Field(default=None, max_length=128)
    authorization_ref: str | None = Field(default=None, max_length=128)
    source_range: dict[str, Any] | None = None
    quote: str | None = Field(default=None, max_length=10000)

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
    relation_kind: RelationKind | None = None
    description: str | None = Field(default=None, max_length=5000)
    operation: Literal["create", "promote", "existing_ref"] = "create"
    relation_id: str | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> WorldAdoptionRelationPayload:
        if self.operation in {"promote", "existing_ref"} and not self.relation_id:
            raise ValueError(
                f"{self.operation} entity relation item requires relation_id"
            )
        if self.operation == "create" and self.relation_id is not None:
            raise ValueError("create entity relation item forbids relation_id")
        return self


class WorldAdoptionCoreEntityPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["create", "promote", "existing_ref", "fill_empty"] = "create"
    entity_id: str | None = None
    entity: CoreEntityCreate | None = None
    fields: dict[Literal["summary", "public_info", "hidden_truth"], str] | None = None

    @model_validator(mode="after")
    def validate_operation(self) -> WorldAdoptionCoreEntityPayload:
        if self.operation == "fill_empty":
            if not self.entity_id or self.entity is not None or not self.fields:
                raise ValueError("fill_empty requires entity_id and nonempty fields")
            if any(
                not value.strip() or len(value) > 10000 for value in self.fields.values()
            ):
                raise ValueError("fill_empty values must be bounded nonempty text")
        elif self.fields is not None:
            raise ValueError("Only fill_empty accepts fields")
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
        if self.operation == "existing_ref" and (
            not self.entity_id or self.entity is not None
        ):
            raise ValueError(
                "existing_ref core entity item requires entity_id and forbids entity"
            )
        return self


class WorldAdoptionAliasPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    candidate_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64, exclude_if=lambda value: value is None
    )

    entity_ref: str = Field(min_length=1, max_length=128)
    alias: str = Field(min_length=1, max_length=255)
    alias_kind: AliasKind
    alias_type: str = Field(default="alias", min_length=1, max_length=64)


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
    kind: Literal["core_entity", "entity_relation", "world_bible_page", "entity_alias"]
    disposition: Literal["include", "open", "rejected"] = "open"
    authority_kind: Literal[
        "author_seed", "canonical_baseline", "manuscript_observation", "generated_bridge"
    ]
    source_refs: list[WorldAdoptionSourceRef] = Field(
        default_factory=list, max_length=256
    )
    baseline: WorldAdoptionBaseline | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    root_key: str | None = Field(default=None, max_length=128)
    depth: Literal[0, 1] = 0
    review_reasons: list[str] = Field(default_factory=list, max_length=16)
    review_evidence: dict[str, list[str]] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    direct_relation_ref: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_typed_payload(self) -> WorldAdoptionPackageItem:
        if self.kind == "core_entity":
            payload = WorldAdoptionCoreEntityPayload.model_validate(self.payload)
            if payload.operation == "promote" and self.baseline is None:
                raise ValueError("promote core entity item requires a typed baseline")
            if payload.operation != "promote" and self.baseline is not None:
                raise ValueError("create core entity item forbids baseline")
        elif self.kind == "entity_relation":
            WorldAdoptionRelationPayload.model_validate(self.payload)
            if self.baseline is not None:
                raise ValueError("entity relation item forbids baseline")
        elif self.kind == "entity_alias":
            WorldAdoptionAliasPayload.model_validate(self.payload)
            if self.baseline is not None:
                raise ValueError("alias item forbids promotion baseline")
        else:
            WorldAdoptionPagePayload.model_validate(self.payload)
            if self.baseline is not None:
                raise ValueError("World Bible page item forbids entity baseline")
        return self


class WorldAdoptionPackagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_adoption_package.v1", "world_adoption_package.v2"]
    focused_authorization_id: str | None = None
    review_resolution_run: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    focused_roots: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    context_fingerprint: str | None = None
    focused_request_hash: str | None = None
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
        if self.review_resolution_run and any(
            item.kind == "world_bible_page"
            or item.payload.get("operation") in {"create", "replace", "fill_empty"}
            for item in self.items
        ):
            raise ValueError("Manual resolution only adopts existing candidates")
        specialized = any(
            item.kind == "entity_alias" or item.payload.get("operation") == "fill_empty"
            for item in self.items
        )
        if specialized and self.schema_version != "world_adoption_package.v2":
            raise ValueError("Focused additions require adoption package v2")
        if self.focused_authorization_id and (
            self.schema_version != "world_adoption_package.v2"
            or not self.context_fingerprint
        ):
            raise ValueError("Focused packages require v2 and context fingerprint")
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
    validation_run_id: uuid.UUID | None = None


