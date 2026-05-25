"""World 模块共享辅助函数"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import status as http_status


def parse_uuid(value: str, field_name: str) -> uuid.UUID:
    """将字符串 ID 解析为 UUID"""
    try:
        return uuid.UUID(hex=value)
    except ValueError:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {field_name}: {value}",
        )


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


def merge_string_lists(*values: list[str]) -> list[str]:
    """合并多个字符串列表，去重保序"""
    merged: list[str] = []
    for group in values:
        for item in group:
            if item and item not in merged:
                merged.append(item)
    return merged


def world_entity_types_compatible(left: str | None, right: str | None) -> bool:
    """判断两个 entity_type 是否可合并"""
    left = (left or "other").strip().casefold()
    right = (right or "other").strip().casefold()
    return "other" in {left, right} or left == right
