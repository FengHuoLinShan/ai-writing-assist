"""Stable World boundary for evidence-backed spatial clue candidates."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.world.map_structure_schemas import SpatialQuantityRange, SpatialValidity
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyTraits,
)
from shared.observation import ObservationModality

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
SpatialVocabularyKind = Literal[
    "space",
    "level",
    "feature",
    "relation",
    "transport",
    "traveler",
    "access_condition",
]
MapSpatialClueKind = Literal[
    "contains",
    "bearing",
    "adjacency",
    "connection",
    "journey",
    "access_condition",
    "effective_change",
]
MapSpatialClueVerdict = Literal["supported", "unsupported", "uncertain"]
MapSpatialClueStatus = Literal[
    "pending_review",
    "pending_verification",
    "adopted",
    "rejected",
    "superseded",
]


class SpatialClueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MapSpatialClueSourceRange(SpatialClueModel):
    """One immutable manuscript range from Evolution's SceneSourceBinding."""

    draft_id: str = Field(min_length=1, max_length=128)
    chapter_index: int = Field(ge=1)
    content_hash: Annotated[str, Field(min_length=32, max_length=64)]
    start_offset: int = Field(default=0, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    range_hash: Annotated[str, Field(min_length=32, max_length=64)] | None = None

    @model_validator(mode="after")
    def validate_range(self) -> MapSpatialClueSourceRange:
        if self.end_offset is not None and self.end_offset < self.start_offset:
            raise ValueError("end_offset must be >= start_offset")
        return self


class MapSpatialClueSourceBinding(MapSpatialClueSourceRange):
    """Exact source binding plus the mode Evolution actually read."""

    content_mode: Literal["canonical", "working"]
    additional_sources: list[MapSpatialClueSourceRange] = Field(
        default_factory=list, max_length=15
    )

    @model_validator(mode="after")
    def validate_source_order(self) -> MapSpatialClueSourceBinding:
        ranges = [
            MapSpatialClueSourceRange.model_validate(
                self.model_dump(exclude={"content_mode", "additional_sources"})
            ),
            *self.additional_sources,
        ]
        for previous, current in zip(ranges, ranges[1:]):
            if current.chapter_index < previous.chapter_index:
                raise ValueError("source ranges must follow chapter order")
            if current.chapter_index == previous.chapter_index and (
                previous.end_offset is None or current.start_offset < previous.end_offset
            ):
                raise ValueError("source ranges must not overlap")
        return self

    def ranges(self) -> list[MapSpatialClueSourceRange]:
        return [
            MapSpatialClueSourceRange.model_validate(
                self.model_dump(exclude={"content_mode", "additional_sources"})
            ),
            *self.additional_sources,
        ]


class MapSpatialClueEndpointIdentity(SpatialClueModel):
    """Canonical or candidate World endpoint that was present in this batch input."""

    entity_id: UUID
    state: Literal["canonical", "candidate"]


class MapSpatialClueEndpoint(SpatialClueModel):
    """A bound endpoint or an unresolved surface label for the author tray."""

    entity_id: UUID | None = None
    state: Literal["canonical", "candidate"] | None = None
    surface: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_endpoint(self) -> MapSpatialClueEndpoint:
        bound = self.entity_id is not None and self.state is not None
        unresolved = self.entity_id is None and self.state is None and self.surface is not None
        if bound == unresolved:
            raise ValueError("endpoint must be a bound entity or one unresolved surface")
        if bound and self.surface is not None:
            raise ValueError("a bound endpoint cannot also contain an unresolved surface")
        if self.surface is not None and not self.surface.strip():
            raise ValueError("endpoint surface must not be blank")
        if self.surface is not None:
            self.surface = self.surface.strip()
        return self


class MapSpatialClueTypeRef(SpatialClueModel):
    type_ref: UUID
    type_revision_id: UUID
    kind: SpatialVocabularyKind


class MapSpatialClueCallRef(SpatialClueModel):
    """Opaque journal and provider request identities for one frozen call."""

    journal_key: str = Field(min_length=1, max_length=160)
    request_id: str | None = Field(default=None, min_length=1, max_length=256)


class MapSpatialClueReview(SpatialClueModel):
    """Independent review bound to the exact proposal and quote evidence."""

    proposal_call: MapSpatialClueCallRef
    review_call: MapSpatialClueCallRef
    proposal_hash: Sha256
    evidence_hash: Sha256
    verdict: MapSpatialClueVerdict

    @model_validator(mode="after")
    def calls_are_independent(self) -> MapSpatialClueReview:
        if self.proposal_call.journal_key == self.review_call.journal_key:
            raise ValueError("proposal and reviewer must use different journal keys")
        if (
            self.proposal_call.request_id is not None
            and self.proposal_call.request_id == self.review_call.request_id
        ):
            raise ValueError("proposal and reviewer must use different request ids")
        return self


class MapSpatialClueAttributes(SpatialClueModel):
    """Bounded optional details needed to later build a map document."""

    transport_label: str | None = Field(default=None, min_length=1, max_length=200)
    transport_type: MapSpatialClueTypeRef | None = None
    traveler_type: MapSpatialClueTypeRef | None = None
    duration: SpatialQuantityRange | None = None
    distance: SpatialQuantityRange | None = None
    access_conditions: list[str] = Field(default_factory=list, max_length=16)
    effective: SpatialValidity | None = None
    change_label: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_access_conditions(self) -> MapSpatialClueAttributes:
        if any(not item.strip() for item in self.access_conditions):
            raise ValueError("access conditions must not be blank")
        return self


class MapSpatialClue(SpatialClueModel):
    """One extracted spatial claim; it is never a World fact or map head write."""

    clue_key: Sha256
    kind: MapSpatialClueKind
    subject: MapSpatialClueEndpoint
    target: MapSpatialClueEndpoint | None = None
    relation: str | None = Field(default=None, min_length=1, max_length=96)
    type_ref: UUID | None = None
    type_revision_id: UUID | None = None
    type_kind: SpatialVocabularyKind | None = None
    type_proposal: ModelVocabularyProposal | None = None
    modality: ObservationModality
    quote: str = Field(min_length=1, max_length=2000)
    attributes: MapSpatialClueAttributes = Field(default_factory=MapSpatialClueAttributes)
    review: MapSpatialClueReview

    @model_validator(mode="after")
    def validate_claim(self) -> MapSpatialClue:
        if not self.quote.strip():
            raise ValueError("spatial clue quote must not be blank")
        if self.kind in {"contains", "bearing", "adjacency", "connection", "journey"}:
            if self.target is None:
                raise ValueError("this spatial clue kind requires a target endpoint")
        type_fields = (self.type_ref, self.type_revision_id, self.type_kind)
        if any(item is not None for item in type_fields) and not all(
            item is not None for item in type_fields
        ):
            raise ValueError("a type reference must pin identity, revision, and kind")
        if self.type_proposal is not None and any(item is not None for item in type_fields):
            raise ValueError("a clue cannot carry both a fixed type and a type proposal")
        if (
            self.type_proposal is not None
            and self.type_proposal.kind not in SpatialVocabularyKind.__args__
        ):
            raise ValueError("type proposal kind must be a spatial vocabulary kind")
        return self


class MapSpatialClueBatch(SpatialClueModel):
    """Per-Scene discovery handoff from Evolution to World."""

    run_id: str = Field(min_length=1, max_length=120)
    attempt_id: str = Field(min_length=1, max_length=120)
    scene_id: str = Field(min_length=1, max_length=128)
    scene_index: int = Field(ge=0)
    source_manifest_hash: Sha256
    source_binding: MapSpatialClueSourceBinding
    method_fingerprint: Sha256
    allowed_endpoint_ids: list[MapSpatialClueEndpointIdentity] = Field(
        default_factory=list, max_length=128
    )
    allowed_type_revisions: list[MapSpatialClueTypeRef] = Field(
        default_factory=list, max_length=64
    )
    clues: list[MapSpatialClue] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def unique_batch_identities(self) -> MapSpatialClueBatch:
        if len({item.clue_key for item in self.clues}) != len(self.clues):
            raise ValueError("clue_key values must be unique within a batch")
        endpoint_keys = {
            (item.entity_id, item.state) for item in self.allowed_endpoint_ids
        }
        if len(endpoint_keys) != len(self.allowed_endpoint_ids):
            raise ValueError("allowed endpoint identities must be unique")
        type_keys = {
            (item.type_ref, item.type_revision_id, item.kind)
            for item in self.allowed_type_revisions
        }
        if len(type_keys) != len(self.allowed_type_revisions):
            raise ValueError("allowed type revisions must be unique")
        return self


class MapSpatialClueContextType(SpatialClueModel):
    id: UUID
    revision_id: UUID
    kind: SpatialVocabularyKind
    status: Literal["active", "emerging", "archived", "merged"]
    source: Literal["author", "model", "preset"]
    name: str
    aliases: list[str] = Field(default_factory=list, max_length=24)
    description: str = Field(default="", max_length=1000)
    traits: VocabularyTraits = Field(default_factory=VocabularyTraits)
    evidence: list[VocabularyEvidence] = Field(default_factory=list, max_length=32)
    proposal_run_id: UUID | None = None


class MapSpatialClueContextItem(SpatialClueModel):
    clue_id: UUID
    scene_id: str
    scene_index: int = Field(ge=0)
    clue_key: Sha256
    subject: MapSpatialClueEndpoint
    target: MapSpatialClueEndpoint | None = None
    kind: MapSpatialClueKind
    relation: str | None = None
    type_ref: UUID | None = None
    modality: ObservationModality
    quote: str = Field(min_length=1, max_length=2000)
    status: MapSpatialClueStatus


class MapSpatialClueContext(SpatialClueModel):
    types: list[MapSpatialClueContextType] = Field(default_factory=list, max_length=64)
    clues: list[MapSpatialClueContextItem] = Field(default_factory=list, max_length=128)
    endpoint_states: dict[str, Literal["canonical", "candidate"]] = Field(
        default_factory=dict, max_length=128
    )
    omitted_types: int = Field(default=0, ge=0)
    omitted_clues: int = Field(default=0, ge=0)


class MapSpatialClueResultRef(SpatialClueModel):
    clue_key: Sha256
    clue_id: UUID
    status: MapSpatialClueStatus


class MapSpatialClueRejection(SpatialClueModel):
    clue_key: Sha256
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class MapSpatialClueStageResult(SpatialClueModel):
    """Per-clue write outcome; accepted rows remain author-review candidates."""

    result_refs: list[MapSpatialClueResultRef] = Field(default_factory=list)
    accepted: list[MapSpatialClueResultRef] = Field(default_factory=list)
    pending: list[MapSpatialClueResultRef] = Field(default_factory=list)
    rejected: list[MapSpatialClueRejection] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list, max_length=128)


