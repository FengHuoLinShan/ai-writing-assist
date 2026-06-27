"""World 服务层 — 与旧 services.py 兼容的导出"""

from modules.world.services.alias_service import AliasService
from modules.world.services.candidate_service import EntityCandidateService
from modules.world.services.dedup_service import EntityDedupService
from modules.world.services.entity_service import WorldEntityService
from modules.world.services.extraction_service import (
    EntityExtractionService,
    ExtractionResult,
)
from modules.world.services.helpers import (
    merge_text_field,
    normalize_name,
    parse_uuid,
    world_entity_types_compatible,
)
from modules.world.services.relationship_service import RelationshipService

__all__ = [
    "WorldEntityService",
    "RelationshipService",
    "EntityCandidateService",
    "AliasService",
    "EntityDedupService",
    "EntityExtractionService",
    "ExtractionResult",
    "parse_uuid",
    "normalize_name",
    "merge_text_field",
    "world_entity_types_compatible",
]
