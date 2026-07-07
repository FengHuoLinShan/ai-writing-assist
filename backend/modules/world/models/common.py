"""Shared imports and helpers for world ORM model modules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin

__all__ = [
    "Base",
    "Boolean",
    "Computed",
    "DateTime",
    "Float",
    "ForeignKey",
    "Index",
    "Integer",
    "JSON",
    "Mapped",
    "NovelMixin",
    "PG_UUID",
    "StatusMixin",
    "String",
    "Text",
    "TimestampMixin",
    "UUIDMixin",
    "UniqueConstraint",
    "_HAS_PGVECTOR",
    "_vector_column",
    "datetime",
    "func",
    "mapped_column",
    "relationship",
    "uuid",
    "UTC",
]

try:
    import pgvector.sqlalchemy  # type: ignore[import-untyped]  # noqa: F401

    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False


def _vector_column(dim: int = 768):
    """返回 pgvector Vector 列或 Text 回退列（用于 SQLite 测试）"""
    if _HAS_PGVECTOR:
        from pgvector.sqlalchemy import Vector

        return mapped_column(Vector(dim), nullable=True)
    return mapped_column(Text, nullable=True, comment="embedding 向量（JSON 序列化）")
