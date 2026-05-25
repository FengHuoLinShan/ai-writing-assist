"""辅助函数"""

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


def is_valid_uuid(value: str) -> bool:
    """检查字符串是否为有效的 UUID 格式"""
    try:
        uuid.UUID(hex=value)
        return True
    except (ValueError, AttributeError):
        return False
