"""World 模块共享辅助函数"""

from __future__ import annotations

from shared.utils import parse_uuid  # noqa: F401


def normalize_name(value: str) -> str:
    """标准化名称用于匹配：去除特殊字符后 casefold"""
    normalized = value.casefold()
    for token in ("·", "•", "-", "_", " ", "（", "）", "(", ")", "　"):
        normalized = normalized.replace(token, "")
    return normalized


def merge_text_field(current: str | None, incoming: str | None) -> str:
    """合并两个文本字段：不覆盖非空已有内容，只追加"""
    current_text = (current or "").strip()
    incoming_text = (incoming or "").strip()
    if not incoming_text:
        return current_text
    if not current_text:
        return incoming_text
    if incoming_text == current_text or incoming_text in current_text:
        return current_text
    return f"{current_text}\n\n{incoming_text}"


def world_entity_types_compatible(left: str | None, right: str | None) -> bool:
    """判断两个 entity_type 是否可合并"""
    left = (left or "other").strip().casefold()
    right = (right or "other").strip().casefold()
    return "other" in {left, right} or left == right
