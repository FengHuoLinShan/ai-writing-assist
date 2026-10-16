"""Public contracts for author-confirmed plans and evidence-bounded comparisons."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArcPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArcPlanWriteInput(ArcPlanModel):
    operation_id: UUID
    scene_id: UUID
    character_id: UUID
    expected_version: int = Field(ge=0)
    plan_text: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def nonblank_plan(self):
        if not self.plan_text.strip():
            raise ValueError("人物弧计划不能为空")
        return self


class ConfirmArcPlanInput(ArcPlanWriteInput):
    preview_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ArcPlanPreviewResponse(ArcPlanModel):
    scene_id: UUID
    character_id: UUID
    character_name: str
    expected_version: int
    current_version: int
    preview_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    current_plan_text: str | None = None
    proposed_plan_text: str
    effect: str
    requires_confirmation: Literal[True] = True
    risk_level: Literal["R3"] = "R3"
    fee_category: Literal["free"] = "free"


class ArcPlanView(ArcPlanModel):
    character_id: UUID
    character_name: str
    version: int = Field(ge=0)
    revision_id: UUID | None = None
    plan_text: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal[
        "author_confirmed",
        "author_restore",
        "author_archive",
        "author_unarchive",
    ]
    audience: Literal["director_only"] = "director_only"
    confirmed_by_owner: bool = True
    updated_at: datetime | None = None


class ArcPlanRevisionView(ArcPlanModel):
    revision_id: UUID
    version: int = Field(ge=1)
    plan_text: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: Literal[
        "author_confirmed",
        "author_restore",
        "author_archive",
        "author_unarchive",
    ]
    audience: Literal["director_only"] = "director_only"
    created_at: datetime
    restored_from_revision_id: UUID | None = None


class RestoreArcPlanInput(ArcPlanModel):
    operation_id: UUID
    scene_id: UUID
    character_id: UUID
    revision_id: UUID
    expected_version: int = Field(ge=0)
    preview_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ArchiveArcPlanInput(ArcPlanModel):
    operation_id: UUID
    scene_id: UUID
    character_id: UUID
    expected_version: int = Field(ge=1)
    preview_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class SceneCharacterReadInput(ArcPlanModel):
    scene_id: UUID


class CharacterArcReadInput(SceneCharacterReadInput):
    character_id: UUID


class SceneCharacterOption(ArcPlanModel):
    character_id: UUID
    character_name: str = Field(min_length=1, max_length=255)
    is_pov: bool = False


class SceneCharacterOptionsResponse(ArcPlanModel):
    scene_id: UUID
    scene_title: str
    scene_index: int = Field(ge=0)
    chapter_indices: list[int] = Field(default_factory=list)
    characters: list[SceneCharacterOption] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list, max_length=20)


class ArcEvidenceEvent(ArcPlanModel):
    field: str = Field(min_length=1, max_length=255)
    value: Any
    occurred_at: dict[str, int] | None = None
    chapter_index: int = Field(ge=1)
    source_label: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=1200)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    range_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArcCutoffView(ArcPlanModel):
    scene_id: UUID
    scene_index: int = Field(ge=0)
    scene_title: str
    chapter_indices: list[int] = Field(default_factory=list)
    chapter_cutoff: int | None = Field(default=None, ge=1)
    order_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class CharacterArcComparisonResponse(ArcPlanModel):
    character_id: UUID
    character_name: str
    plan: ArcPlanView | None = None
    plan_archived: bool = False
    cutoff: ArcCutoffView
    actual_events: list[ArcEvidenceEvent] = Field(default_factory=list, max_length=60)
    unknowns: list[str] = Field(default_factory=list, max_length=30)
    coverage: Literal["complete", "partial", "unknown"]
    comparison_basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    arc_completion: Literal["not_adjudicated"] = "not_adjudicated"
