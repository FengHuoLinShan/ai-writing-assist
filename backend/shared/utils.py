"""
共享工具函数

包含 UUID 解析、验证等跨模块通用工具。
所有模块应使用此文件的函数，而非各自重复实现。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import status as http_status


def parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    """将字符串 ID 解析为 UUID，格式错误时抛出 422

    Args:
        value: UUID 字符串（hex 格式）
        field_name: 字段名（用于错误提示）

    Returns:
        uuid.UUID

    Raises:
        HTTPException 422: UUID 格式无效
    """
    try:
        return uuid.UUID(hex=value)
    except ValueError:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid {field_name}: {value}",
        )


def is_valid_uuid(value: str) -> bool:
    """检查字符串是否为有效的 UUID 格式

    Args:
        value: 待检查的字符串

    Returns:
        True 如果字符串是有效 UUID，否则 False
    """
    try:
        uuid.UUID(hex=value)
        return True
    except (ValueError, AttributeError):
        return False
