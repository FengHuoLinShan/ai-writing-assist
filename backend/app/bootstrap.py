"""Application composition root for DI container registration."""
# ruff: noqa: I001

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from core.container import get as _get
from core.container import register as _register
from modules.context.facade import compile_structure_context as _ctx_compile
from modules.context.facade import (
    compile_generation_background as _ctx_generation_background,
)
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService as _SceneExtractSvc,
)
from modules.memory.services import MemoryService
from modules.outline.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotStructureGenerator,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from modules.rag.facade import (
    get_entity_activity_stats as _rag_get_entity_activity_stats,
    get_ordered_chapter_chunks as _rag_get_chunks,
    index_chapter_with_report as _rag_index,
    request_entity_activity_reannotation as _rag_request_entity_reannotation,
)
from modules.rag.indexing import IndexingService as _RagIndexingService
from modules.project.facade import require_active_project as _project_require_active
from modules.writing.facade import (
    get_latest_draft_for_chapter as _writing_get_draft,
    list_chapter_indices as _writing_list_indices,
    list_effective_chapter_indices as _writing_list_effective_indices,
    list_latest_drafts_for_chapters as _writing_list_latest_drafts,
)
from modules.world.facade import (
    create_character as _world_create_char,
    get_character_id_by_world_entity as _world_get_char_id,
    list_characters as _world_list_characters,
    list_entities as _world_list_entities,
    list_entity_terms as _world_list_entity_terms,
)
from modules.world.map_atlas_facade import (
    enqueue_map_atlas_project_cleanup as _map_atlas_cleanup,
)


def _register_orm_models() -> None:
    """Import ORM models with Base.metadata for FK dependency resolution."""
    import modules.account.models  # noqa: F401, I001
    import modules.context.models  # noqa: F401, I001
    import modules.imports.models  # noqa: F401, I001
    import modules.interaction.models  # noqa: F401, I001
    import modules.project.models  # noqa: F401, I001
    import modules.settings.models  # noqa: F401, I001
    import modules.story.models  # noqa: F401, I001
    import modules.world.map_atlas_models  # noqa: F401, I001
    import modules.world.models  # noqa: F401, I001


def _container_services() -> Iterable[tuple[str, Any]]:
    """Build app/worker process-singleton service registrations."""
    scene_extraction = _SceneExtractSvc()
    memory = MemoryService()
    rag_indexing = _RagIndexingService()

    return (
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
        ("memory.capture_snapshot", memory.capture_snapshot),
        ("project.require_active", _project_require_active),
        ("world.enqueue_map_atlas_cleanup", _map_atlas_cleanup),
    )


def register_container_services(ignore_existing: bool = False) -> None:
    """Register module services as process singletons in the global DI container.

    Args:
        ignore_existing: when True, keep any already registered service object
            and register only missing keys. When False, duplicate registrations
            keep core.container.register's ValueError behavior.
    """
    _register_orm_models()
    for name, service in _container_services():
        if ignore_existing:
            try:
                _get(name)
            except KeyError:
                pass
            else:
                continue
        _register(name, service)
