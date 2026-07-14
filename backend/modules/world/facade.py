"""
World Facade — 对外入口 (re-export hub)

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。

子 facade 按领域拆分：
  entity_facade   — 实体 / 关系 / 去重
  character_facade — 人物
  event_facade    — 事件 / 修订 / 抽取 / 状态导出
  worldbuilding_facade — 世界书 / 上下文激活
"""

from modules.world.character_facade import (  # noqa: F401
    create_character,
    filter_context_by_character_knowledge,
    find_character_id_by_name,
    get_character_id_by_world_entity,
    get_character_knowledge_context,
    get_character_knowledge_entries,
    get_character_location_id,
    get_characters_at_location,
    get_characters_context,
    list_characters,
    update_character_location,
)
from modules.world.entity_facade import (  # noqa: F401
    append_candidate_alias,
    apply_entity_fusion,
    backfill_entity_embeddings,
    count_entities,
    create_entity,
    create_or_merge_relation,
    create_relation,
    deprecate_deep_import_entities_by_workflow,
    expand_related_entities,
    find_entity_id_by_name,
    find_similar_entities,
    find_working_entity_id_by_name,
    find_working_entity_ids_by_names,
    get_deep_import_alias_metadata_summary,
    get_entity_relations,
    get_world_context,
    list_auto_ingested_entities,
    list_entities,
    list_entity_terms,
    merge_candidate_into_entity,
    repair_deep_import_alias_metadata,
    rollback_deep_import_aliases_by_workflow,
    rollback_deep_import_relations_by_workflow,
    suggest_entity_fusion,
    update_entity,
    upsert_relation,
)
from modules.world.event_facade import (  # noqa: F401
    create_event,
    get_entity_revisions,
    get_events_context,
    get_full_state,
    rollback_to_revision,
)
from modules.world.map_facade import (  # noqa: F401
    count_deep_import_map_observations_by_workflow,
    create_map_observation_from_delta_event,
    rollback_deep_import_map_observations_by_workflow,
)
from modules.world.worldbuilding_facade import (  # noqa: F401
    get_world_background,
    get_world_bible_synopsis_context,
    get_world_bible_working_pages_context,
    mark_world_bible_synopsis_stale,
    mark_worldbuilding_context_stale,
    preview_worldbuilding_activation,
)

# Frozen cross-module API. New names require a deletion test, contract/README
# update, and an explicit change to the public-surface regression test.
__all__ = [
    "append_candidate_alias",
    "apply_entity_fusion",
    "backfill_entity_embeddings",
    "count_deep_import_map_observations_by_workflow",
    "count_entities",
    "create_character",
    "create_entity",
    "create_event",
    "create_map_observation_from_delta_event",
    "create_or_merge_relation",
    "create_relation",
    "deprecate_deep_import_entities_by_workflow",
    "expand_related_entities",
    "filter_context_by_character_knowledge",
    "find_character_id_by_name",
    "find_entity_id_by_name",
    "find_similar_entities",
    "find_working_entity_id_by_name",
    "find_working_entity_ids_by_names",
    "get_character_id_by_world_entity",
    "get_character_knowledge_context",
    "get_character_knowledge_entries",
    "get_character_location_id",
    "get_characters_at_location",
    "get_characters_context",
    "get_deep_import_alias_metadata_summary",
    "get_entity_relations",
    "get_entity_revisions",
    "get_events_context",
    "get_full_state",
    "get_world_background",
    "get_world_bible_synopsis_context",
    "get_world_bible_working_pages_context",
    "get_world_context",
    "list_auto_ingested_entities",
    "list_characters",
    "list_entities",
    "list_entity_terms",
    "mark_worldbuilding_context_stale",
    "mark_world_bible_synopsis_stale",
    "merge_candidate_into_entity",
    "preview_worldbuilding_activation",
    "repair_deep_import_alias_metadata",
    "rollback_deep_import_aliases_by_workflow",
    "rollback_deep_import_map_observations_by_workflow",
    "rollback_deep_import_relations_by_workflow",
    "rollback_to_revision",
    "suggest_entity_fusion",
    "update_character_location",
    "update_entity",
    "upsert_relation",
]
