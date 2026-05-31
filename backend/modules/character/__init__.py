"""modules/character — 人物档案与知识边界模块

负责人物档案、人物状态、人物关系摘要和人物知识边界。
"""

from __future__ import annotations

from modules.character.models import Character, CharacterKnowledge

__all__ = [
    "Character",
    "CharacterKnowledge",
]
