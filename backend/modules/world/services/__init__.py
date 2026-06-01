"""World 服务层导出"""

from modules.world.services.character_knowledge_service import (
    CharacterKnowledgeService,
)
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

# 去重服务: 仍可通过 modules.world.services.dedup_service 直接导入
# (本文件不重导出以保持 facade 简洁 — 调用方按需 import)

__all__ = [
    "WorldEntityService",
    "EntityRelationService",
    "EntityRevisionService",
    "EventService",
    "CharacterService",
    "CharacterKnowledgeService",
    "parse_uuid",
    "normalize_name",
    "merge_text_field",
    "world_entity_types_compatible",
]
