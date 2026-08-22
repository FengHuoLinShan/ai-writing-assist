"""Shared review-queue type catalog and deterministic fingerprints."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from shared.enums import RelationType

RELATION_KINDS = (
    "state",
    "social",
    "spatial",
    "causal",
    "temporal",
    "epistemic",
    "intentional",
)
ALIAS_KINDS = ("name", "title", "identity")

_RELATION_KIND_CATALOG = [
    (
        "state",
        "状态/结构",
        "所有、组成、隶属、控制、依赖、承载或其它持续结构事实。",
    ),
    (
        "social",
        "社会/组织",
        "由亲属、角色、成员身份、合作、冲突或服务形成的关系。",
    ),
    (
        "spatial",
        "空间",
        "位于、包含、相邻、连接、经过或携带等位置与拓扑关系。",
    ),
    (
        "causal",
        "因果",
        "一方创造、导致、促成、阻止、改变或修复另一方。",
    ),
    (
        "temporal",
        "时序",
        "先于、后于、同时、继承、延续或阶段顺序。",
    ),
    (
        "epistemic",
        "认知",
        "知道、相信、怀疑、观察、提及、揭示、隐藏或误认。",
    ),
    (
        "intentional",
        "意图",
        "寻找、计划、选择、追求、支持、反对、保护、使用或回避。",
    ),
]

_ALIAS_KIND_CATALOG = [
    (
        "name",
        "名称",
        "同一对象的名称、昵称、简称、译名、古称等语言标签变化。",
    ),
    (
        "title",
        "称谓",
        "由地位、职位、等级、荣誉或社会角色产生的称号与称呼。",
    ),
    (
        "identity",
        "身份",
        "化身、伪装、前世、秘密身份、公开身份或形态等身份名称。",
    ),
]

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

_STANDARD_RELATION_KINDS = {
    **{
        value: "social"
        for value in (
            "parent_of",
            "child_of",
            "spouse_of",
            "sibling_of",
            "friend_of",
            "rival_of",
            "enemy_of",
            "ally_of",
            "mentor_of",
            "student_of",
            "lover_of",
            "master_of",
            "servant_of",
            "member_of",
            "leader_of",
            "allied_with",
            "at_war_with",
            "trading_with",
        )
    },
    "belongs_to": "state",
    "created_by": "causal",
    "located_at": "spatial",
    "contains": "spatial",
    "controls": "state",
    "related_to": "state",
    "opposes": "intentional",
    "supports": "intentional",
}

_CUSTOM_RELATION_KINDS = {
    **{
        value: "social"
        for value in (
            "sibling",
            "成员",
            "acquaintance",
            "colleague_of",
            "family",
            "tenant_of",
            "兄妹",
            "同事",
            "塔罗会成员",
            "师生",
            "customer",
            "daughter_of",
            "engaged_to",
            "family_member",
            "membership",
            "mentors",
            "pet_of",
            "ruler_of",
            "serves",
            "subordinate_of",
            "supervisor_of",
            "teacher_of",
            "上下级",
            "下属",
            "乘客",
            "兄弟",
            "占卜服务",
            "同伴",
            "同学",
            "宣称后裔",
            "就读于",
            "师从",
            "并肩作战",
            "执行者",
            "教导",
            "朋友",
            "未婚夫妻",
            "船长",
            "领导",
            "交易对手",
        )
    },
    **{
        value: "spatial"
        for value in (
            "located_in",
            "位于",
            "包含",
            "has_on_desk",
            "举办地点",
            "携带",
        )
    },
    **{
        value: "causal"
        for value in (
            "derived_from",
            "causes",
            "founded",
            "founds",
            "key_to",
            "以命名者命名",
            "修复",
            "修理",
            "创造了",
            "基础",
            "来源",
            "配制",
        )
    },
    "sequence_progression": "temporal",
    "subsequent_sequence": "temporal",
    **{
        value: "epistemic"
        for value in (
            "knows_about",
            "提及",
            "mentions",
            "verified",
            "contains_information",
            "knows",
            "reads",
            "suspects",
            "占卜与被占卜",
            "感知",
            "被注视",
            "被观测",
            "猜测的穿越者前辈",
            "理论认同",
        )
    },
    **{
        value: "intentional"
        for value in (
            "seeks",
            "chooses",
            "collects",
            "consumes",
            "performs",
            "plans",
            "pursuit",
            "uses",
            "被跟踪",
            "访问",
            "选择了",
            "支持",
            "服食",
        )
    },
}

_ALIAS_KIND_BY_TYPE = {
    **{
        value: "title"
        for value in ("title", "称号", "头衔", "尊称", "职称", "塔罗会称号")
    },
    **{
        value: "identity"
        for value in ("identity", "伪装", "伪装身份", "官方身份", "形态", "穿越前身份")
    },
    "name": "name",
    "nickname": "name",
    "alias": "name",
    "translation": "name",
    "abbreviation": "name",
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


def default_relation_kind(value: str | None) -> str | None:
    """Return a deterministic default without changing the detailed type."""
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    suggested = suggest_relation_type(value)
    if suggested:
        return _STANDARD_RELATION_KINDS.get(suggested)
    return _CUSTOM_RELATION_KINDS.get(normalized)


def default_alias_kind(value: str | None) -> str | None:
    """Return a deterministic default without changing the detailed type."""
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return None
    suggested = suggest_alias_type(value)
    if suggested:
        return _ALIAS_KIND_BY_TYPE.get(suggested)
    return _ALIAS_KIND_BY_TYPE.get(normalized)


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
                "default_kind": _STANDARD_RELATION_KINDS[relation_type.value],
            }
        )
    alias_types = [
        {
            "value": value,
            "label": label,
            "category": "别名",
            "synonyms": synonyms,
            "default_kind": _ALIAS_KIND_BY_TYPE[value],
        }
        for value, label, synonyms in _ALIAS_CATALOG
    ]
    return {
        "version": 2,
        "custom_allowed": True,
        "relation_kinds": [
            {"value": value, "label": label, "description": description}
            for value, label, description in _RELATION_KIND_CATALOG
        ],
        "alias_kinds": [
            {"value": value, "label": label, "description": description}
            for value, label, description in _ALIAS_KIND_CATALOG
        ],
        "relation_types": relation_types,
        "alias_types": alias_types,
    }
