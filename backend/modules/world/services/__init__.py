"""World 服务层导出"""

from modules.world.services.common import (
    merge_text_field,
    normalize_name,
    parse_uuid,
    world_entity_types_compatible,
)
from modules.world.services.core.character_knowledge_service import (
    CharacterKnowledgeService,
)
from modules.world.services.core.character_service import CharacterService
from modules.world.services.core.entity_alias_service import EntityAliasService
from modules.world.services.core.entity_context_service import EntityContextService
from modules.world.services.core.entity_embedding_service import EntityEmbeddingService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_revision_service import EntityRevisionService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.core.entity_stats_service import EntityStatsService
from modules.world.services.core.event_service import EventService
from modules.world.services.map.map_config_service import MapConfigService
from modules.world.services.map.map_location_binding_service import (
    MapLocationBindingService,
)
from modules.world.services.map.map_tile_service import MapTileService

# 去重服务: 仍可通过 modules.world.services.core.dedup_service 直接导入
# (本文件不重导出以保持 facade 简洁 — 调用方按需 import)

__all__ = [
    "WorldEntityService",
    "EntityAliasService",
    "EntityContextService",
    "EntityEmbeddingService",
    "EntityRelationService",
    "EntityRevisionService",
    "EntityStatsService",
    "EventService",
    "CharacterService",
    "CharacterKnowledgeService",
    "MapConfigService",
    "MapTileService",
    "MapLocationBindingService",
    "parse_uuid",
    "normalize_name",
    "merge_text_field",
    "world_entity_types_compatible",
]
