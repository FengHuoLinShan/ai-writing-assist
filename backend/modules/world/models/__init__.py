"""World ORM model package.

Importing this package registers every world table on ``core.base.Base.metadata``
and preserves the historical ``modules.world.models`` import path.
"""

from __future__ import annotations

from .authority import (
    EntityProfileTemplateRevision,
    WorldAssertion,
    WorldCanonHead,
    WorldCanonRevision,
)
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
    WorldBiblePageTemplate,
    WorldBiblePageTemplateRevision,
    WorldBibleSynopsisHead,
    WorldBibleSynopsisRevision,
    WorldValidationRun,
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
    "EntityProfileTemplateRevision",
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
    "WorldBibleCategory",
    "WorldBiblePage",
    "WorldBiblePageDraft",
    "WorldBiblePageProjection",
    "WorldBiblePageRevision",
    "WorldBiblePageTemplate",
    "WorldBiblePageTemplateRevision",
    "WorldBibleSynopsisHead",
    "WorldBibleSynopsisRevision",
    "WorldValidationRun",
    "WorldAssertion",
    "WorldCanonHead",
    "WorldCanonRevision",
    "WorldEntity",
    "WorldEntityAlias",
    "_ProfileMixin",
]
