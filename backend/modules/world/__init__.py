"""
<<<<<<< HEAD
modules/world — 共享核心实体与关系管理模块

管理所有子系统的公共字段（core_entities）及其关系。
=======
modules/world — 核心实体与关系管理模块（v3 因果时空网）

管理小说世界的核心实体、事件、关系、版本历史和人物档案。
>>>>>>> origin/worktree-grill-v3
"""

from __future__ import annotations

from modules.world.contracts import (
<<<<<<< HEAD
    DuplicateSuggestion,
    EntityCandidateContract,
    RelationshipContract,
    WorldEntityContract,
=======
    CharacterContract,
    CharacterKnowledgeContract,
    CoreEntityContract,
    EntityRelationContract,
    EntityRevisionContract,
    EventContract,
>>>>>>> origin/worktree-grill-v3
)

# 注意：EntityAliasContract 已移除 — 别名现在在 CoreEntity.aliases JSONB 中
from modules.world.facade import (
    accept_candidate,
    add_alias,
    count_pending_candidates,
<<<<<<< HEAD
    create_entity,
    delete_entity,
=======
    create_character,
>>>>>>> origin/worktree-grill-v3
    expand_related_entities,
    find_duplicate_entity_candidates,
    find_entity_id_by_name,
    find_similar_entities,
<<<<<<< HEAD
    get_entity,
    get_entity_importance_map,
    get_location_factions,
=======
    get_characters_context,
    get_events_context,
>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
    CoreEntity,
=======
    Character,
    CharacterKnowledge,
    CoreEntity,
    EntityAlias,
>>>>>>> origin/worktree-grill-v3
    EntityCandidate,
    EntityRelation,
    EntityRevision,
    Event,
    Relationship,
)
from modules.world.schemas import (
<<<<<<< HEAD
    CoreEntityCreate,
    CoreEntityResponse,
    CoreEntityUpdate,
    CoreEntityContext,
=======
    CharacterContextBundle,
    CharacterKnowledgeContext,
    CharacterResponse,
    CoreEntityResponse,
    EntityAliasCreate,
    EntityAliasResponse,
>>>>>>> origin/worktree-grill-v3
    EntityCandidateCreate,
    EntityCandidateResponse,
    EntityRelationCreate,
    EntityRelationResponse,
    EventContext,
    EventsContextBundle,
    EventResponse,
    RelationshipCreate,
    RelationshipResponse,
    WorldContextBundle,
)
<<<<<<< HEAD
=======
# 注意：不导出 Services — 其他模块只能通过 contracts/facade 访问
>>>>>>> origin/worktree-grill-v3

__all__ = [
    # ORM Models
    "CoreEntity",
<<<<<<< HEAD
=======
    "Event",
    "EntityRelation",
    "EntityRevision",
    "Character",
    "CharacterKnowledge",
    "WorldEntity",
>>>>>>> origin/worktree-grill-v3
    "Relationship",
    "EntityCandidate",
    # Pydantic Schemas
<<<<<<< HEAD
    "CoreEntityCreate",
    "CoreEntityUpdate",
    "CoreEntityResponse",
    "CoreEntityContext",
=======
    "CoreEntityResponse",
    "EventResponse",
    "EventContext",
    "EventsContextBundle",
    "EntityRelationCreate",
    "EntityRelationResponse",
    "CharacterResponse",
    "CharacterContextBundle",
    "CharacterKnowledgeContext",
    "WorldEntityCreate",
    "WorldEntityUpdate",
    "WorldEntityResponse",
>>>>>>> origin/worktree-grill-v3
    "RelationshipCreate",
    "RelationshipResponse",
    "EntityCandidateCreate",
    "EntityCandidateResponse",
    "WorldContextBundle",
    # Contracts
<<<<<<< HEAD
    "WorldEntityContract",
    "RelationshipContract",
    "EntityCandidateContract",
    "DuplicateSuggestion",
=======
    "CoreEntityContract",
    "EventContract",
    "EntityRelationContract",
    "EntityRevisionContract",
    "CharacterContract",
    "CharacterKnowledgeContract",
>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
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
=======
    "get_events_context",
    "create_character",
    "get_characters_context",
>>>>>>> origin/worktree-grill-v3
]
