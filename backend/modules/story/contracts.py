"""Stable Story read contracts for downstream Scene/workflow consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from modules.story.continuity.contracts import (
    SCENE_MEMORY_DIMENSIONS,
    ChapterPanoramaContract,
    MemoryContinuityEvidenceContract,
    MemoryDeltaEventIngest,
    MemoryDeltaIngestResult,
    MemoryEventContract,
    SceneCheckpointRepairResult,
)
from modules.story.outline_state.contracts import (
    SCENE_SEMANTIC_FIELD_STATUSES,
    SCENE_SEMANTIC_FIELDS,
    NeighborSceneBriefContract,
    OutlineAnalysisContextContract,
    OutlineArcContract,
    OutlineAuthorAttentionItemContract,
    PlotThreadContract,
    ReaderRevealDecisionContract,
    SceneBoundaryAssessmentContract,
    SceneBoundaryReviewOutputContract,
    SceneCandidateConcernContract,
    SceneContextWindowContract,
    SceneContract,
    SceneExecutionBundleContract,
    SceneExecutionSceneContract,
    SceneFusionSynthesisOutputContract,
    SceneSpanContract,
    SceneSpanCoverageContract,
    SceneSummaryCheckpointContract,
    scene_semantic_field_status,
)
from modules.story.schemas import (
    CharacterCardResponse,
    CharacterCardRevisionResponse,
    SceneScriptFileResponse,
    SceneScriptRevisionResponse,
    StorySceneContextResponse,
)


@dataclass(frozen=True)
class StoryWorldDependencyContract:
    kind: Literal["story_thread", "outline_arc", "outline_scene", "story_outline"]
    id: str
    label: str
    source_hash: str
    version: str
    text: str
    match_basis: Literal["declared", "literal"] = "declared"


__all__ = [
    "StoryWorldDependencyContract",
    "CharacterCardResponse",
    "CharacterCardRevisionResponse",
    "SceneScriptFileResponse",
    "SceneScriptRevisionResponse",
    "StorySceneContextResponse",
    "SCENE_MEMORY_DIMENSIONS",
    "SCENE_SEMANTIC_FIELDS",
    "SCENE_SEMANTIC_FIELD_STATUSES",
    "ChapterPanoramaContract",
    "MemoryContinuityEvidenceContract",
    "MemoryDeltaEventIngest",
    "MemoryDeltaIngestResult",
    "MemoryEventContract",
    "NeighborSceneBriefContract",
    "OutlineAnalysisContextContract",
    "OutlineArcContract",
    "OutlineAuthorAttentionItemContract",
    "PlotThreadContract",
    "ReaderRevealDecisionContract",
    "SceneBoundaryAssessmentContract",
    "SceneBoundaryReviewOutputContract",
    "SceneCandidateConcernContract",
    "SceneCheckpointRepairResult",
    "SceneContextWindowContract",
    "SceneContract",
    "SceneExecutionBundleContract",
    "SceneExecutionSceneContract",
    "SceneFusionSynthesisOutputContract",
    "SceneSpanContract",
    "SceneSpanCoverageContract",
    "SceneSummaryCheckpointContract",
    "scene_semantic_field_status",
]
