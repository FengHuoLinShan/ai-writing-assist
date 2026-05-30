"""
modules/world — 核心实体与关系管理模块（v3 因果时空网）

管理小说世界的核心实体、事件、关系、版本历史和人物档案。
"""

from __future__ import annotations

from modules.world.contracts import (
    CharacterContract,
    CharacterKnowledgeContract,
    CoreEntityContract,
    EntityRelationContract,
    EntityRevisionContract,
    EventContract,
)
from modules.world.facade import (
    accept_candidate,
    count_pending_candidates,
    create_character,
    expand_related_entities,
    find_duplicate_entity_candidates,
    find_similar_entities,
    get_characters_context,
    get_events_context,
    get_world_context,
    list_entities,
    merge_candidate_into_entity,
    run_entity_extraction,
)
from modules.world.models import (
    Character,
    CharacterKnowledge,
    CoreEntity,
    EntityAlias,
    EntityCandidate,
    EntityRelation,
    EntityRevision,
    Event,
    Relationship,
    WorldEntity,
)
from modules.world.schemas import (
    CharacterContextBundle,
    CharacterKnowledgeContext,
    CharacterResponse,
    CoreEntityResponse,
    EntityAliasCreate,
    EntityAliasResponse,
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
    WorldEntityContext,
    WorldEntityCreate,
    WorldEntityResponse,
    WorldEntityUpdate,
)
# 注意：不导出 Services — 其他模块只能通过 contracts/facade 访问

__all__ = [
    # ORM Models
    "CoreEntity",
    "Event",
    "EntityRelation",
    "EntityRevision",
    "Character",
    "CharacterKnowledge",
    "WorldEntity",
    "Relationship",
    "EntityAlias",
    "EntityCandidate",
    # Pydantic Schemas
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
    "RelationshipCreate",
    "RelationshipResponse",
    "EntityAliasCreate",
    "EntityAliasResponse",
    "EntityCandidateCreate",
    "EntityCandidateResponse",
    "WorldEntityContext",
    "WorldContextBundle",
    # Contracts
    "CoreEntityContract",
    "EventContract",
    "EntityRelationContract",
    "EntityRevisionContract",
    "CharacterContract",
    "CharacterKnowledgeContract",
    # Facade
    "get_world_context",
    "expand_related_entities",
    "find_duplicate_entity_candidates",
    "find_similar_entities",
    "merge_candidate_into_entity",
    "accept_candidate",
    "list_entities",
    "count_pending_candidates",
    "run_entity_extraction",
    "get_events_context",
    "create_character",
    "get_characters_context",
]
