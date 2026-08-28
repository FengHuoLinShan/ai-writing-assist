"""Immutable world authority persistence owned by the world module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, UUIDMixin, UUIDType


class WorldAssertion(Base, UUIDMixin):
    __tablename__ = "world_assertions"
    __table_args__ = (
        UniqueConstraint("novel_id", "content_digest", name="uq_world_assertion_digest"),
        CheckConstraint(
            "regime = 'objective_world.v1'", name="ck_world_assertions_regime"
        ),
        CheckConstraint(
            "polarity IN ('positive', 'negative')",
            name="ck_world_assertions_polarity",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    regime: Mapped[str] = mapped_column(String(64), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    statement_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    time_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    hard_ground_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False
    )
    provenance_actor_ref_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class WorldCanonRevision(Base, UUIDMixin):
    __tablename__ = "world_canon_revisions"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_world_canon_revision_novel_id"),
        UniqueConstraint(
            "novel_id", "version_number", name="uq_world_canon_revision_version"
        ),
        UniqueConstraint(
            "novel_id", "decision_id", name="uq_world_canon_revision_decision"
        ),
        ForeignKeyConstraint(
            ["novel_id", "parent_revision_id"],
            ["world_canon_revisions.novel_id", "world_canon_revisions.id"],
            ondelete="CASCADE",
            name="fk_world_canon_revision_parent_same_novel",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    decision_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    decision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class WorldCanonHead(Base):
    __tablename__ = "world_canon_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "current_revision_id"],
            ["world_canon_revisions.novel_id", "world_canon_revisions.id"],
            ondelete="CASCADE",
            name="fk_world_canon_head_revision_same_novel",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    current_revision_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class EntityProfileTemplateRevision(Base, UUIDMixin):
    __tablename__ = "entity_profile_template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_entity_profile_template_revision",
        ),
        ForeignKeyConstraint(
            ["novel_id", "template_id"],
            ["entity_profile_templates.novel_id", "entity_profile_templates.id"],
            ondelete="CASCADE",
            name="fk_profile_template_revision_same_novel",
        ),
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    revision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
