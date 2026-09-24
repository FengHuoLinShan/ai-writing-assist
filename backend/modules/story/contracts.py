"""Stable Story read contracts for downstream Scene/workflow consumers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from modules.story.continuity.contracts import (
    CURRENT_SCENE_MEMORY_CONTRACT_VERSION,
    SCENE_MEMORY_CONTRACT_V1,
    SCENE_MEMORY_CONTRACT_V2,
    SCENE_MEMORY_DIMENSIONS,
    SCENE_MEMORY_DIMENSIONS_V1,
    SCENE_MEMORY_DIMENSIONS_V2,
    STATE_EVENT_DIMENSIONS,
    ConfirmedContinuityEventIngest,
    MemoryContinuityEvidenceContract,
    MemoryDeltaEventIngest,
    MemoryDeltaIngestResult,
    scene_memory_dimensions,
)
from modules.story.observations import (
    InputStimulus as InputStimulusContract,  # noqa: F401
)
from modules.story.observations import (
    ObservationIntent as ActionIntentContract,  # noqa: F401
)
from modules.story.observations import ReadingNode as ReadingNode
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
    "STATE_EVENT_DIMENSIONS",
    "StoryWorldDependencyContract",
    "CharacterCardResponse",
    "CharacterCardRevisionResponse",
    "SceneScriptFileResponse",
    "SceneScriptRevisionResponse",
    "StorySceneContextResponse",
    "CURRENT_SCENE_MEMORY_CONTRACT_VERSION",
    "SCENE_MEMORY_CONTRACT_V1",
    "SCENE_MEMORY_CONTRACT_V2",
    "SCENE_MEMORY_DIMENSIONS",
    "SCENE_MEMORY_DIMENSIONS_V1",
    "SCENE_MEMORY_DIMENSIONS_V2",
    "scene_memory_dimensions",
    "ConfirmedContinuityEventIngest",
    "SCENE_SEMANTIC_FIELDS",
    "SCENE_SEMANTIC_FIELD_STATUSES",
    "MemoryContinuityEvidenceContract",
    "MemoryDeltaEventIngest",
    "MemoryDeltaIngestResult",
    "NeighborSceneBriefContract",
    "OutlineAnalysisContextContract",
    "OutlineArcContract",
    "OutlineAuthorAttentionItemContract",
    "PlotThreadContract",
    "ReaderRevealDecisionContract",
    "SceneBoundaryAssessmentContract",
    "SceneBoundaryReviewOutputContract",
    "SceneCandidateConcernContract",
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

from modules.story.outline_state.scene_resolution import (  # noqa: E402
    SceneBoundaryReview,  # noqa: F401
)


def reading_structure_schema(name):
    """Closed response schemas for source-pinned reading structure calls."""
    from modules.story.outline_state.generation.models import (
        SimpleStructureOutput,
        StructureEvidenceReviewOutput,
    )

    return {
        schema.__name__: schema
        for schema in (
            SimpleStructureOutput,
            StructureEvidenceReviewOutput,
        )
    }[name]
