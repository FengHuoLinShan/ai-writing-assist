"""世界设计检查点与迭代 schema。"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.llm_schemas import (
    GeneratedWorldCoreConvergence,
    GeneratedWorldGenerationDecisionState,
)
from modules.world.schemas._common import _validate_lower_sha256
from modules.world.schemas.adoption import WorldAdoptionSeed, WorldCoreCheckpointDecision
from modules.world.schemas.generation import WorldGenerationChatRequest
from modules.world.schemas.worldstate import (
    WORLD_STATE_COUPLING_CHAINS,
    WORLD_STATE_FACETS,
    WORLD_STATE_PRESSURE_TESTS,
    WorldStateAudit,
    WorldStateAuthority,
    WorldStateChange,
    WorldStateCouplingChain,
    WorldStateCoverageEntry,
    WorldStateDependency,
    WorldStateEntity,
    WorldStateFacet,
    WorldStateFictionCore,
    WorldStateKnowledge,
    WorldStateKnowledgeLayers,
    WorldStatePipelineEntry,
    WorldStatePremise,
    WorldStatePressureTest,
    WorldStateProject,
    WorldStateReproductionLoops,
    WorldStateRule,
    WorldStateSituatedTest,
    WorldStateSituatedTests,
)


class WorldDesignWorldState(BaseModel):
    """The 19-section worldbuilding-engine state carried inside a checkpoint."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1.0"]
    engine_version: str = Field(..., min_length=1, max_length=64)
    project: WorldStateProject
    authority: WorldStateAuthority
    premise: WorldStatePremise
    knowledge_layers: WorldStateKnowledgeLayers
    rules: list[WorldStateRule] = Field(default_factory=list, max_length=128)
    reproduction_loops: WorldStateReproductionLoops
    facets: list[WorldStateFacet] = Field(..., min_length=22, max_length=22)
    coupling_chains: list[WorldStateCouplingChain] = Field(
        ..., min_length=5, max_length=5
    )
    situated_tests: WorldStateSituatedTests
    pressure_tests: list[WorldStatePressureTest] = Field(
        ..., min_length=12, max_length=12
    )
    actors: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    places: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    institutions: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    history: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    fiction_core: WorldStateFictionCore
    dependencies: list[WorldStateDependency] = Field(default_factory=list, max_length=512)
    change_log: list[WorldStateChange] = Field(default_factory=list, max_length=256)
    audit: WorldStateAudit
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_taxonomy(self) -> WorldDesignWorldState:
        for prefix, values, names in (
            ("F", self.facets, WORLD_STATE_FACETS),
            ("C", self.coupling_chains, WORLD_STATE_COUPLING_CHAINS),
            ("T", self.pressure_tests, WORLD_STATE_PRESSURE_TESTS),
        ):
            expected = {
                f"{prefix}{index:02d}": name for index, name in enumerate(names, start=1)
            }
            actual = {item.id: item.name for item in values}
            if actual != expected:
                raise ValueError(
                    f"{prefix} taxonomy must contain each required id "
                    "and name exactly once"
                )
        all_ids = [item.id for item in self.rules]
        all_ids.extend(
            item.id
            for group in (self.actors, self.places, self.institutions, self.history)
            for item in group
        )
        all_ids.extend(
            item.id
            for group in (
                self.authority.locked_decisions,
                self.authority.author_required,
                self.authority.open_questions,
                self.knowledge_layers.author_truth,
                self.knowledge_layers.expert_models,
                self.knowledge_layers.public_beliefs,
                self.knowledge_layers.reader_unknowns,
            )
            for item in group
        )
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("world state ids must be unique")
        known_ids = {
            self.project.id,
            *all_ids,
            *(item.id for item in self.facets),
            *(item.id for item in self.coupling_chains),
            *(item.id for item in self.pressure_tests),
        }
        for edge in self.dependencies:
            if edge.source not in known_ids or edge.to not in known_ids:
                raise ValueError("world state dependency endpoints must resolve")
        for rule in self.rules:
            if any(target not in known_ids for target in rule.dependencies):
                raise ValueError("world state rule dependencies must resolve")
        return self


