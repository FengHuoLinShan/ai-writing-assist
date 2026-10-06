"""Application composition root for DI container registration."""
# ruff: noqa: I001

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.container import get as _get
from core.container import register as _register
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
    get_project_owner_ref as _project_owner_ref,
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
)
from modules.world.project_ports import (
    WorldDedupAdapter as _WorldDedupAdapter,
)
from modules.world.project_ports import (
    WorldWorkspaceStatsAdapter as _WorldWorkspaceStatsAdapter,
)
from modules.world.map_atlas_facade import (
    enqueue_map_atlas_project_cleanup as _map_atlas_cleanup,
)
from modules.world import assistant_ports as _world_assistant
from modules.world.assistant_tools import OPERATIONS as _WORLD_OPERATIONS
from modules.project.assistant_dedup_tool import OPERATIONS as _PROJECT_DEDUP_OPERATIONS
from modules.story.assistant_information_tools import (
    OPERATIONS as _STORY_INFORMATION_OPERATIONS,
)
from modules.world.assistant_page_tools import OPERATIONS as _WORLD_PAGE_OPERATIONS
from modules.world.assistant_outcome_tools import OPERATIONS as _WORLD_OUTCOME_OPERATIONS
from modules.world.assistant_cocreation_tools import (
    OPERATIONS as _WORLD_COCREATION_OPERATIONS,
)
from modules.writing.assistant_tools import OPERATIONS as _WRITING_OPERATIONS
from modules.writing.assistant_generation_tool import (
    OPERATIONS as _WRITING_GENERATION_OPERATIONS,
)
from modules.writing.assistant_candidate_tools import (
    OPERATIONS as _WRITING_CANDIDATE_OPERATIONS,
)
from modules.project.assistant_tools import OPERATIONS as _PROJECT_OPERATIONS
from modules.story.assistant_tools import OPERATIONS as _STORY_OPERATIONS
from modules.story.assistant_structure_workflow import (
    OPERATIONS as _STORY_STRUCTURE_OPERATIONS,
)
from modules.story.assistant_planning_tools import (
    OPERATIONS as _STORY_PLANNING_OPERATIONS,
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
    collect_forecast_understanding as _collab_collect_forecast_understanding,
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


def _container_services() -> Iterable[tuple[str, Any]]:
    """Build app/worker process-singleton service registrations."""
    scene_extraction = _SceneExtractSvc()
    memory = MemoryService()
    rag_indexing = _RagIndexingService()
    from modules.writing.creative import port as _writing_creative_port
    from modules.story.creative import ports as story_creative
    from modules.world.creative import PORT as WORLD_CREATIVE
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
            "assistant.forecast.instructions",
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
            "assistant.forecast.personas",
            {
                "rp": {
                    "authorize": interaction_forecast.authorize,
                    "materialize": interaction_forecast.materialize,
                }
            },
        ),
        (
            "assistant.forecast.choices",
            {
                "world": world_forecast.prepare_direction,
                "evidence": evidence_forecast.prepare_direction,
            },
        ),
        (
            "assistant.forecast.sources",
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
            "collaboration.resources",
            {
                "writing_draft": _writing_creative_port(),
                "world_bible_draft": WORLD_CREATIVE,
                **story_creative(),
            },
        ),
        (
            "assistant.operations",
            {
                **_WORLD_OPERATIONS,
                **_PROJECT_DEDUP_OPERATIONS,
                **_STORY_INFORMATION_OPERATIONS,
                **_WORLD_PAGE_OPERATIONS,
                **_WORLD_OUTCOME_OPERATIONS,
                **_WORLD_COCREATION_OPERATIONS,
                **_WRITING_OPERATIONS,
                **_WRITING_GENERATION_OPERATIONS,
                **_WRITING_CANDIDATE_OPERATIONS,
                **_PROJECT_OPERATIONS,
                **_STORY_OPERATIONS,
                **_STORY_STRUCTURE_OPERATIONS,
                **_STORY_PLANNING_OPERATIONS,
                **_IMPORTS_OPERATIONS,
                **evidence_forecast.OPERATIONS,
                **_MAP_OPERATIONS,
                **_WORLD_REVIEW_OPERATIONS,
            },
        ),
        ("source.changed", _assistant_mark_changed),
        (
            "assistant.proactive.submitters",
            {
                "writing": _writing_proactive_review,
                "world": _world_proactive_review,
                "interaction": _interaction_proactive_review,
                "imports": _imports_proactive_review,
                "story": _story_proactive_review,
            },
        ),
        ("assistant.proactive.findings", {"world_validation": _world_review_findings}),
        ("assistant.session_service", _AssistantSessions()),
        # AO-5: assistant forecast 消费 collaboration 理解包经此 DI port，
        # assistant→collaboration 保持零顶层导入（collaboration→assistant
        # 为该对的既有顶层方向）。
        (
            "collaboration.collect_forecast_understanding",
            _collab_collect_forecast_understanding,
        ),
        # AO-5: local_agent 设备确认回写 interaction 经此 DI port，反向顶层导入清零。
        (
            "interaction.mark_task_local_approved",
            _interaction_mark_task_local_approved,
        ),
        # AO-5: evidence 编译与 world 地图经此只读 port 消费 story 场景事实，
        # world→story / evidence→story 的反向顶层导入清零。
        ("story.scene_source", _StorySceneSource()),
        # AO-5: evidence 编译经此只读 port 消费 writing 正文稿区间/清单，
        # evidence→writing 的反向顶层导入清零（ADR-0004：writing 为原文事实源）。
        ("writing.manuscript_source", _WritingManuscriptSource()),
        # AO-5: world core 经这些 DI port 消费 worldbuilding 能力（校验门、
        # Synopsis 失效钩子、聚焦采用授权、采用包引擎），core→worldbuilding
        # 导入语句清零；接线只在组合根。
        (
            "world.worldbuilding.require_legacy_canon_write_allowed",
            _WorldValidationService().require_legacy_canon_write_allowed,
        ),
        (
            "world.worldbuilding.mark_synopsis_source_changed",
            _world_mark_synopsis_source_changed,
        ),
        (
            "world.worldbuilding.focused_adoption.authorize",
            _world_focused_authorize,
        ),
        (
            "world.worldbuilding.focused_adoption.check_sources",
            _world_focused_check_sources,
        ),
        ("world.worldbuilding.focused_adoption.fence", _world_focused_fence),
        (
            "world.worldbuilding.adoption_package_service",
            _WorldAdoptionPackageService,
        ),
        ("assistant.run_discussion_scope", _assistant_run_discussion_scope),
        (
            "assistant.require_operation_targets",
            _assistant_require_operation_targets,
        ),
        ("world.assistant.require_source", _world_assistant.require_source),
        ("world.assistant.require_checkpoint", _world_assistant.require_checkpoint),
        ("world.assistant.outcome_states", _world_assistant.outcome_states),
        ("world.assistant.chat", _world_assistant.chat),
        ("world.assistant.chat_intent", _world_assistant.chat_intent),
        ("world.list_characters", _world_list_characters),
        ("world.list_entity_terms", _world_list_entity_terms),
        ("world.list_entities", _world_list_entities),
        ("world.run_scene_entity_extraction", scene_extraction.extract_by_scenes),
        (
            "world.run_alias_relation_extraction",
            scene_extraction,
        ),
        ("world.create_character", _world_create_char),
        ("world.get_character_id_by_world_entity", _world_get_char_id),
        ("rag.index_chapter", _rag_index),
        ("rag.index_chapter_for_task", rag_indexing.index_chapter_for_task),
        ("rag.get_ordered_chapter_chunks", _rag_get_chunks),
        ("rag.get_entity_activity_stats", _rag_get_entity_activity_stats),
        (
            "rag.request_entity_activity_reannotation",
            _rag_request_entity_reannotation,
        ),
        ("writing.list_chapter_indices", _writing_list_indices),
        ("writing.list_effective_chapter_indices", _writing_list_effective_indices),
        ("writing.get_latest_draft_for_chapter", _writing_get_draft),
        ("writing.list_latest_drafts_for_chapters", _writing_list_latest_drafts),
        ("outline.generate_structure", PlotStructureGenerator().generate),
        ("outline.arc_service", OutlineArcService()),
        ("outline.thread_service", PlotThreadService()),
        ("outline.scene_service", SceneService()),
        ("outline.foreshadowing_service", ForeshadowingPlanService()),
        ("outline.reveal_service", RevealPlanService()),
        ("context.compile", _ctx_compile),
        ("context.generation_background", _ctx_generation_background),
        ("memory.service", memory),
        ("project.require_active", _project_require_active),
        ("interaction.count_source_references", _interaction_source_reference_count),
        ("world.enqueue_map_atlas_cleanup", _map_atlas_cleanup),
        # AO-4: project reads L2 aggregates through these provider ports.
        ("project.workspace.writing_stats", _WritingWorkspaceStatsAdapter()),
        ("project.workspace.world_stats", _WorldWorkspaceStatsAdapter()),
        ("project.workspace.story_stats", _StoryWorkspaceStatsAdapter()),
        ("project.dedup.world", _WorldDedupAdapter()),
        ("project.dedup.story", _StoryDedupAdapter()),
        # AO-4: account resolves project owners through this project-owned port.
        ("account.project_owner_ref", _project_owner_ref),
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
        ("collaboration.ResourceSnapshot", ResourceSnapshot),
        ("collaboration.CreativeResourcePort", CreativeResourcePort),
    ):
        if ignore_existing:
            try:
                _get(name)
            except KeyError:
                pass
            else:
                continue
        _register(name, service)
