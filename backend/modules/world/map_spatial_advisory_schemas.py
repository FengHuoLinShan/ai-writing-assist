"""Read-only, evidence-bound spatial advisory contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MapSpatialTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_location_id: str
    to_location_id: str
    mover_id: str | None = None


class MapSpatialAdvisoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scene_id: str
    transitions: list[MapSpatialTransition] = Field(default_factory=list, max_length=50)


class MapSpatialAdvisoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_code: Literal[
        "direction_conflict",
        "location_not_effective",
        "route_no_active_connection",
        "journey_duration_conflict",
        "cross_space_connection_unknown",
    ]
    summary: str = Field(min_length=1, max_length=600)
    node_id: str
    revision_id: str
    revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_hashes: list[str] = Field(default_factory=list, max_length=32)
    feature_ids: list[str] = Field(default_factory=list, max_length=8)
    fix_paths: tuple[Literal["writing", "map"], ...] = ("writing", "map")
    dismissible: bool = True
    unknowns: list[str] = Field(default_factory=list, max_length=4)


class MapSpatialAdvisoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str | None = None
    scene_index: int | None = None
    items: list[MapSpatialAdvisoryItem] = Field(default_factory=list, max_length=100)
    omitted_count: int = Field(default=0, ge=0)
