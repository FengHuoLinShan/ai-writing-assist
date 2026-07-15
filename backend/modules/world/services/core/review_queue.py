"""Shared review-queue type catalog and deterministic fingerprints."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from shared.enums import RelationType

_RELATION_LABELS = {
    "parent_of": ("父母/长辈", "人物"),
    "child_of": ("子女/晚辈", "人物"),
    "spouse_of": ("配偶", "人物"),
    "sibling_of": ("兄弟姐妹", "人物"),
    "friend_of": ("朋友", "人物"),
    "rival_of": ("竞争对手", "人物"),
    "enemy_of": ("敌人", "人物"),
    "ally_of": ("盟友", "人物"),
    "mentor_of": ("导师", "人物"),
    "student_of": ("学生", "人物"),
    "lover_of": ("恋人", "人物"),
    "master_of": ("主人", "人物"),
    "servant_of": ("仆从", "人物"),
    "member_of": ("成员", "势力"),
    "leader_of": ("领导者", "势力"),
    "allied_with": ("结盟", "势力"),
    "at_war_with": ("交战", "势力"),
    "trading_with": ("贸易", "势力"),
    "belongs_to": ("属于", "对象"),
    "created_by": ("由其创造", "对象"),
    "located_at": ("位于", "对象"),
    "contains": ("包含", "对象"),
    "controls": ("控制", "对象"),
    "related_to": ("相关", "通用"),
    "opposes": ("反对", "通用"),
    "supports": ("支持", "通用"),
}

_RELATION_SYNONYMS = {
    "sibling": "sibling_of",
    "兄妹": "sibling_of",
    "兄弟": "sibling_of",
    "姐妹": "sibling_of",
    "friend": "friend_of",
    "朋友": "friend_of",
    "enemy": "enemy_of",
    "敌人": "enemy_of",
    "敌对": "enemy_of",
    "ally": "ally_of",
    "盟友": "ally_of",
    "同盟": "ally_of",
    "member": "member_of",
    "成员": "member_of",
    "leader": "leader_of",
    "领导者": "leader_of",
    "位于": "located_at",
    "包含": "contains",
    "相关": "related_to",
}

_ALIAS_CATALOG = [
    ("name", "名称", ["名称", "本名", "姓名"]),
    ("title", "称号", ["称号", "头衔"]),
    ("nickname", "昵称", ["昵称", "绰号"]),
    ("alias", "别名", ["别称", "别名", "化名"]),
    ("translation", "译名", ["译名"]),
    ("abbreviation", "缩写", ["缩写", "简称"]),
]

_ALIAS_SYNONYMS = {
    synonym.casefold(): value
    for value, _label, synonyms in _ALIAS_CATALOG
    for synonym in synonyms
}


def stable_fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def suggest_relation_type(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    casefolded = normalized.casefold()
    canonical = {item.value.casefold(): item.value for item in RelationType}
    return canonical.get(casefolded) or _RELATION_SYNONYMS.get(casefolded)


def suggest_alias_type(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    canonical = {item[0].casefold(): item[0] for item in _ALIAS_CATALOG}
    return canonical.get(normalized.casefold()) or _ALIAS_SYNONYMS.get(
        normalized.casefold()
    )


def review_type_catalog() -> dict[str, Any]:
    relation_synonyms: dict[str, list[str]] = {}
    for synonym, value in _RELATION_SYNONYMS.items():
        relation_synonyms.setdefault(value, []).append(synonym)
    relation_types = []
    for relation_type in RelationType:
        label, category = _RELATION_LABELS[relation_type.value]
        relation_types.append(
            {
                "value": relation_type.value,
                "label": label,
                "category": category,
                "synonyms": sorted(relation_synonyms.get(relation_type.value, [])),
            }
        )
    alias_types = [
        {
            "value": value,
            "label": label,
            "category": "别名",
            "synonyms": synonyms,
        }
        for value, label, synonyms in _ALIAS_CATALOG
    ]
    return {
        "version": 1,
        "custom_allowed": True,
        "relation_types": relation_types,
        "alias_types": alias_types,
    }
