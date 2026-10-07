"""Application composition root for DI container registration."""
# ruff: noqa: I001

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.container import ServiceKey
from core.container import ensure_registered, get as _get
from core.container import register as _register
from core.service_keys import (
    ALL_SERVICE_KEYS,
    CONDITIONALLY_REGISTERED,
    ACCOUNT_PROJECT_CONTEXT,
    ACCOUNT_PROJECT_IDS_FOR_OWNER,
    ACCOUNT_PROJECT_OWNER_REF,
    ACCOUNT_PROJECT_PURGE_FOR_OWNER,
    ASSISTANT_FORECAST_CHOICES,
    ASSISTANT_FORECAST_INSTRUCTIONS,
    ASSISTANT_FORECAST_PERSONAS,
    ASSISTANT_FORECAST_SOURCES,
    ASSISTANT_INSPECT_DISCUSSION,
    ASSISTANT_MARK_EDITORIAL_READY,
    ASSISTANT_MARK_TASK_LOCAL_APPROVED,
    ASSISTANT_OPERATIONS,
    ASSISTANT_PROACTIVE_FINDINGS,
    ASSISTANT_PROACTIVE_SUBMITTERS,
    ASSISTANT_REQUIRE_OPERATION_TARGETS,
    ASSISTANT_RUN_DISCUSSION_SCOPE,
    ASSISTANT_SESSION_SERVICE,
    ASSISTANT_SUBMIT_COMMENT_PROPOSALS,
    COLLABORATION_CHANGED_CASES,
    COLLABORATION_COLLECT_FORECAST_UNDERSTANDING,
    COLLABORATION_CREATIVE_RESOURCE_PORT,
    COLLABORATION_READ_PROJECTED_RUN,
    COLLABORATION_RESOURCES,
    COLLABORATION_RESOURCE_SNAPSHOT,
    COLLABORATION_STOP_UNAVAILABLE_RUNS,
    COLLABORATION_SUBMIT_CHANGED_CASE,
    CONTEXT_COMPILE,
    CONTEXT_GENERATION_BACKGROUND,
    EVOLUTION_RECORD_WRITING_SOURCE_CHANGE,
    EVOLUTION_REQUIRE_CURRENT_WORLD_CANDIDATE,
    IMPORTS_GET_ACTIVE_ORGANIZATION,
    IMPORTS_GET_REVIEW_DISPOSITIONS,
    INTERACTION_COUNT_SOURCE_REFERENCES,
    INTERACTION_MARK_TASK_LOCAL_APPROVED,
    INTERACTION_READ_CONTINUITY_REVIEW,
    INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT,
    MEMORY_SERVICE,
    OUTLINE_ARC_SERVICE,
    OUTLINE_FORESHADOWING_SERVICE,
    OUTLINE_GENERATE_STRUCTURE,
    OUTLINE_REVEAL_SERVICE,
    OUTLINE_SCENE_SERVICE,
    OUTLINE_THREAD_SERVICE,
    PROJECT_DEDUP_STORY,
    PROJECT_DEDUP_WORLD,
    PROJECT_REQUIRE_ACTIVE,
    PROJECT_WORKSPACE_STORY_STATS,
    PROJECT_WORKSPACE_WORLD_STATS,
    PROJECT_WORKSPACE_WRITING_STATS,
    RAG_GET_ENTITY_ACTIVITY_STATS,
    RAG_GET_ORDERED_CHAPTER_CHUNKS,
    RAG_INDEX_CHAPTER,
    RAG_INDEX_CHAPTER_FOR_TASK,
    RAG_REQUEST_ENTITY_ACTIVITY_REANNOTATION,
    SOURCE_CHANGED,
    STORY_GET_SCENE_CONTRACT,
    STORY_SCENE_SOURCE,
    WORLD_ASSISTANT_CHAT,
    WORLD_ASSISTANT_CHAT_INTENT,
    WORLD_ASSISTANT_OUTCOME_STATES,
    WORLD_ASSISTANT_REQUIRE_CHECKPOINT,
    WORLD_ASSISTANT_REQUIRE_SOURCE,
    WORLD_CREATE_CHARACTER,
    WORLD_ENQUEUE_MAP_ATLAS_CLEANUP,
    WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY,
    WORLD_LIST_ADOPTED_MAP_CONTINUITY_FACTS,
    WORLD_LIST_CHARACTERS,
    WORLD_LIST_ENTITIES,
    WORLD_LIST_ENTITY_TERMS,
    WORLD_MAP_CAPABILITIES,
    WORLD_REVIEW_TEAM_STRESS,
    WORLD_RUN_ALIAS_RELATION_EXTRACTION,
    WORLD_RUN_SCENE_ENTITY_EXTRACTION,
    WORLD_WORLDBUILDING_ADOPTION_PACKAGE_SERVICE,
    WORLD_WORLDBUILDING_FOCUSED_ADOPTION_AUTHORIZE,
    WORLD_WORLDBUILDING_FOCUSED_ADOPTION_CHECK_SOURCES,
    WORLD_WORLDBUILDING_FOCUSED_ADOPTION_FENCE,
    WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED,
    WORLD_WORLDBUILDING_REQUIRE_LEGACY_CANON_WRITE_ALLOWED,
    WRITING_GET_LATEST_DRAFT_FOR_CHAPTER,
    WRITING_LIST_CHAPTER_INDICES,
    WRITING_LIST_EFFECTIVE_CHAPTER_INDICES,
    WRITING_LIST_LATEST_DRAFTS_FOR_CHAPTERS,
    WRITING_MANUSCRIPT_SOURCE,
)
from modules.evidence.facade import compile_structure_context as _ctx_compile
from modules.evidence.facade import (
    compile_generation_background as _ctx_generation_background,
)
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService as _SceneExtractSvc,
)
from modules.interaction.facade import (
    count_source_project_references as _interaction_source_reference_count,
)
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotStructureGenerator,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from modules.evidence.facade import (
    get_entity_activity_stats as _rag_get_entity_activity_stats,
    get_ordered_chapter_chunks as _rag_get_chunks,
    index_chapter_with_report as _rag_index,
    request_entity_activity_reannotation as _rag_request_entity_reannotation,
)
from modules.evidence.indexing.indexing import IndexingService as _RagIndexingService
from modules.project.facade import (
    get_project_context as _project_context,
    get_project_owner_ref as _project_owner_ref,
    list_project_ids_for_owner as _project_list_ids_for_owner,
    purge_projects_for_owner as _project_purge_for_owner,
)
from modules.project.facade import require_active_project as _project_require_active
from modules.story.project_ports import (
    StoryDedupAdapter as _StoryDedupAdapter,
)
from modules.story.project_ports import (
    StoryWorkspaceStatsAdapter as _StoryWorkspaceStatsAdapter,
)
from modules.writing.facade import (
    get_latest_draft_for_chapter as _writing_get_draft,
    list_chapter_indices as _writing_list_indices,
    list_effective_chapter_indices as _writing_list_effective_indices,
    list_latest_drafts_for_chapters as _writing_list_latest_drafts,
)
from modules.writing.project_ports import (
    WritingWorkspaceStatsAdapter as _WritingWorkspaceStatsAdapter,
)
from modules.world.facade import (
    create_character as _world_create_char,
    get_character_id_by_world_entity as _world_get_char_id,
    list_characters as _world_list_characters,
    list_entities as _world_list_entities,
    list_entity_terms as _world_list_entity_terms,
    review_team_stress as _world_review_team_stress,
)
from modules.world.project_ports import (
    WorldDedupAdapter as _WorldDedupAdapter,
)
from modules.world.project_ports import (
    WorldWorkspaceStatsAdapter as _WorldWorkspaceStatsAdapter,
)
from modules.world.map_atlas_facade import (
    enqueue_map_atlas_project_cleanup as _map_atlas_cleanup,
    list_adopted_map_continuity_facts as _world_list_map_continuity_facts,
    map_capabilities as _world_map_capabilities,
)
from modules.imports.facade import (
    get_active_organization as _imports_get_active_organization,
    get_review_dispositions as _imports_get_review_dispositions,
)
from modules.interaction.facade import (
    read_continuity_review as _interaction_read_continuity_review,
)
from modules.interaction.facade import (
    validate_public_demo_source_context as _interaction_validate_demo_context,
)
from modules.evolution.facade import (
    record_writing_source_change as _evolution_record_writing_source_change,
    require_current_world_candidate as _evolution_require_current_world_candidate,
)
from modules.story.facade import get_scene_contract as _story_get_scene_contract
from modules.world import assistant_ports as _world_assistant
from modules.world.assistant_tools import OPERATIONS as _WORLD_OPERATIONS
from app.assistant_operation_registry import evidence_forecast_operations
from app.assistant_operation_registry import project_dedup_operations
from app.assistant_operation_registry import project_operations
from app.assistant_operation_registry import story_information_operations
from app.assistant_operation_registry import story_operations
from app.assistant_operation_registry import story_planning_operations
from app.assistant_operation_registry import story_structure_operations
from app.assistant_operation_registry import writing_candidate_operations
from app.assistant_operation_registry import writing_generation_operations
from app.assistant_operation_registry import writing_operations
from modules.world.assistant_page_tools import OPERATIONS as _WORLD_PAGE_OPERATIONS
from modules.world.assistant_outcome_tools import OPERATIONS as _WORLD_OUTCOME_OPERATIONS
from modules.world.assistant_cocreation_tools import (
    OPERATIONS as _WORLD_COCREATION_OPERATIONS,
)
from modules.story.proactive import schedule_proactive_review as _story_proactive_review
from modules.imports.assistant_tools import OPERATIONS as _IMPORTS_OPERATIONS
from modules.imports.assistant_tools import (
    schedule_proactive_review as _imports_proactive_review,
)
from modules.world.assistant_map_tools import OPERATIONS as _MAP_OPERATIONS
from modules.world.assistant_review_tools import OPERATIONS as _WORLD_REVIEW_OPERATIONS
from modules.world.assistant_review_tools import (
    schedule_proactive_review as _world_proactive_review,
    review_findings as _world_review_findings,
)
from modules.writing.assistant_tools import (
    schedule_proactive_review as _writing_proactive_review,
)
from modules.assistant.facade import mark_changed as _assistant_mark_changed
from modules.collaboration.facade import (
    changed_cases as _collab_changed_cases,
    collect_forecast_understanding as _collab_collect_forecast_understanding,
    read_projected_run as _collab_read_projected_run,
    stop_unavailable_runs as _collab_stop_unavailable_runs,
    submit_changed_case as _collab_submit_changed_case,
)
from modules.assistant.facade import (
    inspect_discussion as _assistant_inspect_discussion,
    mark_editorial_ready as _assistant_mark_editorial_ready,
    mark_task_local_approved as _assistant_mark_task_local_approved,
    submit_comment_proposals as _assistant_submit_comment_proposals,
)
from modules.assistant.facade import (
    run_discussion_scope as _assistant_run_discussion_scope,
)
from modules.assistant.operation_scope import (
    require_operation_targets as _assistant_require_operation_targets,
)
from modules.assistant.sessions import AssistantSessionService as _AssistantSessions
from modules.interaction.facade import (
    mark_task_local_approved as _interaction_mark_task_local_approved,
)
from modules.story.scene_source_port import SceneSourcePort as _StorySceneSource
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService as _WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.focused_adoption import (
    authorize as _world_focused_authorize,
)
from modules.world.services.worldbuilding.focused_adoption import (
    check_sources as _world_focused_check_sources,
)
from modules.world.services.worldbuilding.focused_adoption import (
    fence as _world_focused_fence,
)
from modules.world.services.worldbuilding.synopsis_invalidation import (
    mark_synopsis_source_changed as _world_mark_synopsis_source_changed,
)
from modules.world.services.worldbuilding.world_validation_service import (
    WorldValidationService as _WorldValidationService,
)
from modules.writing.manuscript_source_port import (
    ManuscriptSourcePort as _WritingManuscriptSource,
)
from modules.interaction.proactive import (
    schedule_proactive_review as _interaction_proactive_review,
)


