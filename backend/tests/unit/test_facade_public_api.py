"""P2 regression gates for contracts and frozen root facade surfaces."""

from __future__ import annotations

import modules.world as world_package
from modules.story.outline_state import facade as outline_facade
from modules.world import contracts as world_contracts
from modules.world import facade as world_facade

WORLD_FACADE_API = {
    "assemble_post_import_adoption_package",
    "append_candidate_alias",
    "apply_entity_fusion",
    "apply_entity_fusion_group",
    "backfill_entity_embeddings",
    "count_entities",
    "create_character",
    "create_entity",
    "create_event",
    "create_or_merge_relation",
    "create_relation",
    "dedupe_deep_import_workflow_candidates",
    "deprecate_deep_import_entities_by_workflow",
    "expand_related_entities",
    "filter_context_by_character_knowledge",
    "find_character_id_by_name",
    "find_entity_id_by_name",
    "find_similar_entities",
    "find_working_entity_id_by_name",
    "find_working_entity_ids_by_names",
    "get_author_attention_summary",
    "get_character_id_by_world_entity",
    "get_character_knowledge_context",
    "get_character_knowledge_entries",
    "get_character_location_id",
    "get_characters_at_location",
    "get_characters_context",
    "get_deep_import_alias_metadata_summary",
    "get_entity_importance_map",
    "get_entity_relations",
    "get_entity_revisions",
    "get_events_context",
    "get_full_state",
    "get_world_background",
    "get_world_bible_page_source_manifest",
    "get_world_bible_projection_candidates",
    "get_world_bible_synopsis_context",
    "get_world_bible_working_pages_context",
    "get_world_context",
    "initialize_world_canon",
    "list_auto_ingested_entities",
    "list_characters",
    "list_entities",
    "list_entity_terms",
    "list_world_bible_working_page_ids",
    "mark_worldbuilding_context_stale",
    "mark_world_bible_synopsis_stale",
    "merge_candidate_into_entity",
    "preview_worldbuilding_activation",
    "repair_deep_import_alias_metadata",
    "rollback_deep_import_aliases_by_workflow",
    "rollback_deep_import_relations_by_workflow",
    "rollback_to_revision",
    "suggest_entity_fusion",
    "update_character_location",
    "update_entity",
    "upsert_relation",
}

OUTLINE_FACADE_API = {
    "apply_structure_dedup",
    "apply_structure_dedup_group",
    "batch_create_scenes",
    "bind_scene_spans_to_source",
    "count_scenes_by_novel",
    "create_scene",
    "get_author_attention_items",
    "deprecate_deep_import_scenes_by_workflow",
    "deprecate_deep_import_structure_assets_by_workflow",
    "ensure_deep_import_structure_outputs",
    "get_active_foreshadowing",
    "get_deep_import_fallback_thread_type",
    "get_deep_import_structure_category_counts",
    "get_deep_import_structure_category_targets",
    "get_deep_import_structure_output_count",
    "get_next_scene_index",
    "get_outline_analysis_context",
    "get_plot_threads_for_context",
    "get_reader_reveal_decision",
    "get_scene",
    "get_scene_context_window",
    "get_scene_execution_bundle",
    "get_scene_contract",
    "get_scene_span_coverage",
    "get_scene_spans_by_chapter",
    "get_scene_spans_for_scene",
    "get_scene_summary_checkpoint",
    "get_scenes_by_chapter",
    "get_scenes_by_novel",
    "get_scenes_by_provenance_key",
    "get_scenes_by_provenance_keys",
    "commit_deep_import_scene_candidates",
    "persist_deep_import_fusion_suggestions",
    "rebuild_scene_summary_checkpoint",
    "select_deep_import_fallback_reveal_target",
    "split_scene_chunk_to_new_chapter",
    "suggest_structure_dedup",
    "update_scene",
}

WORLD_CONTRACT_API = {
    "CharacterContract",
    "CharacterKnowledgeContract",
    "CoreEntityContract",
    "EntityRelationContract",
    "EntityRevisionContract",
    "EventContract",
    "GenerationBackgroundProvider",
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
}


def _public_callables(module) -> set[str]:
    return {
        name
        for name, value in vars(module).items()
        if not name.startswith("_") and callable(value)
    }


def test_world_root_facade_public_api_is_frozen() -> None:
    assert set(world_facade.__all__) == WORLD_FACADE_API
    assert _public_callables(world_facade) == WORLD_FACADE_API


def test_outline_root_facade_public_api_is_frozen() -> None:
    assert set(outline_facade.__all__) == OUTLINE_FACADE_API
    assert _public_callables(outline_facade) == OUTLINE_FACADE_API


def test_world_contracts_do_not_reexport_http_schemas() -> None:
    assert set(world_contracts.__all__) == WORLD_CONTRACT_API


def test_world_alias_task_port_keeps_domain_surface() -> None:
    for method in (
        "prepare_alias_relation_task",
        "execute_alias_relation_task",
        "finalize_alias_relation_task",
    ):
        assert hasattr(world_contracts.WorldAliasRelationTaskPort, method)
    for schema_name in (
        "CharacterContextBundle",
        "CharacterResponse",
        "CoreEntityResponse",
        "EntityRelationResponse",
        "WorldContextBundle",
    ):
        assert not hasattr(world_contracts, schema_name)


def test_world_package_root_has_no_orm_schema_or_facade_reexports() -> None:
    assert not hasattr(world_package, "__all__")
    for legacy_name in (
        "CoreEntity",
        "CoreEntityResponse",
        "CoreEntityContract",
        "get_world_context",
    ):
        assert not hasattr(world_package, legacy_name)
