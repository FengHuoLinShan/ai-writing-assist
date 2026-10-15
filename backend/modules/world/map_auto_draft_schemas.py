"""World-owned contracts for deterministic, incremental map drafts."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from modules.world.map_atlas_schemas import MapAtlasNodeResponse
from modules.world.map_spatial_clue_schemas import MapSpatialClueEndpoint
from modules.world.map_structure_schemas import MapDocument, MapPoint

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MapAutoDraftStatus = Literal["running", "completed", "stale"]
MapAutoDraftRedoReason = Literal[
    "method_or_kernel_changed",
    "clue_superseded",
    "hierarchy_parent_changed",
    "incremental_placement_failed",
    "author_requested",
]


class MapAutoDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MapAutoDraftBuildRequest(MapAutoDraftModel):
    """One aggregate build boundary; clue records may come from many attempts."""

    run_id: str = Field(min_length=1, max_length=120)
    build_key: str = Field(min_length=1, max_length=120)
    through_scene_id: UUID
    through_scene_index: int = Field(ge=0)
    clue_ids: list[UUID] | None = Field(default=None, max_length=20_000)


class MapAutoDraftRevisionRef(MapAutoDraftModel):
    node_id: UUID
    revision_id: UUID
    base_revision_id: UUID | None = None
    status: Literal["candidate", "saved", "rejected", "superseded", "stale"]
    feature_count: int = Field(ge=0, le=200)
    source_clue_ids: list[UUID] = Field(default_factory=list)


class MapAutoDraftTrayItem(MapAutoDraftModel):
    item_id: UUID
    node_id: UUID
    clue_id: UUID
    scene_id: str
    scene_index: int = Field(ge=0)
    endpoint_side: Literal["subject", "target"]
    endpoint: MapSpatialClueEndpoint
    quote: str = Field(min_length=1, max_length=2000)
    source_mode: Literal["canonical", "working"]
    reason: Literal[
        "unresolved_endpoint",
        "endpoint_not_location",
        "ambiguous_source_quote",
        "feature_limit",
        "relation_limit",
        "placement_failed",
        "non_event_modality",
        "hierarchy_conflict",
        "source_stale",
        "endpoint_stale",
    ]
    fingerprint: Sha256
    placed_feature_id: str | None = None


class MapAutoDraftHierarchyAlternative(MapAutoDraftModel):
    parent_entity_id: UUID
    source: Literal[
        "world_adopted",
        "saved_map",
        "reviewed_clue",
        "world_candidate",
    ]
    source_id: str


class MapAutoDraftHierarchyConflict(MapAutoDraftModel):
    child_entity_id: UUID
    chosen_parent_entity_id: UUID
    chosen_source: Literal[
        "world_adopted",
        "saved_map",
        "reviewed_clue",
        "world_candidate",
    ]
    alternatives: list[MapAutoDraftHierarchyAlternative] = Field(default_factory=list)
    fingerprint: Sha256


class MapAutoDraftBuildResult(MapAutoDraftModel):
    batch_id: UUID
    fingerprint: Sha256
    status: MapAutoDraftStatus
    cursor: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    completed_chunks: int = Field(ge=0)
    revisions: list[MapAutoDraftRevisionRef] = Field(default_factory=list)
    tray_items: list[MapAutoDraftTrayItem] = Field(default_factory=list)
    conflicts: list[MapAutoDraftHierarchyConflict] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list, max_length=128)


class MapAutoDraftBatchProgress(MapAutoDraftModel):
    batch_id: UUID
    fingerprint: Sha256
    status: MapAutoDraftStatus
    cursor: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    completed_chunks: int = Field(ge=0)


class MapAutoDraftListItem(MapAutoDraftModel):
    batch_id: UUID
    node_id: UUID
    node_title: str
    node: MapAtlasNodeResponse
    revision_id: UUID
    base_revision_id: UUID | None = None
    review_base_revision_id: UUID | None = None
    status: Literal["candidate", "superseded"]
    fingerprint: Sha256
    source_clue_ids: list[UUID] = Field(default_factory=list)
    document: MapDocument
    pending_tray: list[MapAutoDraftTrayItem] = Field(default_factory=list)
    conflicts: list[MapAutoDraftHierarchyConflict] = Field(default_factory=list)
    redo_reason: MapAutoDraftRedoReason | None = None
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)


class MapAutoDraftListResponse(MapAutoDraftModel):
    items: list[MapAutoDraftListItem]
    total_count: int = Field(ge=0)
    truncated: bool = False
    batches_truncated: bool = False
    batches: list[MapAutoDraftBatchProgress] = Field(default_factory=list, max_length=200)


class MapAutoDraftResumeRequest(MapAutoDraftModel):
    expected_fingerprint: Sha256
    confirmed: Literal[True]


class MapAutoDraftRedoRequest(MapAutoDraftModel):
    expected_fingerprint: Sha256
    reason: Literal["author_requested"]
    confirmed: Literal[True]


class MapAutoDraftTrayPlacementPreviewRequest(MapAutoDraftModel):
    expected_fingerprint: Sha256
    base_revision_id: UUID | None = None
    space_id: str = Field(default="main", min_length=1, max_length=96)
    point: MapPoint


class MapAutoDraftTrayPlacementRequest(MapAutoDraftTrayPlacementPreviewRequest):
    preview_fingerprint: Sha256
    confirmed: Literal[True]


class MapAutoDraftTrayPlacementPreview(MapAutoDraftModel):
    batch_id: UUID
    node_id: UUID
    candidate_revision_id: UUID
    base_revision_id: UUID | None = None
    item_id: UUID
    preview_fingerprint: Sha256
    feature_id: str
    old_feature_count: int = Field(ge=0, le=200)
    new_feature_count: int = Field(ge=1, le=200)
    remaining_tray_count: int = Field(ge=0)
    impacts: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class MapAutoDraftTrayPlacementResponse(MapAutoDraftModel):
    batch_id: UUID
    node_id: UUID
    revision_id: UUID
    previous_revision_id: UUID
    placed_feature_id: str
    geometry_hash: Sha256
    remaining_tray_count: int = Field(ge=0)
    status: Literal["candidate"]


__all__ = [
    "MapAutoDraftBuildRequest",
    "MapAutoDraftBuildResult",
    "MapAutoDraftBatchProgress",
    "MapAutoDraftHierarchyAlternative",
    "MapAutoDraftHierarchyConflict",
    "MapAutoDraftListItem",
    "MapAutoDraftListResponse",
    "MapAutoDraftRedoReason",
    "MapAutoDraftRedoRequest",
    "MapAutoDraftResumeRequest",
    "MapAutoDraftRevisionRef",
    "MapAutoDraftStatus",
    "MapAutoDraftTrayItem",
    "MapAutoDraftTrayPlacementPreview",
    "MapAutoDraftTrayPlacementPreviewRequest",
    "MapAutoDraftTrayPlacementRequest",
    "MapAutoDraftTrayPlacementResponse",
]
