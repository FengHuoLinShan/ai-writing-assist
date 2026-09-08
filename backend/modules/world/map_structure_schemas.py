"""Bounded spatial documents; models describe relations, never executable drawings."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from datetime import datetime
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

FeatureKey = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9:_.-]{0,95}$")]
Coordinate = Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)]


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
]


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MapPoint(SpatialModel):
    x: Coordinate
    y: Coordinate


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


class MapFeature(SpatialModel):
    id: FeatureKey
    kind: Literal["location", "landmark", "road", "river", "area"]
    label: str = Field(min_length=1, max_length=200)
    entity_id: UUID | None = None
    target_node_id: UUID | None = None
    points: list[MapPoint] = Field(default_factory=list, max_length=128)
    locked: bool = False
    sources: list[MapSource] = Field(default_factory=list, max_length=8)
    depends_on: list[FeatureKey] = Field(default_factory=list, max_length=200)
    note: str = Field(default="", max_length=1000)
    reader_from_chapter: int | None = Field(default=None, ge=1, le=100000)

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


class SpatialConstraint(SpatialModel):
    id: FeatureKey
    subject: FeatureKey
    relation: SpatialRelation
    target: FeatureKey
    via: list[FeatureKey] = Field(default_factory=list, max_length=30)
    path_kind: Literal["road", "river"] = "road"
    path_label: str | None = Field(default=None, min_length=1, max_length=200)
    sources: list[MapSource] = Field(default_factory=list, max_length=8)


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
    schema_version: Literal[1] = 1
    layout_version: Literal[1] = 1
    features: list[MapFeature] = Field(default_factory=list, max_length=200)
    constraints: list[SpatialConstraint] = Field(default_factory=list, max_length=400)
    images: list[MapImagePlacement] = Field(default_factory=list, max_length=40)
    annotation_bindings: list[MapAnnotationBinding] = Field(
        default_factory=list, max_length=100
    )

    @model_validator(mode="after")
    def references(self):
        ids = {item.id for item in self.features}
        if len(ids) != len(self.features):
            raise ValueError("feature identities must be unique")
        if len({item.id for item in self.constraints}) != len(self.constraints):
            raise ValueError("constraint identities must be unique")
        for item in self.features:
            if not set(item.depends_on).issubset(ids) or item.id in item.depends_on:
                raise ValueError("invalid geometry dependency")
        for item in self.constraints:
            if not {item.subject, item.target, *item.via}.issubset(ids):
                raise ValueError("constraint refers to a missing feature")
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
    level: Literal["region", "city"] = "region"
    parent_id: UUID | None = None
    location_entity_id: UUID | None = None

    @field_validator("title")
    @classmethod
    def readable_title(cls, value):
        if not value.strip():
            raise ValueError("map title must not be blank")
        return value.strip()


class MapSaveRequest(SpatialModel):
    base_revision_id: UUID | None
    document: MapDocument


class MapRevisionReview(SpatialModel):
    base_revision_id: UUID | None
    action: Literal["adopt", "reject", "restore"]


class MapGenerateRequest(SpatialModel):
    operation_id: UUID
    base_revision_id: UUID | None
    context_confirmation_id: UUID
    location_ids: list[UUID] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_locations(self):
        if len(set(self.location_ids)) != len(self.location_ids):
            raise ValueError("locations must be unique")
        return self


class MapRevisionResponse(SpatialModel):
    id: str
    node_id: str
    base_revision_id: str | None
    status: Literal["candidate", "saved", "rejected"]
    document: MapDocument
    geometry_hash: str
    problems: list[MapProblem]
    created_at: datetime


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


class MapGeneratedRelation(SpatialModel):
    subject: FeatureKey
    relation: SpatialRelation
    target: FeatureKey
    via: list[FeatureKey] = Field(default_factory=list, max_length=20)
    path_kind: Literal["road", "river"] = "road"
    path_label: str | None = Field(default=None, min_length=1, max_length=200)
    source_keys: list[str] = Field(min_length=1, max_length=5)
    quote: str = Field(min_length=1, max_length=1000)


class MapRelationBatch(SpatialModel):
    relations: list[MapGeneratedRelation] = Field(default_factory=list, max_length=60)


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


class MapReaderPreview(SpatialModel):
    chapter: int = Field(ge=1, le=100000)
    features: list[MapReaderFeature] = Field(max_length=200)
    images: list[MapReaderImage] = Field(max_length=40)
