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
    from modules.evidence.confirmation_reads_port import ConfirmationReadsPort
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
ASSISTANT_EDITORIAL_POST_ADOPTION_RECHECKS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "assistant.editorial.post_adoption_rechecks"
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
#: 失效回执 → 作者语言 dict 投影（``consumption.receipt_public_view``；
#: writing 层不能 import evolution——依赖冻结集合无 writing→evolution 边，
#: C3 透传经此 DI 键由组合根注入。C2 已完成 bootstrap 注册与登记表补录）。
EVOLUTION_INVALIDATION_RECEIPT_VIEW: ServiceKey[Callable[..., Any]] = ServiceKey(
    "evolution.invalidation.receipt_view"
)

# --- imports ---------------------------------------------------------------

IMPORTS_GET_ACTIVE_ORGANIZATION: ServiceKey[Callable[..., Any]] = ServiceKey(
    "imports.get_active_organization"
)
IMPORTS_GET_REVIEW_DISPOSITIONS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "imports.get_review_dispositions"
)

CONTEXT_PURGE_PROJECT_INTERACTION_CACHE: ServiceKey[Callable[..., Any]] = ServiceKey(
    "context.purge_project_interaction_cache"
)

# --- interaction -----------------------------------------------------------

INTERACTION_READ_CONTINUITY_REVIEW: ServiceKey[Callable[..., Any]] = ServiceKey(
    "interaction.read_continuity_review"
)
INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT: ServiceKey[Callable[..., Any]] = (
    ServiceKey("interaction.validate_public_demo_source_context")
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

# --- evidence ---------------------------------------------------------------

EVIDENCE_CONFIRMATION_READS: ServiceKey[ConfirmationReadsPort] = ServiceKey(
    "evidence.confirmation_reads"
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
WORLD_READ_MAP_CHAPTER_CONSUMERS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.read_map_chapter_consumers"
)
WORLD_LIST_ADOPTED_MAP_CONTINUITY_FACTS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.list_adopted_map_continuity_facts"
)
WORLD_READ_MAP_NODE_HEADS: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.read_map_node_heads"
)
WORLD_STAGE_SPATIAL_DISCOVERY: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.stage_spatial_discovery"
)
WORLD_READ_SPATIAL_DISCOVERY_CONTEXT: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.read_spatial_discovery_context"
)
WORLD_READ_PROJECT_VOCABULARY: ServiceKey[Callable[..., Any]] = ServiceKey(
    "world.read_project_vocabulary"
