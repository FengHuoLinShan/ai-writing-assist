<<<<<<< HEAD
"""World 服务层 — 核心实体 + 关联服务"""

from modules.world.services.candidate_service import EntityCandidateService
from modules.world.services.dedup_service import EntityDedupService
from modules.world.services.entity_service import CoreEntityService
from modules.world.services.extraction_service import EntityExtractionService, ExtractionResult
=======
"""World 服务层导出"""

from modules.world.services.character_service import CharacterService
from modules.world.services.entity_relation_service import EntityRelationService
from modules.world.services.entity_revision_service import EntityRevisionService
from modules.world.services.entity_service import WorldEntityService
from modules.world.services.event_service import EventService
>>>>>>> origin/worktree-grill-v3
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
    "CoreEntityService",
    "RelationshipService",
<<<<<<< HEAD
    "EntityCandidateService",
    "EntityDedupService",
    "EntityExtractionService",
    "ExtractionResult",
=======
    "EntityRelationService",
    "EntityRevisionService",
    "EventService",
    "CharacterService",
>>>>>>> origin/worktree-grill-v3
    "parse_uuid",
    "normalize_name",
    "merge_text_field",
    "world_entity_types_compatible",
]
