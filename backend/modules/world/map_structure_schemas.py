"""Bounded spatial documents; models describe relations, never executable drawings."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

from modules.writing.contracts import SourceRangeRefContract
from shared.observation import ObservationModality

FeatureKey = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9:_.-]{0,95}$")]
Coordinate = Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)]
StructureLevel = Literal["region", "city", "district", "street", "interior"]
STRUCTURE_LEVELS = {"region", "city", "district", "street", "interior"}


SpatialRelation = Literal[
    "inside",
    "north",
    "south",
    "east",
    "west",
    "northeast",
    "northwest",
    "southeast",
    "southwest",
    "adjacent",
    "connects",
    "passes_through",
    "along_street",
    "entrance_to",
    "faces",
]
SYSTEM_SPATIAL_RELATIONS = {
    "inside",
    "north",
    "south",
    "east",
    "west",
    "northeast",
    "northwest",
    "southeast",
    "southwest",
    "adjacent",
    "connects",
    "passes_through",
    "along_street",
    "entrance_to",
    "faces",
}


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MapPoint(SpatialModel):
    x: Coordinate
    y: Coordinate


class ProjectTypeRevisionRef(SpatialModel):
    type_ref: UUID | None = None
    type_revision_id: UUID | None = None

    @model_validator(mode="after")
    def paired_type_revision(self):
        if (self.type_ref is None) != (self.type_revision_id is None):
            raise ValueError("a project type must pin both its identity and revision")
        return self


class MapSpace(ProjectTypeRevisionRef):
    id: FeatureKey
    label: str = Field(min_length=1, max_length=200)

    @field_validator("label")
    @classmethod
    def readable_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("space labels must not be blank")
        return value.strip()


class SpatialAnchor(SpatialModel):
    kind: Literal["chapter", "scene"]
    id: UUID


class SpatialValidity(SpatialModel):
    start: SpatialAnchor | None = None
    end: SpatialAnchor | None = None

    @model_validator(mode="after")
    def requires_anchor(self):
        if self.start is None and self.end is None:
            raise ValueError("a validity range needs at least one stable anchor")
        return self


class SpatialQuantityRange(SpatialModel):
    minimum: Decimal | None = Field(default=None, ge=0)
    maximum: Decimal | None = Field(default=None, ge=0)
    unit: str = Field(min_length=1, max_length=32)

    @field_validator("unit")
    @classmethod
    def readable_unit(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("quantity units must not be blank")
        return normalized

    @model_validator(mode="after")
    def ordered_range(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("a quantity needs at least one bound")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("quantity range minimum must not exceed maximum")
        return self


class SpatialAccessCondition(ProjectTypeRevisionRef):
    label: str = Field(min_length=1, max_length=500)

    @field_validator("label")
    @classmethod
    def readable_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("access conditions must not be blank")
        return value.strip()


class MapSource(SpatialModel):
    kind: Literal["entity", "world_bible_page", "source_range"]
    id: UUID
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    quote: str = Field(default="", max_length=1000)
    source_ref: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_ref(self):
        if self.kind != "source_range" and self.source_ref:
            raise ValueError("only manuscript ranges accept a source_ref")
        if self.kind == "source_range":
            if set(self.source_ref) != {
                item.name for item in fields(SourceRangeRefContract)
            }:
                raise ValueError(
                    "manuscript range fields do not match the source contract"
                )
            reference = TypeAdapter(SourceRangeRefContract).validate_python(
                self.source_ref
            )
            if (
                reference.content_mode != "canonical"
                or reference.chapter_index < 1
                or reference.version_number < 1
                or reference.start_offset < 0
                or reference.end_offset <= reference.start_offset
                or str(reference.draft_id) != str(self.id)
                or reference.source_hash != self.source_hash
                or not re.fullmatch(r"[a-f0-9]{64}", reference.range_hash)
            ):
                raise ValueError("invalid canonical manuscript range")
            self.source_ref = asdict(reference)
        if len(json.dumps(self.source_ref, ensure_ascii=False)) > 6000:
            raise ValueError("source reference is too large")
        return self


class MapFeature(ProjectTypeRevisionRef):
    id: FeatureKey
    kind: Literal["location", "landmark", "road", "river", "area"]
    label: str = Field(min_length=1, max_length=200)
    space_id: FeatureKey = "main"
    entity_id: UUID | None = None
    target_node_id: UUID | None = None
    points: list[MapPoint] = Field(default_factory=list, max_length=128)
    locked: bool = False
    sources: list[MapSource] = Field(default_factory=list, max_length=8)
    depends_on: list[FeatureKey] = Field(default_factory=list, max_length=200)
    note: str = Field(default="", max_length=1000)
    reader_from_chapter: int | None = Field(default=None, ge=1, le=100000)
    modality: ObservationModality = "event_observed"
    effective: SpatialValidity | None = None

    @field_validator("label")
    @classmethod
    def readable_label(cls, value):
        if not value.strip():
            raise ValueError("map labels must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def shape(self):
        minimum = 3 if self.kind == "area" else 2 if self.kind in {"road", "river"} else 1
        if self.points and len(self.points) < minimum:
            raise ValueError("insufficient geometry points")
        if self.kind in {"location", "landmark"} and len(self.points) > 1:
            raise ValueError("a location has one point")
        return self


class SpatialConstraint(ProjectTypeRevisionRef):
    id: FeatureKey
    subject: FeatureKey
    relation: FeatureKey
    target: FeatureKey
    via: list[FeatureKey] = Field(default_factory=list, max_length=30)
    path_kind: Literal["road", "river"] = "road"
    path_label: str | None = Field(default=None, min_length=1, max_length=200)
    path_type_ref: UUID | None = None
    path_type_revision_id: UUID | None = None
    sources: list[MapSource] = Field(default_factory=list, max_length=8)
    generated_by_task_id: UUID | None = None
    modality: ObservationModality = "event_observed"
    effective: SpatialValidity | None = None

    @model_validator(mode="after")
    def paired_path_type_revision(self):
        if (self.path_type_ref is None) != (self.path_type_revision_id is None):
            raise ValueError("a path type must pin both its identity and revision")
        return self


class SpatialJourney(SpatialModel):
    id: FeatureKey
    origin: FeatureKey
    destination: FeatureKey
    transport_label: str = Field(min_length=1, max_length=200)
    transport_type_ref: UUID | None = None
    transport_type_revision_id: UUID | None = None
    traveler_type_ref: UUID | None = None
    traveler_type_revision_id: UUID | None = None
    connection_type_ref: UUID | None = None
    connection_type_revision_id: UUID | None = None
    duration: SpatialQuantityRange | None = None
    distance: SpatialQuantityRange | None = None
    access_conditions: list[SpatialAccessCondition] = Field(
        default_factory=list, max_length=30
    )
    modality: ObservationModality = "event_observed"
    sources: list[MapSource] = Field(min_length=1, max_length=8)
    effective: SpatialValidity | None = None

    @field_validator("transport_label")
    @classmethod
    def readable_transport(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("transport labels must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def journey_references_and_evidence(self):
        for type_ref, revision_id in (
            (self.transport_type_ref, self.transport_type_revision_id),
            (self.traveler_type_ref, self.traveler_type_revision_id),
            (self.connection_type_ref, self.connection_type_revision_id),
        ):
            if (type_ref is None) != (revision_id is None):
                raise ValueError("a journey type must pin both its identity and revision")
        if not any(source.quote.strip() for source in self.sources):
            raise ValueError("a journey needs at least one quoted source")
        return self


class CalibrationAnchor(SpatialModel):
    feature_id: FeatureKey
    image_x: float = Field(ge=0, le=1)
    image_y: float = Field(ge=0, le=1)


class MapImagePlacement(SpatialModel):
    page_id: UUID
    role: Literal["background", "illustration"]
    feature_id: FeatureKey | None = None
    opacity: float = Field(default=0.65, ge=0, le=1)
    anchors: list[CalibrationAnchor] = Field(default_factory=list, max_length=3)
    geometry_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reader_from_chapter: int | None = Field(default=None, ge=1, le=100000)
    reader_image_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def calibration(self):
        if self.role == "background" and len(self.anchors) != 3:
            raise ValueError("a background requires three calibration anchors")
        if self.role == "illustration" and self.anchors:
            raise ValueError("illustrations do not use calibration anchors")
        if self.reader_from_chapter is not None and not self.reader_image_hash:
            raise ValueError("reader image approval must bind the image hash")
        return self


class MapAnnotationBinding(SpatialModel):
    annotation_id: UUID
    feature_id: FeatureKey


class MapDocument(SpatialModel):
    schema_version: Literal[1, 2] = 2
    layout_version: Literal[1] = 1
    spaces: list[MapSpace] = Field(default_factory=list, max_length=20)
    features: list[MapFeature] = Field(default_factory=list, max_length=200)
    constraints: list[SpatialConstraint] = Field(default_factory=list, max_length=400)
    journeys: list[SpatialJourney] = Field(default_factory=list, max_length=400)
    images: list[MapImagePlacement] = Field(default_factory=list, max_length=40)
    annotation_bindings: list[MapAnnotationBinding] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def references(self):
        if self.schema_version == 1:
            if self.spaces or self.journeys:
                raise ValueError("v1 documents cannot contain v2 spaces or journeys")
            if any(
                feature.space_id != "main"
                or feature.type_ref is not None
                or feature.type_revision_id is not None
                or feature.effective is not None
                for feature in self.features
            ):
                raise ValueError(
                    "v1 features cannot contain v2 space, type, or time data"
                )
            if any(
                item.type_ref is not None
                or item.type_revision_id is not None
                or item.path_type_ref is not None
                or item.path_type_revision_id is not None
                or item.effective is not None
                for item in self.constraints
            ):
                raise ValueError("v1 constraints cannot contain v2 type or time data")
            space_ids = {"main"}
        else:
            if not any(space.id == "main" for space in self.spaces):
                self.spaces.insert(0, MapSpace(id="main", label="主空间"))
            space_ids = {space.id for space in self.spaces}
            if len(space_ids) != len(self.spaces):
                raise ValueError("space identities must be unique")
        ids = {item.id for item in self.features}
        if len(ids) != len(self.features):
            raise ValueError("feature identities must be unique")
        if len({item.id for item in self.constraints}) != len(self.constraints):
            raise ValueError("constraint identities must be unique")
        for item in self.features:
            if item.space_id not in space_ids:
                raise ValueError("feature refers to a missing space")
            if not set(item.depends_on).issubset(ids) or item.id in item.depends_on:
                raise ValueError("invalid geometry dependency")
        features = {item.id: item for item in self.features}
        for item in self.constraints:
            if not {item.subject, item.target, *item.via}.issubset(ids):
                raise ValueError("constraint refers to a missing feature")
            if item.relation not in SYSTEM_SPATIAL_RELATIONS:
                if self.schema_version != 2 or item.type_ref is None:
                    raise ValueError("a custom relation needs a v2 project type")
            endpoint_spaces = {
                features[item.subject].space_id,
                features[item.target].space_id,
                *(features[key].space_id for key in item.via),
            }
            if len(endpoint_spaces) > 1:
                if self.schema_version != 2 or item.type_ref is None or item.via:
                    raise ValueError(
                        "cross-space relations need a v2 relation type and no via path"
                    )
            if item.relation in {"along_street", "entrance_to", "faces"}:
                if item.subject == item.target or item.via:
                    raise ValueError(
                        "a point relation needs distinct endpoints and no via"
                    )
                allowed_targets = (
                    {"road"}
                    if item.relation == "along_street"
                    else {"location", "landmark", "area"}
                )
                if features[item.subject].kind not in {"location", "landmark"}:
                    raise ValueError(
                        "a point relation must start at a location or landmark"
                    )
                if features[item.target].kind not in allowed_targets:
                    raise ValueError(
                        "point relation target has an incompatible feature kind"
                    )
        if len({item.id for item in self.journeys}) != len(self.journeys):
            raise ValueError("journey identities must be unique")
        for journey in self.journeys:
            if journey.origin not in ids or journey.destination not in ids:
                raise ValueError("journey refers to a missing feature")
            if (
                features[journey.origin].space_id
                != features[journey.destination].space_id
                and journey.connection_type_ref is None
            ):
                raise ValueError(
                    "a cross-space journey needs a typed cross-space connection"
                )
        for item in self.images:
            if item.feature_id is not None and item.feature_id not in ids:
                raise ValueError("image refers to a missing feature")
            if not {a.feature_id for a in item.anchors}.issubset(ids):
                raise ValueError("calibration refers to a missing feature")
        if sum(item.role == "background" for item in self.images) > 1:
            raise ValueError("only one background may be selected")
        if len({item.page_id for item in self.images}) != len(self.images):
            raise ValueError("image placements must be unique")
        if len({item.annotation_id for item in self.annotation_bindings}) != len(
            self.annotation_bindings
        ):
            raise ValueError("annotation bindings must be unique")
        if any(item.feature_id not in ids for item in self.annotation_bindings):
            raise ValueError("annotation refers to a missing feature")
        if sum(len(f.points) for f in self.features) > 2000:
            raise ValueError("map geometry is too large")
        if len(self.model_dump_json()) > 1_000_000:
            raise ValueError("map document is too large")
        return self


class MapProblem(SpatialModel):
    code: str
    message: str
    feature_ids: list[str]


class MapNodeCreate(SpatialModel):
    title: str = Field(min_length=1, max_length=200)
    level: StructureLevel = "region"
    parent_id: UUID | None = None
    location_entity_id: UUID | None = None
    level_type_ref: UUID | None = None
    level_type_revision_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def readable_title(cls, value):
        if not value.strip():
            raise ValueError("map title must not be blank")
        return value.strip()

    @model_validator(mode="after")
    def paired_level_type_revision(self):
        if (self.level_type_ref is None) != (self.level_type_revision_id is None):
            raise ValueError("a level type must pin both its identity and revision")
        return self


class MapSaveRequest(SpatialModel):
    base_revision_id: UUID | None
    document: MapDocument


class MapRevisionReview(SpatialModel):
    base_revision_id: UUID | None
    action: Literal["adopt", "reject", "restore"]
    change_keys: list[str] | None = Field(default=None, min_length=1, max_length=1480)

    @model_validator(mode="after")
    def selection(self):
        if self.change_keys is not None:
            if self.action != "adopt" or len(set(self.change_keys)) != len(
                self.change_keys
            ):
                raise ValueError("only adoption accepts unique change keys")
            if any(len(key) > 120 for key in self.change_keys):
                raise ValueError("change key is too long")
        return self


class MapGenerateRequest(SpatialModel):
    operation_id: UUID
    base_revision_id: UUID | None
    context_confirmation_id: UUID
    location_ids: list[UUID] = Field(default_factory=list, max_length=20)
    feature_ids: list[FeatureKey] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_locations(self):
        if len(set(self.location_ids)) != len(self.location_ids):
            raise ValueError("locations must be unique")
        if len(set(self.feature_ids)) != len(self.feature_ids):
            raise ValueError("features must be unique")
        if not 1 <= len(self.location_ids) + len(self.feature_ids) <= 20:
            raise ValueError("select between one and twenty map targets")
        if self.feature_ids and self.base_revision_id is None:
            raise ValueError("existing features require a saved baseline")
        return self


class MapReviewPreview(SpatialModel):
    candidate_revision_id: str
    base_revision_id: str | None
    applied_change_keys: list[str]
    expanded_change_keys: list[str]


class MapRevisionResponse(SpatialModel):
    id: str
    node_id: str
    base_revision_id: str | None
    status: Literal["candidate", "saved", "rejected", "superseded"]
    document: MapDocument
    geometry_hash: str
    problems: list[MapProblem]
    created_at: datetime
    applied_change_keys: list[str] = Field(default_factory=list)
    expanded_change_keys: list[str] = Field(default_factory=list)
    remaining_candidate_id: str | None = None
    writing_chapter_index: int | None = None
    change_note: str | None = None


class MapLayoutResponse(SpatialModel):
    document: MapDocument
    geometry_hash: str
    problems: list[MapProblem]
    image_layers: list[dict] = Field(default_factory=list)


class MapNodeMapResponse(SpatialModel):
    node_id: str
    revision: MapRevisionResponse | None = None
    candidates: list[MapRevisionResponse] = Field(default_factory=list)
    image_layers: list[dict] = Field(default_factory=list)
    task_id: str | None = None
    task_status: str | None = None
    generation_summary: MapExtractionSummary | None = None


class MapPresenceItem(SpatialModel):
    character_id: str
    character_name: str
    presence_kind: Literal["confirmed_in_scene", "last_observed", "unknown"]
    location: str | None = None
    location_id: str | None = None
    feature_id: str | None = None
    scene_index: int | None = None
    source_receipt: dict = Field(default_factory=dict)


class MapSceneContext(SpatialModel):
    protocol: Literal["map_scene_context_v1"] = "map_scene_context_v1"
    view: Literal["author"] = "author"
    scene_ref: dict
    map_revision: str | None
    presence_items: list[MapPresenceItem]
    history: list[MapPresenceItem]
    routes: list[dict]
    source_receipts: list[dict]
    coverage: dict
    omissions: list[str]
    unsupported_dimensions: list[str]
    freshness: Literal["current", "partial"]
    generation_stamp: str
    request_context_id: str


class MapRelationEvidence(SpatialModel):
    source_key: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=1000)


class MapGeneratedRelation(SpatialModel):
    subject: FeatureKey
    relation: SpatialRelation
    target: FeatureKey
    via: list[FeatureKey] = Field(default_factory=list, max_length=20)
    path_kind: Literal["road", "river"] = "road"
    path_label: str | None = Field(default=None, min_length=1, max_length=200)
    evidence: list[MapRelationEvidence] = Field(default_factory=list, max_length=5)
    source_keys: list[str] = Field(default_factory=list, max_length=5)
    quote: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def cited_evidence(self):
        if self.evidence:
            if self.source_keys or self.quote:
                raise ValueError(
                    "use per-source evidence or legacy shared quote, not both"
                )
        elif not self.source_keys or not self.quote:
            raise ValueError("each spatial relation requires quoted evidence")
        return self


class MapRelationBatch(SpatialModel):
    relations: list[MapGeneratedRelation] = Field(max_length=60)


DiscardReason = Literal[
    "unknown_feature",
    "outside_selection",
    "unknown_source",
    "quote_mismatch",
    "path_label_mismatch",
    "source_changed",
    "invalid_geometry",
    "invalid_schema",
]


class MapExtractionSummary(SpatialModel):
    outcome: Literal["complete", "partial", "no_supported_relations", "failed"]
    message: str
    targets: int = Field(ge=0)
    sources: int = Field(ge=0)
    input_characters: int = Field(ge=0)
    batches: int = Field(ge=0)
    failed_batches: int = Field(ge=0)
    truncated_batches: int = Field(ge=0)
    received_relations: int = Field(ge=0)
    accepted_relations: int = Field(ge=0)
    discarded_relations: int = Field(ge=0)
    discard_reasons: dict[DiscardReason, int]
    structured_attempts: int | None = Field(default=None, ge=0)
    format_retries: int | None = Field(default=None, ge=0)


class MapTaskResponse(SpatialModel):
    task_id: str
    status: str


class MapReaderFeature(SpatialModel):
    id: FeatureKey
    kind: Literal["location", "landmark", "road", "river", "area"]
    label: str = Field(min_length=1, max_length=200)
    points: list[MapPoint] = Field(max_length=128)


class MapReaderImage(SpatialModel):
    page_id: UUID
    role: Literal["background", "illustration"]
    feature_id: FeatureKey | None
    transform: list[float] | None
    opacity: float = Field(ge=0, le=1)


class MapReaderJourney(SpatialModel):
    id: FeatureKey
    origin: FeatureKey
    destination: FeatureKey
    transport_label: str = Field(min_length=1, max_length=200)
    duration: SpatialQuantityRange | None = None
    distance: SpatialQuantityRange | None = None
    access_conditions: list[str] = Field(max_length=30)


class MapReaderPreview(SpatialModel):
    chapter: int = Field(ge=1, le=100000)
    features: list[MapReaderFeature] = Field(max_length=200)
    journeys: list[MapReaderJourney] = Field(default_factory=list, max_length=400)
    images: list[MapReaderImage] = Field(max_length=40)


class MapLinkQuery(SpatialModel):
    chapter_index: int | None = Field(default=None, ge=1, le=100000)
    entity_id: UUID | None = None
    q: str = Field(default="", max_length=100)
    limit: int = Field(default=50, ge=1, le=100)


class MapLink(SpatialModel):
    node_id: UUID
    node_title: str
    level: str
    feature_id: FeatureKey
    feature_label: str
    entity_id: UUID | None
    chapter_indices: list[int]


class MapLinksResponse(SpatialModel):
    items: list[MapLink] = Field(default_factory=list, max_length=100)
    truncated: bool = False
