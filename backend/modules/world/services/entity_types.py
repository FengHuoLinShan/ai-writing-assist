"""实体类型映射工具

定义 LLM 输出中文类型到系统标准英文类型的映射。
给 extraction_service 和 candidate_service 共享使用。
"""

from __future__ import annotations

# LLM 输出中文 → 系统标准英文类型映射
ENTITY_TYPE_MAP: dict[str, str] = {
    "人物": "character_ref", "人": "character_ref", "角色": "character_ref",
    "地点": "location", "场所": "location", "位置": "location",
    "组织": "faction", "势力": "faction", "派系": "faction",
    "物品": "item", "道具": "item", "物品/装备": "item",
    "事件": "event", "事件/活动": "event",
    "规则": "rule", "规则/系统": "rule",
    "力量体系": "power_system", "超凡体系": "power_system",
    "秘密": "secret", "秘密/真相": "secret",
    "概念": "secret", "设定": "secret",
    "传说": "legend", "传说/神话": "legend",
    "资源": "resource", "资源/材料": "resource",
}


def map_entity_type(raw_type: str) -> str:
    """将 LLM 输出/中文类型映射为标准英文类型

    如无法映射则返回原始值（由调用方决定是否报错）。
    """
    return ENTITY_TYPE_MAP.get(raw_type, raw_type)


def is_entity_type_valid(entity_type: str) -> bool:
    """判断实体类型是否为系统支持的标准类型"""
    import re
    return bool(re.match(
        r"^(location|faction|item|event|rule|power_system|secret|legend|resource|character_ref)$",
        entity_type,
    ))
