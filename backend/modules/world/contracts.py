"""
World 对外契约 — v3 因果时空网

定义其他模块可以安全依赖的世界模块接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from modules.world.schemas import RelationKind

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


ENTITY_FUSION_CHECKPOINT_PAIR_BATCH_SIZE = 12


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
class MapContinuityFactContract:
    """Adopted, source-validated spatial relation for continuity checks."""

    node_id: str
    revision_id: str
    revision_hash: str
    relation: str
    subject_entity_id: str
    target_entity_id: str
    via_entity_ids: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()


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
class WorldAuthorAttentionItemContract:
    """One safe, actionable World item for a project-level read model."""

    key: str
    source_kind: str
    title: str
    summary: str
    author_action: str
    severity: str
    target_kind: str
    item_id: str | None = None
    chapter_index: int | None = None
    scene_id: str | None = None
    page_id: str | None = None
    suggestion_id: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class WorldAttentionSummaryContract:
    """Author-facing review counts used by project-level workspace summaries."""

    novel_id: str
    world_objects: int = 0
    world_aliases: int = 0
    world_relations: int = 0
    items: tuple[WorldAuthorAttentionItemContract, ...] = ()

    @property
    def total(self) -> int:
        return self.world_objects + self.world_aliases + self.world_relations


@dataclass(frozen=True)
class PostImportSceneSourceContract:
    """Frozen Scene evidence supplied by imports at finalization."""

    scene_id: str
    source_hash: str
    range_start: int | None = None
    range_end: int | None = None
    entity_ids: tuple[str, ...] = ()
    relation_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PostImportWorldAdoptionRequestContract:
    novel_id: str
    workflow_id: str
    authorization_ref: str
    scene_sources: list[PostImportSceneSourceContract] = field(default_factory=list)


@dataclass(frozen=True)
class PostImportWorldAdoptionResultContract:
    suggestion_id: str
    created: bool
    suggestion_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FocusedWorldPackageRequest:
    novel_id: str
    authorization_id: str
    task_id: str
    task_type: str
    attempt: int
    lease_id: str
    items: list[dict]
    source_manifest_hash: str
    context_fingerprint: str
    roots: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class FocusedWorldPackageApplyRequest:
    novel_id: str
    authorization_id: str
    task_id: str
    task_type: str
    attempt: int
    lease_id: str
    suggestion_id: str
    expected_preview_hash: str
    validation_run_id: str | None = None


@dataclass(frozen=True)
class EntityRevisionContract:
    """版本快照契约

    `entity_revisions` 是实体改动历史（改动前快照，携带写作进度
    `writing_chapter_index` 与 `change_summary` 改动字段摘要）；
    `rollback-by-revision` 基于它把实体恢复到某次改动之前。
    按 Scene 的回滚在 `TextArchive` 可用时仍优先使用 TextArchive
    作为数据源，无归档时回退到本表。
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
    source_hash: str = ""
    token_count: int = 0


@dataclass(frozen=True)
class WorldBackgroundBundleContract:
    """Read-only derived world background; it never owns canonical facts."""

    novel_id: str
    context_mode: str
    entries: list[WorldBackgroundEntryContract] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KnowledgeVisibilityRequest:
    """一次批量可见性判定中的单个请求。

    character_id 为空表示读者主体；cutoff 语义为保守截止（当章不揭示）。
    """

    target_type: str
    target_id: str
    character_id: str | None = None
    cutoff_chapter: int | None = None
    cutoff_scene_id: str | None = None
    apply_reader_reveal: bool = True


@dataclass(frozen=True)
class KnowledgeVisibilityDecision:
    """服务端判定的生成者可见性；reasons 只含短原因，不含隐藏正文。"""

    target_type: str
    target_id: str
    visible: bool
    knowledge_level: str | None = None
    visibility_source: str = "public_default"
    has_reader_policy: bool = False
    reader_revealed: bool | None = None
    reasons: tuple[str, ...] = ()


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
        capture_snapshot: bool = True,
    ) -> dict[str, Any]: ...


# ============================================================
# 表格迁移（ADR-0030）— 作者在途项目资产迁移的 world 契约
# ============================================================


class AuthorNote(BaseModel):
    """未识别列转化的作者备注条目，追加到 hidden_truth。"""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=64)
    value: str = Field(max_length=20000)


CharacterFieldName = Literal[
    "role",
    "appearance",
    "personality",
    "desire",
    "fear",
    "weakness",
    "current_goal",
    "current_state",
    "stance",
    "voice_style",
    "relationship_summary",
]


class AuthorMigrationEntityInput(BaseModel):
    """一条待迁移的世界对象/人物条目。"""

    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    source_ref: str = Field(min_length=1, max_length=64)  # "<sheet_key>:r<row>"
    source_hash: str = Field(min_length=64, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=64)
    summary: str | None = Field(None, max_length=5000)
    public_info: str | None = Field(None, max_length=20000)
    hidden_truth: str | None = Field(None, max_length=20000)
    author_notes: list[AuthorNote] = Field(default_factory=list, max_length=64)
    character_fields: dict[CharacterFieldName, str] = Field(default_factory=dict)
    decision: Literal[
        "auto",
        "different_object",
        "use_existing",
        "append_note",
        "skip",
    ] = "auto"
    target_entity_id: str | None = Field(None, min_length=1, max_length=64)

    @field_validator("aliases")
    @classmethod
    def _validate_alias_lengths(cls, value: list[str]) -> list[str]:
        for alias in value:
            if len(alias) > 255:
                raise ValueError("单个别名不得超过 255 字")
        return value

    @model_validator(mode="after")
    def _validate_use_existing(self) -> AuthorMigrationEntityInput:
        if self.decision == "use_existing" and not self.target_entity_id:
            raise ValueError("decision=use_existing 时必须提供 target_entity_id")
        return self


