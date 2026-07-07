"""Route selection for Phase 2 scene entity extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Phase2ExtractionStrategy = Literal[
    "empty",
    "small_sample_parallel",
    "bulk",
    "batched",
    "checkpoint_resume",
]


@dataclass(frozen=True)
class Phase2ExtractionRoute:
    strategy: Phase2ExtractionStrategy
    reason: str
    total_scenes: int
    has_checkpoints: bool


class SceneEntityExtractionStrategySelector:
    """Selects the Phase 2 route without depending on service or DB state."""

    @staticmethod
    def select(
        total_scenes: int,
        has_checkpoints: bool,
        small_sample_min: int,
        bulk_max: int,
    ) -> Phase2ExtractionRoute:
        if total_scenes == 0:
            return Phase2ExtractionRoute(
                strategy="empty",
                reason="no_scenes",
                total_scenes=total_scenes,
                has_checkpoints=has_checkpoints,
            )

        if has_checkpoints:
            return Phase2ExtractionRoute(
                strategy="checkpoint_resume",
                reason="phase2_checkpoints_present",
                total_scenes=total_scenes,
                has_checkpoints=True,
            )

        if small_sample_min <= total_scenes <= bulk_max:
            return Phase2ExtractionRoute(
                strategy="small_sample_parallel",
                reason="small_sample_parallel_default",
                total_scenes=total_scenes,
                has_checkpoints=False,
            )

        if total_scenes <= bulk_max:
            return Phase2ExtractionRoute(
                strategy="bulk",
                reason="within_bulk_limit",
                total_scenes=total_scenes,
                has_checkpoints=False,
            )

        return Phase2ExtractionRoute(
            strategy="batched",
            reason="above_bulk_limit",
            total_scenes=total_scenes,
            has_checkpoints=False,
        )
