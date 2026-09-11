"""
共享工具函数

包含 UUID 解析、验证等跨模块通用工具。
所有模块应使用此文件的函数，而非各自重复实现。
"""

from __future__ import annotations

import re
import uuid

from core.errors import ValidationError as DomainValidationError


def parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    """将字符串 ID 解析为 UUID，格式错误时抛出 422

    Args:
        value: UUID 字符串（hex 格式）
        field_name: 字段名（用于错误提示）

    Returns:
        uuid.UUID

    Raises:
        DomainValidationError 422: UUID 格式无效
    """
    try:
        return uuid.UUID(hex=value)
    except ValueError:
        raise DomainValidationError(
            f"Invalid {field_name}: {value}",
            status_code=422,
        )

def retrieval_question_text(value: str) -> str:
    """Remove citation-request boilerplate only; source visibility is unchanged."""
    value = re.sub(
        r"请(?:给出|提供|附上)(?:相关|对应|明确的?)?(?:章节依据|章节出处|原文依据)[。！!]?",
        " ",
        value,
    )
    value = re.sub(r"请引用第[0-9一二三四五六七八九十百]+章[。！!]?", " ", value)
    value = re.sub(r"^前\s*\d+\s*章[中里]?[，,\s]*", "", value)
    return value.strip()
