"""实体类型映射工具

定义 LLM 输出中文类型到系统标准英文类型的映射。
给 extraction_service 共享使用 (candidate_service 已废弃, 直接入库 canonical)。
"""

from __future__ import annotations

SUPPORTED_ENTITY_TYPES: set[str] = {
    "character",
    "location",
    "faction",
    "organization",
    "item",
    "object",
    "event",
    "rule",
    "power_system",
    "secret",
    "legend",
    "resource",
    "concept",
    "creature",
    "skill",
    "ability",
    "artifact",
    "other",
}

# LLM 输出中文 → 系统标准英文类型映射
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
    # 新增类型映射（is_entity_type_valid 已接受）
    "生物": "creature",
    "怪物": "creature",
    "生物/怪物": "creature",
    "技能": "skill",
    "能力": "ability",
    "技能/能力": "skill",
    "神器": "artifact",
    "遗物": "artifact",
    "其他": "other",
}


def map_entity_type(raw_type: str) -> str:
    """将 LLM 输出/中文类型映射为标准英文类型

    如无法映射则返回原始值（由调用方决定是否报错）。
    向后兼容：DB 迁移已将存量 character_ref 转为 character。
    """
    if raw_type == "character_ref":
        return "character"
    return ENTITY_TYPE_MAP.get(raw_type, raw_type)


def is_entity_type_valid(entity_type: str) -> bool:
    """判断实体类型是否为系统支持的标准类型"""

    return entity_type in SUPPORTED_ENTITY_TYPES


def normalize_entity_type(raw_type: str) -> str:
    """规范化实体类型，并拒绝系统不支持的类型。"""
    mapped_type = map_entity_type(raw_type.strip()).strip().lower()
    if not is_entity_type_valid(mapped_type):
        raise ValueError(f"Unsupported entity_type: {raw_type!r}")
    return mapped_type
