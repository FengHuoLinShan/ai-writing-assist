"""世界对象类型目录与边界校验。"""

from __future__ import annotations

import unicodedata

SYSTEM_ENTITY_TYPE_CATALOG: tuple[tuple[str, str], ...] = (
    ("character", "人物"),
    ("location", "地点"),
    ("faction", "势力/派系"),
    ("organization", "组织"),
    ("species", "种族"),
    ("group", "群体"),
    ("item", "物品"),
    ("object", "物体"),
    ("event", "事件"),
    ("rule", "规则"),
    ("power_system", "力量体系"),
    ("secret", "秘密/真相"),
    ("legend", "传说/神话"),
    ("resource", "资源/材料"),
    ("concept", "概念"),
    ("creature", "生物/怪物"),
    ("skill", "技能"),
    ("ability", "能力"),
    ("artifact", "神器/遗物"),
    ("other", "其他"),
)

SUPPORTED_ENTITY_TYPES: set[str] = {value for value, _label in SYSTEM_ENTITY_TYPE_CATALOG}
RESERVED_AUTHOR_ENTITY_TYPES = {
    "__custom_entity_type__",
    "__new_custom_type__",
    "system",
    "custom",
}

ENTITY_TYPE_MAP: dict[str, str] = {
    "人物": "character",
    "人": "character",
    "角色": "character",
    "地点": "location",
    "场所": "location",
    "位置": "location",
    "组织": "organization",
    "势力": "faction",
    "派系": "faction",
    "势力/派系": "faction",
    "种族": "species",
    "族群": "species",
    "群体": "group",
    "团体": "group",
    "物品": "item",
    "道具": "item",
    "物品/装备": "item",
    "物体": "object",
    "对象": "object",
    "事件": "event",
    "事件/活动": "event",
    "规则": "rule",
    "规则/系统": "rule",
    "力量体系": "power_system",
    "超凡体系": "power_system",
    "秘密": "secret",
    "秘密/真相": "secret",
    "概念": "concept",
    "概念（抽象）": "concept",
    "设定": "secret",
    "传说": "legend",
    "传说/神话": "legend",
    "资源": "resource",
    "资源/材料": "resource",
    "生物": "creature",
    "怪物": "creature",
    "生物/怪物": "creature",
    "技能": "skill",
    "能力": "ability",
    "技能/能力": "skill",
    "rule/power_system": "rule",
    "secret/legend": "secret",
    "神器": "artifact",
    "遗物": "artifact",
    "神器/遗物": "artifact",
    "其他": "other",
}


def map_entity_type(raw_type: str) -> str:
    """映射兼容别名；未知值原样返回。"""
    if raw_type == "character_ref":
        return "character"
    return ENTITY_TYPE_MAP.get(raw_type, raw_type)


def is_entity_type_valid(entity_type: str) -> bool:
    return entity_type in SUPPORTED_ENTITY_TYPES


def normalize_system_entity_type(raw_type: str) -> str:
    """系统/AI 边界：只接受固定目录。"""
    mapped_type = map_entity_type(raw_type.strip()).strip().lower()
    if not is_entity_type_valid(mapped_type):
        raise ValueError(f"Unsupported entity_type: {raw_type!r}")
    return mapped_type


def normalize_author_entity_type(raw_type: str) -> str:
    """作者边界：兼容系统别名，并允许安全的 1-64 字符自定义类型。"""
    normalized = raw_type.strip()
    if not normalized:
        raise ValueError("entity_type must not be empty")
    mapped = map_entity_type(normalized)
    candidate = mapped.lower()
    if len(candidate) > 64:
        raise ValueError("entity_type must be at most 64 characters")
    if candidate.casefold() in RESERVED_AUTHOR_ENTITY_TYPES:
        raise ValueError(f"Reserved entity_type: {raw_type!r}")
    if any(unicodedata.category(char) in {"Cc", "Cf"} for char in candidate):
        raise ValueError("entity_type must not contain control characters")
    return candidate


# 兼容已有 AI/提取调用方；新增作者入口必须显式使用 author 版本。
normalize_entity_type = normalize_system_entity_type
