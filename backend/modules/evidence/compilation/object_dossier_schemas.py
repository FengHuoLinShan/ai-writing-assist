"""Stable request and response contracts for an Evidence object brief."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ObjectDossierBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scene_id: str
    entity_ids: list[str] = Field(min_length=1, max_length=16)
    reveal_mode: Literal["author_safe", "author_full", "character", "reader"] = (
        "author_safe"
    )
    viewpoint_character_id: str | None = None
    content_mode: Literal["canonical", "working"] = "canonical"
    include_patterns: bool = False
    only_adopted_patterns: bool = False

    @field_validator("novel_id", "scene_id", "viewpoint_character_id")
    @classmethod
    def normalize_uuid(cls, value: str | None) -> str | None:
        return str(uuid.UUID(str(value))) if value is not None else None

    @field_validator("entity_ids")
    @classmethod
    def normalize_entity_ids(cls, values: list[str]) -> list[str]:
        normalized = [str(uuid.UUID(str(value))) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("entity_ids must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_viewpoint(self) -> ObjectDossierBriefRequest:
        if self.reveal_mode == "character" and not self.viewpoint_character_id:
            raise ValueError("character view requires viewpoint_character_id")
        if self.reveal_mode != "character" and self.viewpoint_character_id:
            raise ValueError("viewpoint_character_id is only valid in character view")
        if self.only_adopted_patterns and not self.include_patterns:
            raise ValueError("only_adopted_patterns requires include_patterns")
        return self


class ObjectDossierWorldItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["world_dossier", "legacy_profile_field"]
    entity_id: str
    entity_type: str
    entry_id: str | None = None
    entry_group_id: str | None = None
    revision_id: str | None = None
    revision_number: int | None = None
    profile_id: str | None = None
    template_id: str | None = None
    template_version_number: int | None = None
    field_key: str | None = None
    facing: dict[str, Any] | None = None
    facing_label: str | None = None
    legacy_field_key: str | None = None
    content: str | None = None
    value: Any = None
    tags: list[str] = Field(default_factory=list)
    visibility: str | None = None
    source: str | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    validity: dict[str, Any] | None = None
    story_field_key: str | None = None
    validity_conflict: bool = False
    story_override_applied: bool = False
    validity_gap: str | None = None
    story_observation: dict[str, Any] | None = None
    dossier_fingerprint: str | None = None

    @model_validator(mode="after")
    def validate_item_shape(self) -> ObjectDossierWorldItem:
        if self.kind == "world_dossier" and not (
            self.entry_id and self.revision_id and self.content is not None
        ):
            raise ValueError("world_dossier items require a revision and content")
        legacy_fields = (self.profile_id, self.template_id, self.field_key, self.facing)
        if (
            self.kind == "legacy_profile_field"
            and any(legacy_fields)
            and not all(legacy_fields)
        ):
            raise ValueError("mapped legacy fields require profile/template/key/facing")
        return self


class ObjectDossierStoryStateItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["story_state"] = "story_state"
    entity_id: str
    subject_label: str | None = None
    dimension: str
    field: str
    value: Any
    layer: Literal["fact", "belief", "observation"]
    possibly_false: bool = False
    occurred_at: dict[str, int] | None = None
    confidence: str
    checkpoint_id: str
    checkpoint_source_hash: str | None = None
    provenance: dict[str, Any] | None = None
    source_refs: list[dict[str, Any]] = Field(default_factory=list)


class ObjectDossierPatternItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    revision_id: str
    revision: int
    entity_ids: list[str]
    category: str
    statement: str
    conditions: list[str] = Field(default_factory=list)
    modality: str
    confidence: float = Field(ge=0, le=1)
    competing_explanations: list[str] = Field(default_factory=list)
    review_verdict: str
    author_decision: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(min_length=1)
    interpretation_only: Literal[True]


class ObjectDossierBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scene_id: str
    scene_index: int | None = None
    viewpoint: dict[str, Any]
    world_items: list[ObjectDossierWorldItem] = Field(default_factory=list)
    validity_notices: list[dict[str, Any]] = Field(default_factory=list)
    continuity_items: list[ObjectDossierStoryStateItem] = Field(default_factory=list)
    pattern_items: list[ObjectDossierPatternItem] = Field(default_factory=list)
    checkpoint_refs: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint_fingerprint: str | None = None
    world_dossier_fingerprints: list[dict[str, str]] = Field(default_factory=list)
    world_fingerprint: str | None = None
    continuity_fingerprint: str | None = None
    pattern_fingerprint: str | None = None
    omitted_count: int = Field(ge=0)
    omissions: list[str] = Field(default_factory=list)
    layers: list[Literal["world", "continuity", "evolution"]] = Field(
        default_factory=list
    )
    unknown_layers: list[Literal["world", "continuity", "evolution"]] = Field(
        default_factory=list
    )
    coverage: Literal["complete", "partial", "unknown"]
    fingerprint: str
