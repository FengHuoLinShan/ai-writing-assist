"""共享字面量类型与内部校验工具。"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BeforeValidator

RelationKind = Literal[
    "state",
    "social",
    "spatial",
    "causal",
    "temporal",
    "epistemic",
    "intentional",
]
AliasKind = Literal["name", "title", "identity"]

# ============================================================
# 内部工具
# ============================================================


def _uuid_validator(v: object) -> str:
    """将 UUID 原始值转为字符串"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


def _optional_uuid_validator(v: object) -> str | None:
    """将可空 UUID 转为字符串"""
    if v is None:
        return None
    return _uuid_validator(v)


UuidStr = Annotated[str, BeforeValidator(_uuid_validator)]
OptionalUuidStr = Annotated[str | None, BeforeValidator(_optional_uuid_validator)]


def _validate_lower_sha256(value: str, field_name: str) -> str:
    if value != value.lower() or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _normalize_system_entity_type(v: str) -> str:
    """Lazy import to avoid schemas <-> services package initialization cycles."""
    from modules.world.services.core.entity_types import normalize_system_entity_type

    return normalize_system_entity_type(v)


def _normalize_author_entity_type(v: str) -> str:
    from modules.world.services.core.entity_types import normalize_author_entity_type

    return normalize_author_entity_type(v)
