"""Read-only spatial brief contracts for authoring context and Ask World."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MapSpatialBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scene_id: str | None = None
    chapter_index: int | None = Field(default=None, ge=1)
    reveal_mode: Literal["author_safe", "author_full", "reader", "character"] = (
        "author_safe"
    )
    viewpoint_character_id: str | None = None
    query_text: str = Field(default="", max_length=2000)
    excluded_ids: list[str] = Field(default_factory=list, max_length=200)
    limit: int = Field(default=20, ge=1, le=20)


class MapSpatialBriefItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    revision_id: str
    title: str = Field(max_length=200)
    content: str = Field(max_length=3000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    geometry_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_hashes: list[str] = Field(default_factory=list, max_length=64)


class MapSpatialBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str | None = None
    scene_index: int | None = None
    chapter_index: int | None = None
    items: list[MapSpatialBriefItem] = Field(default_factory=list, max_length=20)
    omitted_count: int = Field(default=0, ge=0)
