"""DI 键常量登记表（AO-10）。

组合根 ``app/bootstrap.py`` 注册的全部服务键在此逐字登记为
:class:`~core.container.ServiceKey` 常量：键名字符串是行为契约，常量
命名与键名一一对应（不改字符串本身）。生产代码消费依赖一律用常量
（``get(WORLD_LIST_ENTITIES)``），字符串键保留为过渡期兼容路径。

类型参数仅服务于静态检查与 IDE 导航，运行期零开销；领域类型走
``TYPE_CHECKING`` 导入，避免 core → modules 的运行期依赖。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core.container import ServiceKey

if TYPE_CHECKING:
    from modules.assistant.contracts import AssistantSessionPort
    from modules.collaboration.contracts import (
        CreativeResourcePort,
        ResourceSnapshot,
    )
    from modules.project.contracts import (
        StoryDedupSuggestionProvider,
        StoryWorkspaceStatsProvider,
        WorldDedupSuggestionProvider,
        WorldWorkspaceStatsProvider,
        WritingWorkspaceStatsProvider,
    )
    from modules.story.continuity.services import MemoryService
    from modules.story.outline_state.services import (
        ForeshadowingPlanService,
        OutlineArcService,
        PlotThreadService,
        RevealPlanService,
        SceneService,
    )
    from modules.story.scene_source_port import SceneSourcePort
    from modules.world.contracts import WorldAliasRelationTaskPort
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )
    from modules.writing.manuscript_source_port import ManuscriptSourcePort

# --- assistant -----------------------------------------------------------

ASSISTANT_FORECAST_INSTRUCTIONS: ServiceKey[dict[str, Any]] = ServiceKey(
    "assistant.forecast.instructions"
)
ASSISTANT_FORECAST_PERSONAS: ServiceKey[dict[str, Any]] = ServiceKey(
    "assistant.forecast.personas"
)
ASSISTANT_FORECAST_CHOICES: ServiceKey[dict[str, Any]] = ServiceKey(
    "assistant.forecast.choices"
)
ASSISTANT_FORECAST_SOURCES: ServiceKey[dict[str, Any]] = ServiceKey(
    "assistant.forecast.sources"
)
ASSISTANT_OPERATIONS: ServiceKey[dict[str, Any]] = ServiceKey("assistant.operations")
SOURCE_CHANGED: ServiceKey[Callable[..., Any]] = ServiceKey("source.changed")
ASSISTANT_PROACTIVE_SUBMITTERS: ServiceKey[dict[str, Callable[..., Any]]] = ServiceKey(
    "assistant.proactive.submitters"
)
ASSISTANT_PROACTIVE_FINDINGS: ServiceKey[dict[str, Callable[..., Any]]] = ServiceKey(
    "assistant.proactive.findings"
)
ASSISTANT_SESSION_SERVICE: ServiceKey[AssistantSessionPort] = ServiceKey(
    "assistant.session_service"
)
ASSISTANT_MARK_TASK_LOCAL_APPROVED: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.mark_task_local_approved"
)
ASSISTANT_INSPECT_DISCUSSION: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.inspect_discussion"
)
ASSISTANT_SUBMIT_COMMENT_PROPOSALS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.submit_comment_proposals"
)
ASSISTANT_MARK_EDITORIAL_READY: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.mark_editorial_ready"
)
ASSISTANT_RUN_DISCUSSION_SCOPE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.run_discussion_scope"
)
ASSISTANT_REQUIRE_OPERATION_TARGETS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.require_operation_targets"
)

# --- collaboration -------------------------------------------------------

COLLABORATION_RESOURCES: ServiceKey[dict[str, Any]] = ServiceKey(
    "collaboration.resources"
)
COLLABORATION_COLLECT_FORECAST_UNDERSTANDING: ServiceKey[Callable[..., Any]] = ServiceKey(
    "collaboration.collect_forecast_understanding"
)
COLLABORATION_CHANGED_CASES: ServiceKey[Callable[..., Any]] = ServiceKey(
    "collaboration.changed_cases"
)
COLLABORATION_SUBMIT_CHANGED_CASE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "collaboration.submit_changed_case"
)
COLLABORATION_STOP_UNAVAILABLE_RUNS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "collaboration.stop_unavailable_runs"
)
COLLABORATION_READ_PROJECTED_RUN: ServiceKey[Callable[..., Any]] = ServiceKey(
    "collaboration.read_projected_run"
)
# 键名为驼峰（历史契约），常量按语义转蛇形。
COLLABORATION_RESOURCE_SNAPSHOT: ServiceKey[type[ResourceSnapshot]] = ServiceKey(
    "collaboration.ResourceSnapshot"
)
COLLABORATION_CREATIVE_RESOURCE_PORT: ServiceKey[type[CreativeResourcePort]] = ServiceKey(
    "collaboration.CreativeResourcePort"
)

# --- context -------------------------------------------------------------

CONTEXT_COMPILE: ServiceKey[Callable[..., Any]] = ServiceKey("context.compile")
CONTEXT_GENERATION_BACKGROUND: ServiceKey[Callable[..., Any]] = ServiceKey(
    "context.generation_background"
)

# --- evolution -----------------------------------------------------------

EVOLUTION_REQUIRE_CURRENT_WORLD_CANDIDATE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "evolution.require_current_world_candidate"
)
EVOLUTION_RECORD_WRITING_SOURCE_CHANGE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "evolution.record_writing_source_change"
)

# --- imports ---------------------------------------------------------------

IMPORTS_GET_ACTIVE_ORGANIZATION: ServiceKey[Callable[..., Any]] = ServiceKey(
    "imports.get_active_organization"
)
IMPORTS_GET_REVIEW_DISPOSITIONS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "imports.get_review_dispositions"
)

# --- interaction -----------------------------------------------------------

INTERACTION_READ_CONTINUITY_REVIEW: ServiceKey[Callable[..., Any]] = ServiceKey(
    "interaction.read_continuity_review"
)
INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT: ServiceKey[Callable[..., Any]] = (
    ServiceKey("interaction.validate_public_demo_source_context")
)
INTERACTION_MARK_TASK_LOCAL_APPROVED: ServiceKey[Callable[..., Any]] = ServiceKey(
    "interaction.mark_task_local_approved"
)
INTERACTION_COUNT_SOURCE_REFERENCES: ServiceKey[Callable[..., Any]] = ServiceKey(
    "interaction.count_source_references"
)

# --- account ----------------------------------------------------------------

ACCOUNT_PROJECT_OWNER_REF: ServiceKey[Callable[..., Any]] = ServiceKey(
    "account.project_owner_ref"
)
ACCOUNT_PROJECT_CONTEXT: ServiceKey[Callable[..., Any]] = ServiceKey(
    "account.project_context"
)
ACCOUNT_PROJECT_IDS_FOR_OWNER: ServiceKey[Callable[..., Any]] = ServiceKey(
    "account.project_ids_for_owner"
)
ACCOUNT_PROJECT_PURGE_FOR_OWNER: ServiceKey[Callable[..., Any]] = ServiceKey(
    "account.project_purge_for_owner"
)

# --- memory -----------------------------------------------------------------

MEMORY_SERVICE: ServiceKey[MemoryService] = ServiceKey("memory.service")

# --- outline ----------------------------------------------------------------

OUTLINE_GENERATE_STRUCTURE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "outline.generate_structure"
)
OUTLINE_ARC_SERVICE: ServiceKey[OutlineArcService] = ServiceKey("outline.arc_service")
OUTLINE_THREAD_SERVICE: ServiceKey[PlotThreadService] = ServiceKey(
    "outline.thread_service"
)
OUTLINE_SCENE_SERVICE: ServiceKey[SceneService] = ServiceKey("outline.scene_service")
OUTLINE_FORESHADOWING_SERVICE: ServiceKey[ForeshadowingPlanService] = ServiceKey(
    "outline.foreshadowing_service"
)
OUTLINE_REVEAL_SERVICE: ServiceKey[RevealPlanService] = ServiceKey(
    "outline.reveal_service"
)

# --- project ----------------------------------------------------------------

PROJECT_REQUIRE_ACTIVE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "project.require_active"
)
PROJECT_WORKSPACE_WRITING_STATS: ServiceKey[WritingWorkspaceStatsProvider] = ServiceKey(
    "project.workspace.writing_stats"
)
PROJECT_WORKSPACE_WORLD_STATS: ServiceKey[WorldWorkspaceStatsProvider] = ServiceKey(
    "project.workspace.world_stats"
)
PROJECT_WORKSPACE_STORY_STATS: ServiceKey[StoryWorkspaceStatsProvider] = ServiceKey(
    "project.workspace.story_stats"
)
PROJECT_DEDUP_WORLD: ServiceKey[WorldDedupSuggestionProvider] = ServiceKey(
    "project.dedup.world"
)
PROJECT_DEDUP_STORY: ServiceKey[StoryDedupSuggestionProvider] = ServiceKey(
    "project.dedup.story"
)

# --- rag（evidence 索引；键名前缀为历史契约，不改字符串） ----------------

RAG_INDEX_CHAPTER: ServiceKey[Callable[..., Any]] = ServiceKey("rag.index_chapter")
RAG_INDEX_CHAPTER_FOR_TASK: ServiceKey[Callable[..., Any]] = ServiceKey(
    "rag.index_chapter_for_task"
)
RAG_GET_ORDERED_CHAPTER_CHUNKS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "rag.get_ordered_chapter_chunks"
)
RAG_GET_ENTITY_ACTIVITY_STATS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "rag.get_entity_activity_stats"
)
RAG_REQUEST_ENTITY_ACTIVITY_REANNOTATION: ServiceKey[Callable[..., Any]] = ServiceKey(
    "rag.request_entity_activity_reannotation"
)

# --- story ------------------------------------------------------------------

STORY_GET_SCENE_CONTRACT: ServiceKey[Callable[..., Any]] = ServiceKey(
    "story.get_scene_contract"
)
STORY_SCENE_SOURCE: ServiceKey[SceneSourcePort] = ServiceKey("story.scene_source")

# --- world ------------------------------------------------------------------

WORLD_MAP_CAPABILITIES: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.map_capabilities"
)
WORLD_REVIEW_TEAM_STRESS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.review_team_stress"
)
WORLD_LIST_ADOPTED_MAP_CONTINUITY_FACTS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.list_adopted_map_continuity_facts"
)
WORLD_WORLDBUILDING_REQUIRE_LEGACY_CANON_WRITE_ALLOWED: ServiceKey[Callable[..., Any]] = (
    ServiceKey("world.worldbuilding.require_legacy_canon_write_allowed")
)
WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED: ServiceKey[Callable[..., Any]] = (
    ServiceKey("world.worldbuilding.mark_synopsis_source_changed")
)
WORLD_WORLDBUILDING_FOCUSED_ADOPTION_AUTHORIZE: ServiceKey[Callable[..., Any]] = (
    ServiceKey("world.worldbuilding.focused_adoption.authorize")
)
WORLD_WORLDBUILDING_FOCUSED_ADOPTION_CHECK_SOURCES: ServiceKey[Callable[..., Any]] = (
    ServiceKey("world.worldbuilding.focused_adoption.check_sources")
)
WORLD_WORLDBUILDING_FOCUSED_ADOPTION_FENCE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.worldbuilding.focused_adoption.fence"
)
WORLD_WORLDBUILDING_ADOPTION_PACKAGE_SERVICE: ServiceKey[
    type[WorldAdoptionPackageService]
] = ServiceKey("world.worldbuilding.adoption_package_service")
WORLD_ASSISTANT_REQUIRE_SOURCE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.assistant.require_source"
)
WORLD_ASSISTANT_REQUIRE_CHECKPOINT: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.assistant.require_checkpoint"
)
WORLD_ASSISTANT_OUTCOME_STATES: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.assistant.outcome_states"
)
WORLD_ASSISTANT_CHAT: ServiceKey[Callable[..., Any]] = ServiceKey("world.assistant.chat")
WORLD_ASSISTANT_CHAT_INTENT: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.assistant.chat_intent"
)
WORLD_LIST_CHARACTERS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.list_characters"
)
WORLD_LIST_ENTITY_TERMS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.list_entity_terms"
)
WORLD_LIST_ENTITIES: ServiceKey[Callable[..., Any]] = ServiceKey("world.list_entities")
WORLD_RUN_SCENE_ENTITY_EXTRACTION: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.run_scene_entity_extraction"
)
# 注册值为 SceneEntityExtractionService 实例（非单函数，历史键名不改）。
WORLD_RUN_ALIAS_RELATION_EXTRACTION: ServiceKey[WorldAliasRelationTaskPort] = ServiceKey(
    "world.run_alias_relation_extraction"
)
WORLD_CREATE_CHARACTER: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.create_character"
)
WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.get_character_id_by_world_entity"
)
WORLD_ENQUEUE_MAP_ATLAS_CLEANUP: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.enqueue_map_atlas_cleanup"
)

# --- writing ----------------------------------------------------------------

WRITING_LIST_CHAPTER_INDICES: ServiceKey[Callable[..., Any]] = ServiceKey(
    "writing.list_chapter_indices"
)
WRITING_LIST_EFFECTIVE_CHAPTER_INDICES: ServiceKey[Callable[..., Any]] = ServiceKey(
    "writing.list_effective_chapter_indices"
)
WRITING_GET_LATEST_DRAFT_FOR_CHAPTER: ServiceKey[Callable[..., Any]] = ServiceKey(
    "writing.get_latest_draft_for_chapter"
)
WRITING_LIST_LATEST_DRAFTS_FOR_CHAPTERS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "writing.list_latest_drafts_for_chapters"
)
WRITING_MANUSCRIPT_SOURCE: ServiceKey[ManuscriptSourcePort] = ServiceKey(
    "writing.manuscript_source"
)

#: 组合根登记的全部键（与 ``app/bootstrap.py`` 一一对应）。
ALL_SERVICE_KEYS: tuple[ServiceKey[Any], ...] = (
    ASSISTANT_FORECAST_INSTRUCTIONS,
    ASSISTANT_FORECAST_PERSONAS,
    ASSISTANT_FORECAST_CHOICES,
    ASSISTANT_FORECAST_SOURCES,
    ASSISTANT_OPERATIONS,
    SOURCE_CHANGED,
    ASSISTANT_PROACTIVE_SUBMITTERS,
    ASSISTANT_PROACTIVE_FINDINGS,
    ASSISTANT_SESSION_SERVICE,
    ASSISTANT_MARK_TASK_LOCAL_APPROVED,
    ASSISTANT_INSPECT_DISCUSSION,
    ASSISTANT_SUBMIT_COMMENT_PROPOSALS,
    ASSISTANT_MARK_EDITORIAL_READY,
    ASSISTANT_RUN_DISCUSSION_SCOPE,
    ASSISTANT_REQUIRE_OPERATION_TARGETS,
    COLLABORATION_RESOURCES,
    COLLABORATION_COLLECT_FORECAST_UNDERSTANDING,
    COLLABORATION_CHANGED_CASES,
    COLLABORATION_SUBMIT_CHANGED_CASE,
    COLLABORATION_STOP_UNAVAILABLE_RUNS,
    COLLABORATION_READ_PROJECTED_RUN,
    COLLABORATION_RESOURCE_SNAPSHOT,
    COLLABORATION_CREATIVE_RESOURCE_PORT,
    CONTEXT_COMPILE,
    CONTEXT_GENERATION_BACKGROUND,
    EVOLUTION_REQUIRE_CURRENT_WORLD_CANDIDATE,
    EVOLUTION_RECORD_WRITING_SOURCE_CHANGE,
    IMPORTS_GET_ACTIVE_ORGANIZATION,
    IMPORTS_GET_REVIEW_DISPOSITIONS,
    INTERACTION_READ_CONTINUITY_REVIEW,
    INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT,
    INTERACTION_MARK_TASK_LOCAL_APPROVED,
    INTERACTION_COUNT_SOURCE_REFERENCES,
    ACCOUNT_PROJECT_OWNER_REF,
    ACCOUNT_PROJECT_CONTEXT,
    ACCOUNT_PROJECT_IDS_FOR_OWNER,
    ACCOUNT_PROJECT_PURGE_FOR_OWNER,
    MEMORY_SERVICE,
    OUTLINE_GENERATE_STRUCTURE,
    OUTLINE_ARC_SERVICE,
    OUTLINE_THREAD_SERVICE,
    OUTLINE_SCENE_SERVICE,
    OUTLINE_FORESHADOWING_SERVICE,
    OUTLINE_REVEAL_SERVICE,
    PROJECT_REQUIRE_ACTIVE,
    PROJECT_WORKSPACE_WRITING_STATS,
    PROJECT_WORKSPACE_WORLD_STATS,
    PROJECT_WORKSPACE_STORY_STATS,
    PROJECT_DEDUP_WORLD,
    PROJECT_DEDUP_STORY,
    RAG_INDEX_CHAPTER,
    RAG_INDEX_CHAPTER_FOR_TASK,
    RAG_GET_ORDERED_CHAPTER_CHUNKS,
    RAG_GET_ENTITY_ACTIVITY_STATS,
    RAG_REQUEST_ENTITY_ACTIVITY_REANNOTATION,
    STORY_GET_SCENE_CONTRACT,
    STORY_SCENE_SOURCE,
    WORLD_MAP_CAPABILITIES,
    WORLD_REVIEW_TEAM_STRESS,
    WORLD_LIST_ADOPTED_MAP_CONTINUITY_FACTS,
    WORLD_WORLDBUILDING_REQUIRE_LEGACY_CANON_WRITE_ALLOWED,
    WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED,
    WORLD_WORLDBUILDING_FOCUSED_ADOPTION_AUTHORIZE,
    WORLD_WORLDBUILDING_FOCUSED_ADOPTION_CHECK_SOURCES,
    WORLD_WORLDBUILDING_FOCUSED_ADOPTION_FENCE,
    WORLD_WORLDBUILDING_ADOPTION_PACKAGE_SERVICE,
    WORLD_ASSISTANT_REQUIRE_SOURCE,
    WORLD_ASSISTANT_REQUIRE_CHECKPOINT,
    WORLD_ASSISTANT_OUTCOME_STATES,
    WORLD_ASSISTANT_CHAT,
    WORLD_ASSISTANT_CHAT_INTENT,
    WORLD_LIST_CHARACTERS,
    WORLD_LIST_ENTITY_TERMS,
    WORLD_LIST_ENTITIES,
    WORLD_RUN_SCENE_ENTITY_EXTRACTION,
    WORLD_RUN_ALIAS_RELATION_EXTRACTION,
    WORLD_CREATE_CHARACTER,
    WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY,
    WORLD_ENQUEUE_MAP_ATLAS_CLEANUP,
    WRITING_LIST_CHAPTER_INDICES,
    WRITING_LIST_EFFECTIVE_CHAPTER_INDICES,
    WRITING_GET_LATEST_DRAFT_FOR_CHAPTER,
    WRITING_LIST_LATEST_DRAFTS_FOR_CHAPTERS,
    WRITING_MANUSCRIPT_SOURCE,
)

#: 条件注册键豁免登记：键名 → 未由组合根无条件注册的理由。
#: 现状为空：全部键都在 ``register_container_services()`` 无条件注册，
#: worker/eval 入口以 ``ignore_existing=True`` 复跑装配同样覆盖全部键。
#: 新增按环境条件注册的键时，在此登记键名与理由，启动校验即豁免。
CONDITIONALLY_REGISTERED: dict[str, str] = {}