class WorldDesignCheckpointPayload(BaseModel):
    """Read-only full-world state checkpoint; it can never be adopted."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["world_design_checkpoint.v1"]
    depth: Literal["seed", "candidate", "instance"]
    round_no: int = Field(..., ge=0)
    action: Literal["expand", "connect", "pressure", "consolidate"]
    parent_checkpoint_id: str | None = None
    source_manifest_hash: str = Field(..., min_length=64, max_length=64)
    seeds: list[WorldAdoptionSeed] = Field(default_factory=list, max_length=64)
    decision_state: GeneratedWorldGenerationDecisionState | None = None
    world_core: GeneratedWorldCoreConvergence | None = None
    decisions: list[WorldCoreCheckpointDecision] = Field(
        default_factory=list, max_length=64
    )
    world_state: WorldDesignWorldState

    @field_validator("source_manifest_hash")
    @classmethod
    def validate_source_manifest_hash(cls, value: str) -> str:
        return _validate_lower_sha256(value, "source_manifest_hash")

    @model_validator(mode="after")
    def validate_serialized_size(self) -> WorldDesignCheckpointPayload:
        size = len(
            json.dumps(
                self.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if size > 1024 * 1024:
            raise ValueError("world design checkpoint exceeds 1 MiB")
        return self


class WorldDesignCheckpointSaveRequest(BaseModel):
    novel_id: str
    checkpoint: WorldDesignCheckpointPayload


class WorldDesignChanges(BaseModel):
    """Typed changed entries only; omitted entries always inherit the parent."""

    model_config = ConfigDict(extra="forbid")

    premise: WorldStatePremise | None = None
    knowledge_layers: dict[
        Literal["author_truth", "expert_models", "public_beliefs", "reader_unknowns"],
        list[WorldStateKnowledge],
    ] = Field(default_factory=dict)
    rules: list[WorldStateRule] = Field(default_factory=list, max_length=128)
    reproduction_loops: dict[
        Literal[
            "material",
            "population_care",
            "economic",
            "institutional",
            "knowledge",
            "meaning_identity",
        ],
        WorldStateCoverageEntry,
    ] = Field(default_factory=dict)
    facets: list[WorldStateFacet] = Field(default_factory=list, max_length=22)
    coupling_chains: list[WorldStateCouplingChain] = Field(
        default_factory=list, max_length=5
    )
    situated_tests: dict[
        Literal[
            "ordinary_tuesday", "seven_day_failure", "life_course", "ten_year_feedback"
        ],
        WorldStateSituatedTest,
    ] = Field(default_factory=dict)
    pressure_tests: list[WorldStatePressureTest] = Field(
        default_factory=list, max_length=12
    )
    actors: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    places: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    institutions: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    history: list[WorldStateEntity] = Field(default_factory=list, max_length=256)
    dependencies: list[WorldStateDependency] = Field(default_factory=list, max_length=512)
    fiction_core: dict[
        Literal["world", "character", "story", "outline", "prose", "editor"],
        WorldStatePipelineEntry,
    ] = Field(default_factory=dict)


class WorldDesignRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    session_id: uuid.UUID
    parent_checkpoint_id: uuid.UUID
    expected_checkpoint_id: uuid.UUID | None
    action: Literal["expand", "connect", "pressure", "consolidate"]
    summary: str = Field(..., min_length=1, max_length=5000)
    changes: WorldDesignChanges
    decisions: list[WorldCoreCheckpointDecision] = Field(
        default_factory=list, max_length=64
    )
    depth: Literal["seed", "candidate", "instance"] | None = None
    context_confirmation_id: uuid.UUID | None = None
    origin_task_id: uuid.UUID | None = None


class WorldDesignIterationRequest(WorldGenerationChatRequest):
    action: Literal["expand", "connect", "pressure", "consolidate"]
    parent_checkpoint_id: uuid.UUID


class WorldDesignIterationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1, max_length=5000)
    changes: WorldDesignChanges


class WorldDesignReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "passed_with_open_questions", "blocked"]
    checked_aspects: list[str] = Field(default_factory=list, max_length=8)
    addressed_issues: list[str] = Field(default_factory=list, max_length=8)
    insufficient_evidence: list[str] = Field(default_factory=list, max_length=8)
    author_decisions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def forbid_internal_review_details(self) -> WorldDesignReviewSummary:
        text = "\n".join(
            [
                *self.checked_aspects,
                *self.addressed_issues,
                *self.insufficient_evidence,
                *self.author_decisions,
            ]
        ).lower()
        if re.search(
            r"world-design:[a-z0-9]|intent_scope|causal_operability|\bprompt\b",
            text,
        ):
            raise ValueError("review_summary must not expose internal review details")
        return self


class WorldDesignIterationResponse(WorldDesignIterationOutput):
    parent_checkpoint_id: str
    context_confirmation_id: str
    source_manifest_hash: str
    knowledge_review: dict[str, Any] | None = None
    task_brief: GeneratedWorldGenerationDecisionState | None = None
    review_summary: WorldDesignReviewSummary | None = None