def _register_orm_models() -> None:
    """Import ORM models with Base.metadata for FK dependency resolution."""
    import modules.account.models  # noqa: F401, I001
    import modules.assistant.models  # noqa: F401, E402
    import modules.assistant.forecast.models  # noqa: F401, E402
    import modules.collaboration.models  # noqa: F401, E402
    import modules.account.settings_models  # noqa: F401, I001
    import modules.evidence.models  # noqa: F401, I001
    import modules.evolution.models  # noqa: F401, I001
    import modules.imports.models  # noqa: F401, I001
    import modules.interaction.models  # noqa: F401, I001
    import modules.local_agent.models  # noqa: F401, I001
    import modules.project.models  # noqa: F401, I001
    import modules.story.models  # noqa: F401, I001
    import modules.story.continuity.models  # noqa: F401, I001
    import modules.story.outline_state.models  # noqa: F401, I001
    import modules.project.settings_models  # noqa: F401, I001
    import modules.world.map_atlas_models  # noqa: F401, I001
    import modules.world.models  # noqa: F401, I001


def _container_services() -> Iterable[tuple[ServiceKey[Any], Any]]:
    """Build app/worker process-singleton service registrations."""
    scene_extraction = _SceneExtractSvc()
    memory = MemoryService()
    rag_indexing = _RagIndexingService()
    from modules.writing.creative import port as _writing_creative_port
    from modules.story.creative import ports as story_creative
    from modules.world.creative import port as _world_creative_port
    from modules.writing import forecast as writing_forecast
    from modules.story import forecast as story_forecast
    from modules.world import forecast as world_forecast
    from modules.evidence import forecast as evidence_forecast
    from modules.imports import forecast as imports_forecast
    from modules.project import forecast as project_forecast
    from modules.account import forecast as account_forecast
    from modules.interaction import forecast as interaction_forecast
    from modules.assistant.forecast import domain as assistant_forecast

    return (
        (
            ASSISTANT_FORECAST_INSTRUCTIONS,
            {
                **writing_forecast.INSTRUCTIONS,
                **story_forecast.INSTRUCTIONS,
                **world_forecast.INSTRUCTIONS,
                **evidence_forecast.INSTRUCTIONS,
                **assistant_forecast.INSTRUCTIONS,
                **interaction_forecast.INSTRUCTIONS,
            },
        ),
        (
            ASSISTANT_FORECAST_PERSONAS,
            {
                "rp": {
                    "authorize": interaction_forecast.authorize,
                    "materialize": interaction_forecast.materialize,
                }
            },
        ),
        (
            ASSISTANT_FORECAST_CHOICES,
            {
                "world": world_forecast.prepare_direction,
                "evidence": evidence_forecast.prepare_direction,
            },
        ),
        (
            ASSISTANT_FORECAST_SOURCES,
            {
                "writing": writing_forecast.inspect,
                "story": story_forecast.inspect,
                "world": world_forecast.inspect,
                "evidence": evidence_forecast.inspect,
                "imports": imports_forecast.inspect,
                "project": project_forecast.inspect,
                "account": account_forecast.inspect,
                "assistant": assistant_forecast.inspect,
            },
        ),
        (
            COLLABORATION_RESOURCES,
            {
                "writing_draft": _writing_creative_port(),
                "world_bible_draft": _world_creative_port(),
                **story_creative(),
            },
        ),
        (
            ASSISTANT_OPERATIONS,
            {
                **_WORLD_OPERATIONS,
                **project_dedup_operations,
                **story_information_operations,
                **_WORLD_PAGE_OPERATIONS,
                **_WORLD_OUTCOME_OPERATIONS,
                **_WORLD_COCREATION_OPERATIONS,
                **writing_operations,
                **writing_generation_operations,
                **writing_candidate_operations,
                **project_operations,
                **story_operations,
                **story_structure_operations,
                **story_planning_operations,
                **_IMPORTS_OPERATIONS,
                **evidence_forecast_operations,
                **_MAP_OPERATIONS,
                **_WORLD_REVIEW_OPERATIONS,
            },
        ),
        (SOURCE_CHANGED, _assistant_mark_changed),
        (
            ASSISTANT_PROACTIVE_SUBMITTERS,
            {
                "writing": _writing_proactive_review,
                "world": _world_proactive_review,
                "interaction": _interaction_proactive_review,
                "imports": _imports_proactive_review,
                "story": _story_proactive_review,
            },
        ),
        (ASSISTANT_PROACTIVE_FINDINGS, {"world_validation": _world_review_findings}),
        (ASSISTANT_SESSION_SERVICE, _AssistantSessions()),
        # AO-5: assistant forecast 消费 collaboration 理解包经此 DI port，
        # assistant→collaboration 保持零顶层导入（collaboration→assistant
        # 为该对的既有顶层方向）。
        (
            COLLABORATION_COLLECT_FORECAST_UNDERSTANDING,
            _collab_collect_forecast_understanding,
        ),
        # AO-5 第三批：assistant 消费 collaboration/world/imports/interaction
        # facade 能力经这些 DI 键，四个反方向函数内导入清零
        # （collaboration→assistant / world→assistant / interaction→assistant
        # 为各对既有方向，见 ADR-0031）。
        (COLLABORATION_CHANGED_CASES, _collab_changed_cases),
        (COLLABORATION_SUBMIT_CHANGED_CASE, _collab_submit_changed_case),
        (COLLABORATION_STOP_UNAVAILABLE_RUNS, _collab_stop_unavailable_runs),
        (COLLABORATION_READ_PROJECTED_RUN, _collab_read_projected_run),
        (WORLD_MAP_CAPABILITIES, _world_map_capabilities),
        (WORLD_REVIEW_TEAM_STRESS, _world_review_team_stress),
        (IMPORTS_GET_ACTIVE_ORGANIZATION, _imports_get_active_organization),
        (INTERACTION_READ_CONTINUITY_REVIEW, _interaction_read_continuity_review),
        # AO-5 第三批：world/writing/project/evidence 消费相邻高层模块的
        # 单点 facade 能力经这些 DI 键，七个剩余函数内反方向清零
        # （evolution→world / evolution→writing / story→project /
        # interaction→evidence / world→writing / imports→world 为各对
        # 裁定方向，见 ADR-0031）。
        (
            EVOLUTION_REQUIRE_CURRENT_WORLD_CANDIDATE,
            _evolution_require_current_world_candidate,
        ),
        (
            EVOLUTION_RECORD_WRITING_SOURCE_CHANGE,
            _evolution_record_writing_source_change,
        ),
        (IMPORTS_GET_REVIEW_DISPOSITIONS, _imports_get_review_dispositions),
        (
            INTERACTION_VALIDATE_PUBLIC_DEMO_SOURCE_CONTEXT,
            _interaction_validate_demo_context,
        ),
        (STORY_GET_SCENE_CONTRACT, _story_get_scene_contract),
        (
            WORLD_LIST_ADOPTED_MAP_CONTINUITY_FACTS,
            _world_list_map_continuity_facts,
        ),
        # AO-5: local_agent 设备确认回写 interaction 经此 DI port，反向顶层导入清零。
        (
            INTERACTION_MARK_TASK_LOCAL_APPROVED,
            _interaction_mark_task_local_approved,
        ),
        # AO-5 第二批：local_agent(L1)/evidence(L2)/writing(L2) 消费 assistant
        # facade 能力经这些 DI 键，assistant 反方向顶层/函数内导入清零。
        (
            ASSISTANT_MARK_TASK_LOCAL_APPROVED,
            _assistant_mark_task_local_approved,
        ),
        (ASSISTANT_INSPECT_DISCUSSION, _assistant_inspect_discussion),
        (
            ASSISTANT_SUBMIT_COMMENT_PROPOSALS,
            _assistant_submit_comment_proposals,
        ),
        (ASSISTANT_MARK_EDITORIAL_READY, _assistant_mark_editorial_ready),
        # AO-5: evidence 编译与 world 地图经此只读 port 消费 story 场景事实，
        # world→story / evidence→story 的反向顶层导入清零。
        (STORY_SCENE_SOURCE, _StorySceneSource()),
        # AO-5: evidence 编译经此只读 port 消费 writing 正文稿区间/清单，
        # evidence→writing 的反向顶层导入清零（ADR-0004：writing 为原文事实源）。
        (WRITING_MANUSCRIPT_SOURCE, _WritingManuscriptSource()),
        # AO-5: world core 经这些 DI port 消费 worldbuilding 能力（校验门、
        # Synopsis 失效钩子、聚焦采用授权、采用包引擎），core→worldbuilding
        # 导入语句清零；接线只在组合根。
        (
            WORLD_WORLDBUILDING_REQUIRE_LEGACY_CANON_WRITE_ALLOWED,
            _WorldValidationService().require_legacy_canon_write_allowed,
        ),
        (
            WORLD_WORLDBUILDING_MARK_SYNOPSIS_SOURCE_CHANGED,
            _world_mark_synopsis_source_changed,
        ),
        (
            WORLD_WORLDBUILDING_FOCUSED_ADOPTION_AUTHORIZE,
            _world_focused_authorize,
        ),
        (
            WORLD_WORLDBUILDING_FOCUSED_ADOPTION_CHECK_SOURCES,
            _world_focused_check_sources,
        ),
        (WORLD_WORLDBUILDING_FOCUSED_ADOPTION_FENCE, _world_focused_fence),
        (
            WORLD_WORLDBUILDING_ADOPTION_PACKAGE_SERVICE,
            _WorldAdoptionPackageService,
        ),
        (ASSISTANT_RUN_DISCUSSION_SCOPE, _assistant_run_discussion_scope),
        (
            ASSISTANT_REQUIRE_OPERATION_TARGETS,
            _assistant_require_operation_targets,
        ),
        (WORLD_ASSISTANT_REQUIRE_SOURCE, _world_assistant.require_source),
        (WORLD_ASSISTANT_REQUIRE_CHECKPOINT, _world_assistant.require_checkpoint),
        (WORLD_ASSISTANT_OUTCOME_STATES, _world_assistant.outcome_states),
        (WORLD_ASSISTANT_CHAT, _world_assistant.chat),
        (WORLD_ASSISTANT_CHAT_INTENT, _world_assistant.chat_intent),
        (WORLD_LIST_CHARACTERS, _world_list_characters),
        (WORLD_LIST_ENTITY_TERMS, _world_list_entity_terms),
        (WORLD_LIST_ENTITIES, _world_list_entities),
        (WORLD_RUN_SCENE_ENTITY_EXTRACTION, scene_extraction.extract_by_scenes),
        (
            WORLD_RUN_ALIAS_RELATION_EXTRACTION,
            scene_extraction,
        ),
        (WORLD_CREATE_CHARACTER, _world_create_char),
        (WORLD_GET_CHARACTER_ID_BY_WORLD_ENTITY, _world_get_char_id),
        (RAG_INDEX_CHAPTER, _rag_index),
        (RAG_INDEX_CHAPTER_FOR_TASK, rag_indexing.index_chapter_for_task),
        (RAG_GET_ORDERED_CHAPTER_CHUNKS, _rag_get_chunks),
        (RAG_GET_ENTITY_ACTIVITY_STATS, _rag_get_entity_activity_stats),
        (
            RAG_REQUEST_ENTITY_ACTIVITY_REANNOTATION,
            _rag_request_entity_reannotation,
        ),
        (WRITING_LIST_CHAPTER_INDICES, _writing_list_indices),
        (WRITING_LIST_EFFECTIVE_CHAPTER_INDICES, _writing_list_effective_indices),
        (WRITING_GET_LATEST_DRAFT_FOR_CHAPTER, _writing_get_draft),
        (WRITING_LIST_LATEST_DRAFTS_FOR_CHAPTERS, _writing_list_latest_drafts),
        (OUTLINE_GENERATE_STRUCTURE, PlotStructureGenerator().generate),
        (OUTLINE_ARC_SERVICE, OutlineArcService()),
        (OUTLINE_THREAD_SERVICE, PlotThreadService()),
        (OUTLINE_SCENE_SERVICE, SceneService()),
        (OUTLINE_FORESHADOWING_SERVICE, ForeshadowingPlanService()),
        (OUTLINE_REVEAL_SERVICE, RevealPlanService()),
        (CONTEXT_COMPILE, _ctx_compile),
        (CONTEXT_GENERATION_BACKGROUND, _ctx_generation_background),
        (MEMORY_SERVICE, memory),
        (PROJECT_REQUIRE_ACTIVE, _project_require_active),
        (INTERACTION_COUNT_SOURCE_REFERENCES, _interaction_source_reference_count),
        (WORLD_ENQUEUE_MAP_ATLAS_CLEANUP, _map_atlas_cleanup),
        # AO-4: project reads L2 aggregates through these provider ports.
        (PROJECT_WORKSPACE_WRITING_STATS, _WritingWorkspaceStatsAdapter()),
        (PROJECT_WORKSPACE_WORLD_STATS, _WorldWorkspaceStatsAdapter()),
        (PROJECT_WORKSPACE_STORY_STATS, _StoryWorkspaceStatsAdapter()),
        (PROJECT_DEDUP_WORLD, _WorldDedupAdapter()),
        (PROJECT_DEDUP_STORY, _StoryDedupAdapter()),
        # AO-4: account resolves project owners through this project-owned port.
        (ACCOUNT_PROJECT_OWNER_REF, _project_owner_ref),
        # AO-5 第三批：account 生命周期/公共 demo 主体消费 project 能力经这些
        # project 门面 DI 键，account→project 函数内导入清零。
        (ACCOUNT_PROJECT_CONTEXT, _project_context),
        (ACCOUNT_PROJECT_IDS_FOR_OWNER, _project_list_ids_for_owner),
        (ACCOUNT_PROJECT_PURGE_FOR_OWNER, _project_purge_for_owner),
    )


