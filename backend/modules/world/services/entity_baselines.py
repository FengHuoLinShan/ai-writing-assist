"""CoreEntity / EntityRelation 行基线快照 — world 内共享词汇。

AO-5 / ADR-0031：候选基线（candidate baseline）的字段快照映射是 CoreEntity
与 EntityRelation 行的领域形状，core（候选整理）与 worldbuilding（聚焦采用、
回执逆序回滚）两侧都消费。原定义在 ``services/worldbuilding/
applied_change_reversal``，现上移 world services 共享根；原位置保留兼容
再出口。
"""

from __future__ import annotations

import copy

ENTITY_STATE_KEYS = (
    "name",
    "entity_type",
    "status",
    "summary",
    "public_info",
    "hidden_truth",
    "content_json",
    "importance",
    "importance_level",
    "reveal_level",
)
RELATION_STATE_KEYS = (
    "status",
    "relation_type",
    "relation_kind",
    "description",
    "quote",
    "review_meta",
)
CHARACTER_STATE_KEYS = (
    "name",
    "status",
    "role",
    "appearance",
    "personality",
    "desire",
    "fear",
    "weakness",
    "current_goal",
    "current_state",
    "stance",
    "voice_style",
    "relationship_summary",
    "secret",
    "meta",
)


def entity_state(entity) -> dict:
    return {key: copy.deepcopy(getattr(entity, key)) for key in ENTITY_STATE_KEYS}


def relation_state(relation) -> dict:
    return {key: copy.deepcopy(getattr(relation, key)) for key in RELATION_STATE_KEYS}


def character_state(character) -> dict:
    return {key: copy.deepcopy(getattr(character, key)) for key in CHARACTER_STATE_KEYS}
