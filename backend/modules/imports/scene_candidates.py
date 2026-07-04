"""Intermediate scene candidate shapes for resilient deep import."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

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


def build_scene_candidate_quality_stats(
    candidates: Sequence[SceneCandidate],
    *,
    total_batches: int,
    completed_batches: int | None = None,
    include_degraded_fallback: bool = False,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_batches": total_batches,
        "completed_batches": (
            len(candidates) if completed_batches is None else completed_batches
        ),
        "success": 0,
        "failed": 0,
        "high_quality": 0,
        "low_quality": 0,
        "empty_result": 0,
        "schema_error": 0,
        "timeout": 0,
        "network": 0,
        "rate_limit": 0,
        "quality_gate": 0,
        "http_error": 0,
        "unknown": 0,
        "final_422": 0,
    }
    if include_degraded_fallback:
        stats["degraded_fallback"] = 0

    for candidate in candidates:
        if candidate.quality == "failed":
            stats["failed"] += 1
        else:
            stats["success"] += 1
        if candidate.quality == "high":
            stats["high_quality"] += 1
        if candidate.quality == "low":
            stats["low_quality"] += 1
        if include_degraded_fallback and candidate.diagnostics.get("degraded"):
            stats["degraded_fallback"] += 1

        final_error_type = candidate.diagnostics.get("final_error_type")
        if final_error_type in stats:
            stats[final_error_type] += 1
        if final_error_type == "422":
            stats["final_422"] += 1

    stats["final_422_rate"] = (
        stats["final_422"] / total_batches if total_batches > 0 else 0.0
    )
    return stats
