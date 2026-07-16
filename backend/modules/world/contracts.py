"""
World 对外契约 — v3 因果时空网

定义其他模块可以安全依赖的世界模块接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class CoreEntityContract:
    """核心实体契约 — 其他模块通过此契约获取对象信息"""

    novel_id: str
    entity_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    display_state: str = "active"
    source: str | None = None
    attention_reasons: list[str] = field(default_factory=list)
    suggested_action: str | None = None


@dataclass(frozen=True)
class EventContract:
    """事件契约"""

    novel_id: str
    entity_id: str
    entity_name: str
    entity_type: str = "event"
    timeline_order: int = 0
    occurrence_time_label: str | None = None
    location_entity_id: str | None = None
    location_name: str | None = None


@dataclass(frozen=True)
class EntityRelationContract:
    """关系契约"""

    novel_id: str
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    quote: str | None = None
    status: str = "canonical"
    display_state: str = "active"
    source: str | None = None
    attention_reasons: list[str] = field(default_factory=list)
    suggested_action: str | None = None


@dataclass(frozen=True)
class EntityRevisionContract:
    """版本快照契约

    `entity_revisions` 在回滚时作为兜底使用，并继续承担显式
    `rollback-by-revision` 快照的存储。
    当 `TextArchive` 可用时，优先使用 TextArchive 作为回滚数据源。
    """

    entity_id: str
    revision_id: str
    revision_reason: str = "ai_import"
    created_at: str | None = None


@dataclass(frozen=True)
class CharacterContract:
    """人物契约 — 其他模块通过此契约获取人物信息"""

    character_id: str
    name: str
    role: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = field(default_factory=list)
    relationship_summary: str | None = None


@dataclass(frozen=True)
class CharacterKnowledgeContract:
    """人物知识契约 — 用于 Context Compiler 和 Review 模块"""

    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None
    source_chapter_index: int | None = None
    is_public_baseline: bool = False


@dataclass(frozen=True)
class MergeResult:
    """合并结果 — candidate 合并到 target 的统计信息"""

    target_entity_id: str
    candidate_entity_id: str
    aliases_inherited: int = 0
    relations_migrated: int = 0
    relations_deduplicated: int = 0
    self_loops_cleaned: int = 0
    character_synced: bool = False
    conflicts_archived: int = 0


@dataclass(frozen=True)
class ResolveResult:
    """候选实体自动决议结果"""

    action: str  # "merged" | "promoted" | "needs_user_decision"
    merge_result: MergeResult | None = None
    promoted_entity_id: str | None = None
    suggestions: list = field(default_factory=list)


@dataclass(frozen=True)
class WorldBackgroundEntryContract:
    """Derived world fact suitable for deterministic context activation."""

    entry_id: str
    novel_id: str
    asset_type: str
    asset_id: str
    title: str
    summary: str
    group: str
    importance: float = 0.5
    tier: str = "P2"
    status: str = "canonical"
    sensitivity: str = "author_safe"
    keywords: list[str] = field(default_factory=list)
    source_ids: list[dict[str, str]] = field(default_factory=list)
    token_count: int = 0


@dataclass(frozen=True)
class WorldBackgroundBundleContract:
    """Read-only derived world background; it never owns canonical facts."""

    novel_id: str
    context_mode: str
    entries: list[WorldBackgroundEntryContract] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorldBibleSynopsisContextContract:
    """Author-only derived synopsis material exposed to Context."""

    novel_id: str
    included: bool
    content: str = ""
    revision_id: str | None = None
    source_hash: str = ""
    block_hash: str = ""
    token_count: int = 0
    stale: bool = True
    fallback: bool = False
    status: str = "missing"
    coverage: dict = field(default_factory=dict)
    omitted_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorldBibleActivationTargetContract:
    """Validated author-reference material returned to context activation."""

    novel_id: str
    target: dict[str, str]
    target_hash: str
    label: str
    status: str
    importance: float = 0.0
    content: str = ""
    token_count: int = 0
    source_kind: str = "explicit"
    source_version: int | None = None
    source_hash: str = ""
    linked_target_refs: list[dict[str, str]] = field(default_factory=list)
    expanded_from: dict[str, str] | None = None
    fallback: bool = False
    excluded_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorldBibleActivationResolutionContract:
    """Novel-scoped activation target resolution without exposing world ORM."""

    novel_id: str
    items: list[WorldBibleActivationTargetContract] = field(default_factory=list)
    excluded_items: list[WorldBibleActivationTargetContract] = field(default_factory=list)


class GenerationBackgroundProvider(Protocol):
    """DI port used by world generation without importing context internals."""

    async def __call__(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task: str,
        include_world_synopsis: bool = False,
        selected_world_bible_draft_ids: list[str] | None = None,
        activation_profile_id: str | None = None,
        activation_profile_version: int | None = None,
        operation: str = "world.generation.core_entity",
        prompt_name: str = "world.generation.core_entity.structured",
        model: str = "project-default",
        focus_text: str = "",
        reference_chapter_index: int | None = None,
        scene_id: str | None = None,
        thread_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        entity_ids: list[str] | None = None,
        source_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class WorldAliasRelationTaskPort(Protocol):
    """Task-only DI port; provider execution intentionally has no DB argument."""

    async def prepare_alias_relation_task(
        self,
        db: AsyncSession,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def execute_alias_relation_task(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    async def finalize_alias_relation_task(
        self,
        db: AsyncSession,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class MapObservationProposalBase(BaseModel):
    """Stable unresolved map proposal shared with deterministic import workflows."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    payload_kind: Literal["proposal"] = "proposal"
    schema_version: Literal[1] = 1


