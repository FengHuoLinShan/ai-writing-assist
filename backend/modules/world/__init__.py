"""
modules/world — 世界对象与关系管理模块

管理小说世界中的核心对象（地点、组织、物品、事件、规则等）及其关系。
"""

from __future__ import annotations

from modules.world.contracts import (
    DuplicateSuggestion,
    EntityAliasContract,
    EntityCandidateContract,
    RelationshipContract,
    WorldEntityContract,
)
from modules.world.facade import (
    expand_related_entities,
    find_duplicate_entity_candidates,
    find_similar_entities,
    get_world_context,
    merge_candidate_into_entity,
)
from modules.world.models import (
    EntityAlias,
    EntityCandidate,
    Relationship,
    WorldEntity,
)
from modules.world.schemas import (
    EntityAliasCreate,
    EntityAliasResponse,
    EntityCandidateCreate,
    EntityCandidateResponse,
    RelationshipCreate,
    RelationshipResponse,
    WorldContextBundle,
    WorldEntityContext,
    WorldEntityCreate,
    WorldEntityResponse,
    WorldEntityUpdate,
)
# 注意：不导出 Services — 其他模块只能通过 contracts/facade 访问
# 详见 AI开发规则.md 第 3 节

__all__ = [
    # ORM Models
    "WorldEntity",
    "Relationship",
    "EntityAlias",
    "EntityCandidate",
    # Pydantic Schemas
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
    "WorldEntityContract",
    "RelationshipContract",
    "EntityAliasContract",
    "EntityCandidateContract",
    "DuplicateSuggestion",
    # Facade（唯一对外入口）
    "get_world_context",
    "expand_related_entities",
    "find_duplicate_entity_candidates",
    "find_similar_entities",
    "merge_candidate_into_entity",
]