class MapSpatialClueDecisionRequest(SpatialClueModel):
    action: Literal["adopt", "reject", "merge"]
    expected_fingerprint: Sha256
    confirmed: Literal[True]
    target_clue_id: UUID | None = None
    target_fingerprint: Sha256 | None = None
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_merge_target(self) -> MapSpatialClueDecisionRequest:
        if self.action == "merge":
            if self.target_clue_id is None or self.target_fingerprint is None:
                raise ValueError("merge requires a target clue and its fingerprint")
        elif self.target_clue_id is not None or self.target_fingerprint is not None:
            raise ValueError("only merge may specify a target clue")
        return self


class MapSpatialClueResponse(SpatialClueModel):
    """Author-facing clue data; internal run/reviewer identities stay private."""

    id: UUID
    novel_id: UUID
    scene_id: str
    scene_index: int
    clue_key: Sha256
    status: MapSpatialClueStatus
    fingerprint: Sha256
    kind: MapSpatialClueKind
    subject: MapSpatialClueEndpoint
    target: MapSpatialClueEndpoint | None = None
    relation: str | None = None
    type_ref: UUID | None = None
    modality: ObservationModality
    quote: str
    attributes: MapSpatialClueAttributes
    verification_note: str | None = None
    merged_into_id: UUID | None = None


class MapSpatialClueListResponse(SpatialClueModel):
    items: list[MapSpatialClueResponse]
    total_count: int = Field(ge=0)


__all__ = [
    "MapSpatialClue",
    "MapSpatialClueAttributes",
    "MapSpatialClueBatch",
    "MapSpatialClueCallRef",
    "MapSpatialClueContext",
    "MapSpatialClueContextItem",
    "MapSpatialClueContextType",
    "MapSpatialClueDecisionRequest",
    "MapSpatialClueEndpoint",
    "MapSpatialClueEndpointIdentity",
    "MapSpatialClueKind",
    "MapSpatialClueListResponse",
    "MapSpatialClueRejection",
    "MapSpatialClueResponse",
    "MapSpatialClueResultRef",
    "MapSpatialClueReview",
    "MapSpatialClueSourceBinding",
    "MapSpatialClueSourceRange",
    "MapSpatialClueStageResult",
    "MapSpatialClueStageResult",
    "MapSpatialClueStatus",
    "MapSpatialClueTypeRef",
    "MapSpatialClueVerdict",
    "SpatialVocabularyKind",
]
