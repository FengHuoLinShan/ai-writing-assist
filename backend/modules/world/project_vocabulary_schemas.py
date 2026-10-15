"""Stable vocabulary-kind and calculation-trait contracts for map clients."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VocabularyKind = Literal[
    "space",
    "level",
    "feature",
    "relation",
    "transport",
    "traveler",
    "access_condition",
    "dossier_facing",
    "faction_form",
    "territory_control",
]

VocabularyStatus = Literal["active", "emerging", "archived", "merged"]
VocabularySource = Literal["author", "model", "preset"]

GeometryTrait = Literal["point", "line", "area", "none"]
ContainmentTrait = Literal["can_contain", "independent_space"]
ConnectionTrait = Literal[
    "traversable", "directed", "cross_space", "distance_constrained"
]
OrientationTrait = Literal["compass", "vertical"]
OtherTrait = Literal["movable", "qualitative_distance"]

VocabularyName = Annotated[str, Field(min_length=1, max_length=120)]
VocabularyAlias = Annotated[str, Field(min_length=1, max_length=120)]


class VocabularyTraits(BaseModel):
    """Closed ADR-0035 computation kernel; meanings remain open text."""

    model_config = ConfigDict(extra="forbid")

    geometry: list[GeometryTrait] = Field(default_factory=list, max_length=4)
    containment: list[ContainmentTrait] = Field(default_factory=list, max_length=2)
    connection: list[ConnectionTrait] = Field(default_factory=list, max_length=4)
    orientation: list[OrientationTrait] = Field(default_factory=list, max_length=2)
    other: list[OtherTrait] = Field(default_factory=list, max_length=2)

    @field_validator("geometry", "containment", "connection", "orientation", "other")
    @classmethod
    def unique_traits(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class VocabularyTermFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: VocabularyName
    description: str = Field(default="", max_length=1000)
    aliases: list[VocabularyAlias] = Field(default_factory=list, max_length=24)
    traits: VocabularyTraits = Field(default_factory=VocabularyTraits)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("词条名称不能为空")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def nonblank_aliases(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("别名不能为空")
        return [value.strip() for value in values]


class VocabularyTermCreate(VocabularyTermFields):
    kind: VocabularyKind


class VocabularyTermUpdate(VocabularyTermFields):
    expected_revision_id: UUID


class VocabularyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID
    quote: str = Field(min_length=1, max_length=2000)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("quote")
    @classmethod
    def quote_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("证据引文不能为空")
        return value


class VocabularyTermResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    novel_id: UUID
    kind: VocabularyKind
    source: VocabularySource
    status: VocabularyStatus
    revision_id: UUID
    revision_number: int
    previous_revision_id: UUID | None = None
    name: str
    description: str
    aliases: list[str]
    traits: VocabularyTraits
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    author_confirmed: bool
    redirect_to_id: UUID | None = None
    preset_id: str | None = None
    preset_version: int | None = None
    preset_item_key: str | None = None
    evidence: list[VocabularyEvidence] = Field(default_factory=list)


class VocabularyReviewReceipt(BaseModel):
    """Opaque result from M1's independent reviewer, bound to exact evidence."""

    model_config = ConfigDict(extra="forbid")

    reviewer_run_id: UUID
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: Literal["passed", "failed"]


class ModelVocabularyProposal(VocabularyTermFields):
    kind: VocabularyKind
    proposal_run_id: UUID
    evidence: list[VocabularyEvidence] = Field(min_length=1, max_length=32)
    independent_review: VocabularyReviewReceipt | None = None

    @model_validator(mode="after")
    def reviewer_is_independent(self):
        if (
            self.independent_review is not None
            and self.independent_review.reviewer_run_id == self.proposal_run_id
        ):
            raise ValueError("独立复核必须来自不同的运行")
        return self


class VocabularyArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: UUID


class VocabularyMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    source_ids: list[UUID] = Field(min_length=1, max_length=20)
    expected_revision_ids: dict[UUID, UUID]

    @model_validator(mode="after")
    def merge_refs_are_complete(self):
        refs = [self.target_id, *self.source_ids]
        if self.target_id in self.source_ids or len(set(refs)) != len(refs):
            raise ValueError("合并目标与来源必须是互不重复的词条")
        if set(self.expected_revision_ids) != set(refs):
            raise ValueError("每个合并词条都必须携带当前修订 ID")
        return self


class VocabularySplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: UUID
    retained: VocabularyTermFields
    split_off: VocabularyTermFields


class VocabularyRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision_id: UUID


class VocabularyPresetApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_ids: list[
        Literal["xianxia", "fantasy", "urban", "science_fiction", "mystery"]
    ] = Field(min_length=1, max_length=5)

    @field_validator("preset_ids")
    @classmethod
    def unique_presets(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("同一预设不能重复选择")
        return values


class VocabularyPresetApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: int
    already_applied: int
    duplicate_skipped: int
    items: list[VocabularyTermResponse]


class VocabularySplitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retained: VocabularyTermResponse
    split_off: VocabularyTermResponse


class ProjectVocabularyReadItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: VocabularyKind
    source: VocabularySource
    status: VocabularyStatus
    revision_id: UUID
    revision_number: int
    name: str
    description: str
    aliases: list[str]
    traits: VocabularyTraits
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    redirect_to_id: UUID | None = None


class ProjectVocabularyReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProjectVocabularyReadItem]
    total_count: int
    omitted_count: int


class ModelVocabularyProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["created", "updated", "reused", "restore_suggested"]
    item: VocabularyTermResponse | None = None
    existing_type_ref: UUID | None = None


def vocabulary_evidence_hash(evidence: list[VocabularyEvidence]) -> str:
    """Digest the exact quote set so review cannot be reused after evidence changes."""
    normalized = sorted(
        (
            {
                "scene_id": str(item.scene_id),
                "quote": item.quote,
                "source_hash": item.source_hash,
            }
            for item in evidence
        ),
        key=lambda item: (item["scene_id"], item["quote"], item["source_hash"]),
    )
    raw = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