class AuthorMigrationRelationInput(BaseModel):
    """一条待迁移的人物/对象关系。"""

    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    source_ref: str = Field(min_length=1, max_length=64)
    source_hash: str = Field(min_length=64, max_length=64)
    source_name: str = Field(min_length=1, max_length=255)
    target_name: str = Field(min_length=1, max_length=255)
    source_item_key: str | None = Field(None, pattern=r"^[a-z0-9_-]{1,64}$")
    target_item_key: str | None = Field(None, pattern=r"^[a-z0-9_-]{1,64}$")
    relation_type: str = Field(min_length=1, max_length=64)
    relation_kind: RelationKind | None = None
    description: str | None = Field(None, max_length=5000)
    symmetric: bool = False
    decision: Literal["auto", "skip"] = "auto"


class AuthorMigrationWorldRequest(BaseModel):
    """一次表格迁移的 world 落库请求。"""

    model_config = ConfigDict(extra="forbid")

    migration_id: str = Field(min_length=1, max_length=64)
    entities: list[AuthorMigrationEntityInput] = Field(max_length=1500)
    relations: list[AuthorMigrationRelationInput] = Field(max_length=3000)


class FieldConflict(BaseModel):
    """字段级冲突摘要；摘录 ≤200 字，不含完整正文。"""

    model_config = ConfigDict(extra="forbid")

    field: str
    current_excerpt: str = Field(default="", max_length=200)
    incoming_excerpt: str = Field(default="", max_length=200)


class WorldMigrationItemPlan(BaseModel):
    """单条条目的计划动作。"""

    model_config = ConfigDict(extra="forbid")

    item_key: str
    kind: Literal["entity", "relation"]
    action: Literal[
        "create",
        "fill_empty",
        "adopt_existing",
        "existing_ref",
        "conflict",
        "needs_review",
        "similar_name",
        "alias_collision",
        "skip",
    ]
    target_id: str | None = None
    target_label: str | None = None
    fills: list[str] = Field(default_factory=list)
    conflicts: list[FieldConflict] = Field(default_factory=list)
    similar: list[dict] = Field(default_factory=list)  # {entity_id, name, entity_type}
    relation_kind: RelationKind | None = None
    relation_kind_guessed: bool = False
    reason_code: str | None = Field(None, max_length=64)


class WorldMigrationPlan(BaseModel):
    """一次迁移的 world 计划（只读预览）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[WorldMigrationItemPlan] = Field(default_factory=list)
    validation_policy_active: bool = False
    fingerprint: str


class MigrationAppliedChange(BaseModel):
    """回滚比对用的变更记录；before 仅存被改字段原值（必为空值或状态）。"""

    model_config = ConfigDict(extra="forbid")

    item_key: str
    kind: str
    target_id: str
    operation: Literal[
        "create",
        "fill_empty",
        "promote",
        "alias",
        "relation_create",
        "relation_fill",
    ]
    before: dict = Field(default_factory=dict)
    after_hash: str


class WorldMigrationReceipt(BaseModel):
    """world apply 的回执。"""

    model_config = ConfigDict(extra="forbid")

    applied_changes: list[MigrationAppliedChange] = Field(default_factory=list)
    entity_ids: dict[str, str] = Field(default_factory=dict)  # item_key → id


class MigrationRollbackResult(BaseModel):
    """回滚判定结果；kept 携带保留原因。"""

    model_config = ConfigDict(extra="forbid")

    reverted: list[str] = Field(default_factory=list)
    kept: list[dict] = Field(default_factory=list)  # {item_key, reason_code}


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


__all__ = [
    "AuthorMigrationEntityInput",
    "AuthorMigrationRelationInput",
    "AuthorMigrationWorldRequest",
    "AuthorNote",
    "CharacterFieldName",
    "FieldConflict",
    "MigrationAppliedChange",
    "MigrationRollbackResult",
    "WorldMigrationItemPlan",
    "WorldMigrationPlan",
    "WorldMigrationReceipt",
    "FocusedWorldPackageRequest",
    "FocusedWorldPackageApplyRequest",
    "CharacterContract",
    "CharacterKnowledgeContract",
    "CoreEntityContract",
    "EntityRelationContract",
    "EntityRevisionContract",
    "EventContract",
    "GenerationBackgroundProvider",
    "KnowledgeVisibilityDecision",
    "KnowledgeVisibilityRequest",
    "MergeResult",
    "ResolveResult",
    "WorldBackgroundBundleContract",
    "WorldBackgroundEntryContract",
    "WorldAttentionSummaryContract",
    "WorldAuthorAttentionItemContract",
    "WorldBibleActivationResolutionContract",
    "WorldBibleActivationTargetContract",
    "WorldBibleSynopsisContextContract",
    "WorldAliasRelationTaskPort",
    "normalize_author_entity_type",
]


from modules.world.services.core.entity_types import (  # noqa: E402
    normalize_author_entity_type as normalize_author_entity_type,
)
