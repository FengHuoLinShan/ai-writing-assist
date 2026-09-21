"""Derived assessments and complete host-owned dependency receipts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin, UUIDType


class ForecastCandidate(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_forecast_candidates"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("novel_id", "run_id", "ordinal"),
        ForeignKeyConstraint(
            ["novel_id", "run_id"],
            ["assistant_runs.novel_id", "assistant_runs.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("ordinal >= 0 AND ordinal < 64"),
        CheckConstraint("validation_state IN ('valid','stale','revoked','expired')"),
        Index(
            "ix_forecast_issue_latest",
            "novel_id",
            "audience_key",
            "scope_hash",
            "issue_key",
            "created_at",
        ),
        Index("ix_forecast_expiry", "novel_id", "validation_state", "expires_at"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    ordinal: Mapped[int] = mapped_column(Integer)
    issue_key: Mapped[str] = mapped_column(String(160))
    audience_key: Mapped[str] = mapped_column(String(160))
    scope_hash: Mapped[str] = mapped_column(String(64))
    context_hash: Mapped[str] = mapped_column(String(64))
    assessment_hash: Mapped[str] = mapped_column(String(64))
    capability_id: Mapped[str] = mapped_column(String(100))
    protocol_version: Mapped[str] = mapped_column(String(32), default="forecast_v1")
    output_kind: Mapped[str] = mapped_column(String(32))
    tier: Mapped[str] = mapped_column(String(16))
    policy_generation: Mapped[int] = mapped_column(Integer)
    validation_state: Mapped[str] = mapped_column(String(16), default="valid")
    payload_json: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ForecastDependency(Base):
    __tablename__ = "assistant_forecast_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "candidate_id"],
            [
                "assistant_forecast_candidates.novel_id",
                "assistant_forecast_candidates.id",
            ],
            ondelete="CASCADE",
        ),
        Index(
            "ix_forecast_dependency_source", "novel_id", "resource_kind", "resource_id"
        ),
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True)
    dependency_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    novel_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    resource_kind: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    revision_token: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32))
    required: Mapped[bool] = mapped_column(default=True)
    scope_stamp: Mapped[str] = mapped_column(String(64))