class MapCharacterLocationProposal(MapObservationProposalBase):
    proposal_type: Literal["character_location"]
    location_name: str | None = Field(None, max_length=255)
    movement_mode: Literal[
        "walk", "ride", "vehicle", "rail", "water", "flight", "teleport", "unknown"
    ] = "unknown"
    state: str = Field("present", min_length=1, max_length=64)


class MapEventLocationProposal(MapObservationProposalBase):
    proposal_type: Literal["event_location"]
    location_name: str | None = Field(None, max_length=255)
    state: str = Field("occurred", min_length=1, max_length=64)


class MapRouteStateProposal(MapObservationProposalBase):
    proposal_type: Literal["route_state"]
    path_name: str | None = Field(None, max_length=255)
    state: Literal["open", "restricted", "blocked"]
    reason: str | None = Field(None, max_length=1000)


class MapBoundaryProposal(MapObservationProposalBase):
    proposal_type: Literal["boundary"]
    controller_name: str | None = Field(None, max_length=255)
    area_description: str | None = Field(None, max_length=2000)


MapObservationProposalV1 = Annotated[
    MapCharacterLocationProposal
    | MapEventLocationProposal
    | MapRouteStateProposal
    | MapBoundaryProposal,
    Field(discriminator="proposal_type"),
]


class MapObservationCandidateAuthorizationScope(BaseModel):
    """Frozen user-authorization scope carried across the imports/world seam."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    novel_id: str
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)
    stage: str | None = Field(None, max_length=64)

    @field_validator("novel_id")
    @classmethod
    def _validate_novel_id(cls, value: str) -> str:
        import uuid

        return str(uuid.UUID(value))

    @model_validator(mode="after")
    def _validate_chapter_range(self) -> MapObservationCandidateAuthorizationScope:
        if self.end_chapter < self.start_chapter:
            raise ValueError("authorization end_chapter must not precede start_chapter")
        return self


class MapObservationCandidateAuthorization(BaseModel):
    """Persisted authorization proof for the non-autonomous import workflow."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    adoption_policy: Literal["user_authorized_pipeline"]
    authorization_confirmed: Literal[True]
    authorized_at: datetime
    scope: MapObservationCandidateAuthorizationScope
    snapshot_fingerprint: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class MapObservationCandidateInput(BaseModel):
    """Stable imports -> world input; provenance fields are immutable after creation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    workflow_id: str = Field(..., min_length=1, max_length=255)
    task_id: str | None = Field(None, max_length=255)
    source_item_key: str = Field(..., min_length=1, max_length=255)
    scene_id: str
    scene_index: int = Field(..., ge=0)
    source_chapter_index: int = Field(..., ge=0)
    scene_source_fingerprint: str = Field(..., min_length=1, max_length=255)
    context_snapshot_id: str | None = Field(None, max_length=255)
    evidence_text: str = Field(..., min_length=1, max_length=8000)
    evidence_anchor: str = Field(..., min_length=1, max_length=255)
    confidence: float = Field(..., ge=0.0, le=1.0)
    target_entity_id: str | None = None
    target_name: str | None = Field(None, max_length=255)
    proposal: MapObservationProposalV1
    authorization: MapObservationCandidateAuthorization

    @field_validator("scene_id", "target_entity_id")
    @classmethod
    def _validate_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        import uuid

        return str(uuid.UUID(value))


class MapObservationCandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    action: Literal["created", "reused"]
    proposal_type: Literal[
        "character_location", "event_location", "route_state", "boundary"
    ]
    payload_hash: str


class MapObservationCandidateBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_count: int = 0
    reused_count: int = 0
    items: list[MapObservationCandidateResult] = Field(default_factory=list)


__all__ = [
    "CharacterContract",
    "CharacterKnowledgeContract",
    "CoreEntityContract",
    "EntityRelationContract",
    "EntityRevisionContract",
    "EventContract",
    "GenerationBackgroundProvider",
    "MapBoundaryProposal",
    "MapCharacterLocationProposal",
    "MapEventLocationProposal",
    "MapObservationCandidateAuthorization",
    "MapObservationCandidateAuthorizationScope",
    "MapObservationCandidateBatchResult",
    "MapObservationCandidateInput",
    "MapObservationCandidateResult",
    "MapObservationProposalBase",
    "MapObservationProposalV1",
    "MapRouteStateProposal",
    "MergeResult",
    "ResolveResult",
    "WorldBackgroundBundleContract",
    "WorldBackgroundEntryContract",
    "WorldBibleActivationResolutionContract",
    "WorldBibleActivationTargetContract",
    "WorldBibleSynopsisContextContract",
    "WorldAliasRelationTaskPort",
]
