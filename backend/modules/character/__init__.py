"""modules/character — 人物档案与知识边界模块

负责人物档案、人物状态、人物关系摘要和人物知识边界。
"""

from __future__ import annotations

from modules.character.contracts import CharacterContract, CharacterKnowledgeContract
from modules.character.facade import (
    create_character,
    filter_context_by_character_knowledge,
    find_character_id_by_name,
    get_character_knowledge_context,
    get_characters_context,
)
from modules.character.models import Character, CharacterKnowledge
from modules.character.schemas import (
    CharacterContextBundle,
    CharacterCreate,
    CharacterKnowledgeContext,
    CharacterKnowledgeCreate,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterResponse,
    CharacterUpdate,
)

__all__ = [
    "Character",
    "CharacterKnowledge",
    "CharacterContract",
    "CharacterKnowledgeContract",
    "CharacterContextBundle",
    "CharacterKnowledgeContext",
    "CharacterCreate",
    "CharacterUpdate",
    "CharacterResponse",
    "CharacterKnowledgeCreate",
    "CharacterKnowledgeUpdate",
    "CharacterKnowledgeResponse",
    "get_characters_context",
    "get_character_knowledge_context",
    "filter_context_by_character_knowledge",
    "find_character_id_by_name",
    "create_character",
]
