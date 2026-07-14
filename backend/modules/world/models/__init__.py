"""World ORM model package.

Importing this package registers every world table on ``core.base.Base.metadata``
and preserves the historical ``modules.world.models`` import path.
"""

from __future__ import annotations

from .character import Character, CharacterKnowledge
from .core import CoreEntity, EntityRelation, EntityRevision, Event, TextArchive
from .profiles import (
    EntityProfileTemplate,
    FactionProfile,
    GenericEntityProfile,
    ItemProfile,
    LocationProfile,
    RuleProfile,
    SecretProfile,
    SpeciesProfile,
    _ProfileMixin,
)
from .worldbuilding import (
    AssetKnowledgeTag,
    CharacterKnowledgeTag,
    ConflictCheckQueueItem,
    CreationSuggestion,
    GenerationPromptTemplate,
    GenerationPromptTemplateRevision,
    KnowledgeTag,
    KnowledgeTagExclusion,
    KnowledgeVisibilityPolicy,
    ReaderRevealPolicy,
    WorldBibleCategory,
    WorldBiblePage,
    WorldBiblePageDraft,
    WorldBiblePageProjection,
    WorldBiblePageRevision,
    WorldBibleSynopsisHead,
    WorldBibleSynopsisRevision,
)

WorldEntity = CoreEntity
WorldEntityAlias = object
EntityCandidate = object
Relationship = object
EntityAlias = object

__all__ = [
    "AssetKnowledgeTag",
    "Character",
    "CharacterKnowledge",
    "CharacterKnowledgeTag",
    "ConflictCheckQueueItem",
    "CoreEntity",
    "CreationSuggestion",
    "EntityAlias",
    "EntityCandidate",
    "EntityProfileTemplate",
    "EntityRelation",
    "EntityRevision",
    "Event",
    "FactionProfile",
    "GenerationPromptTemplate",
    "GenerationPromptTemplateRevision",
    "GenericEntityProfile",
    "ItemProfile",
    "KnowledgeTag",
    "KnowledgeTagExclusion",
    "KnowledgeVisibilityPolicy",
    "LocationProfile",
    "ReaderRevealPolicy",
    "Relationship",
    "RuleProfile",
    "SecretProfile",
    "SpeciesProfile",
    "TextArchive",
    "WorldBiblePage",
    "WorldBibleCategory",
    "WorldBiblePageDraft",
    "WorldBiblePageProjection",
    "WorldBiblePageRevision",
    "WorldBibleSynopsisHead",
    "WorldBibleSynopsisRevision",
    "WorldEntity",
    "WorldEntityAlias",
    "_ProfileMixin",
]
