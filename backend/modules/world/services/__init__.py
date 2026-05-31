"""World 服务层导出"""

from modules.world.services.character_service import CharacterService
from modules.world.services.entity_relation_service import EntityRelationService
from modules.world.services.entity_revision_service import EntityRevisionService
from modules.world.services.entity_service import WorldEntityService
from modules.world.services.event_service import EventService
from modules.world.services.helpers import (
    merge_text_field,
    normalize_name,
    parse_uuid,
    world_entity_types_compatible,
)
from modules.world.services.relationship_service import RelationshipService

# 已废弃：候选池/别名/去重服务（EntityCandidateService, EntityDedupService, AliasService, EntityExtractionService）
# 仍可通过直接导入 modules.world.services.{module} 使用

__all__ = [
    "WorldEntityService",
    "RelationshipService",
    "EntityRelationService",
    "EntityRevisionService",
    "EventService",
    "CharacterService",
    "parse_uuid",
    "normalize_name",
    "merge_text_field",
    "world_entity_types_compatible",
]