def register_container_services(ignore_existing: bool = False) -> None:
    """Register module services as process singletons in the global DI container.

    Args:
        ignore_existing: when True, keep any already registered service object
            and register only missing keys. When False, duplicate registrations
            keep core.container.register's ValueError behavior.
    """
    _register_orm_models()
    _register_collaboration_resource_spi(ignore_existing)
    for name, service in _container_services():
        if ignore_existing:
            try:
                _get(name)
            except KeyError:
                pass
            else:
                continue
        _register(name, service)
    # AO-10 启动校验：登记表声明的键必须全部注册（条件注册键按
    # core.service_keys.CONDITIONALLY_REGISTERED 豁免），防拼写/漏注册。
    ensure_registered(
        key for key in ALL_SERVICE_KEYS if key.name not in CONDITIONALLY_REGISTERED
    )


def _register_collaboration_resource_spi(ignore_existing: bool) -> None:
    """先注册 collaboration 资源 SPI 类型（AO-5）。

    L2 provider adapter（story/writing creative.py）在组合根装配
    ``collaboration.resources`` 时经容器解析这些类型，不再顶层 import
    modules.collaboration.contracts；类型对象不变，行为不变。
    """
    from modules.collaboration.contracts import (
        CreativeResourcePort,
        ResourceSnapshot,
    )

    for name, service in (
        (COLLABORATION_RESOURCE_SNAPSHOT, ResourceSnapshot),
        (COLLABORATION_CREATIVE_RESOURCE_PORT, CreativeResourcePort),
    ):
        if ignore_existing:
            try:
                _get(name)
            except KeyError:
                pass
            else:
                continue
        _register(name, service)
