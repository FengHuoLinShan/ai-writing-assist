"""
modules/world — 共享核心实体与关系管理模块

管理所有子系统的公共字段（core_entities）及其关系。
"""

from __future__ import annotations

from modules.world.contracts import (
    DuplicateSuggestion,
    EntityCandidateContract,
    RelationshipContract,
    WorldEntityContract,
)

# 注意：EntityAliasContract 已移除 — 别名现在在 CoreEntity.aliases JSONB 中
from modules.world.facade import (
    accept_candidate,
    add_alias,
    count_pending_candidates,
    create_entity,
    delete_entity,
    expand_related_entities,
    find_duplicate_entity_candidates,
    find_entity_id_by_name,
    find_similar_entities,
    get_entity,
    get_entity_importance_map,
    get_location_factions,
    get_world_context,
    list_entities,
    list_entity_terms,
    merge_candidate_into_entity,
    remove_alias,
    run_entity_extraction,
    update_entity,
    upsert_relationship,
)
from modules.world.models import (
    CoreEntity,
    EntityCandidate,
    Relationship,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityResponse,
    CoreEntityUpdate,
    CoreEntityContext,
    EntityCandidateCreate,
    EntityCandidateResponse,
    RelationshipCreate,
    RelationshipResponse,
    WorldContextBundle,
)

__all__ = [
    # ORM Models
    "CoreEntity",
    "Relationship",
    "EntityCandidate",
    # Pydantic Schemas
    "CoreEntityCreate",
    "CoreEntityUpdate",
    "CoreEntityResponse",
    "CoreEntityContext",
    "RelationshipCreate",
    "RelationshipResponse",
    "EntityCandidateCreate",
    "EntityCandidateResponse",
    "WorldContextBundle",
    # Contracts
    "WorldEntityContract",
    "RelationshipContract",
    "EntityCandidateContract",
    "DuplicateSuggestion",
    # Facade
    "get_world_context",
    "expand_related_entities",
    "find_duplicate_entity_candidates",
    "find_similar_entities",
    "merge_candidate_into_entity",
    "accept_candidate",
    "list_entities",
    "list_entity_terms",
    "count_pending_candidates",
    "run_entity_extraction",
    "create_entity",
    "get_entity",
    "update_entity",
    "delete_entity",
    "add_alias",
    "remove_alias",
    "find_entity_id_by_name",
    "get_entity_importance_map",
    "get_location_factions",
    "upsert_relationship",
]
