"""Intermediate scene candidate shapes for resilient deep import."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SceneCandidateRound = Literal["A", "B"]
SceneCandidateQuality = Literal["high", "low", "failed"]


class SceneCandidateBatch(BaseModel):
    """One Phase 0/1a source batch before formal Scene writes."""

    batch_id: str
    round_name: SceneCandidateRound
    batch_index: int = Field(..., ge=1)
    chapter_indices: list[int] = Field(default_factory=list)


class SceneCandidate(BaseModel):
    """One intermediate Scene observation from a batch."""

    candidate_id: str
    source_round: SceneCandidateRound
    source_batch_id: str
    source_batch_index: int = Field(..., ge=1)
    source_chapter_indices: list[int] = Field(default_factory=list)
    quality: SceneCandidateQuality
    payload: dict = Field(default_factory=dict)
    diagnostics: dict = Field(default_factory=dict)


class ScenePrefetchResult(BaseModel):
    """Phase 0 prefetch output kept in workflow/task result only."""

    candidates: list[SceneCandidate] = Field(default_factory=list)
    quality_stats: dict = Field(default_factory=dict)
    diagnostics: list[dict] = Field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None


class SceneReinforcementResult(BaseModel):
    """Phase 1a reinforcement output kept in workflow/task result only."""

    candidates: list[SceneCandidate] = Field(default_factory=list)
    quality_stats: dict = Field(default_factory=dict)
    diagnostics: list[dict] = Field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None
    did_merge_rounds: bool = False
