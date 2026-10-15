"""Project-scoped vocabulary identities and append-only revisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, UUIDMixin, UUIDType


class ProjectVocabularyTerm(Base, UUIDMixin, NovelMixin):
    """Stable type identity; mutable columns only point at its current revision."""

    __tablename__ = "project_vocabulary_terms"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('space', 'level', 'feature', 'relation', 'transport', "
            "'traveler', 'access_condition', 'dossier_facing', 'faction_form', "
            "'territory_control')",
            name="ck_project_vocabulary_terms_kind",
        ),
        CheckConstraint(
            "source IN ('author', 'model', 'preset')",
            name="ck_project_vocabulary_terms_source",
        ),
        CheckConstraint(
            "status IN ('active', 'emerging', 'archived', 'merged')",
            name="ck_project_vocabulary_terms_status",
        ),
        UniqueConstraint("novel_id", "id", name="uq_project_vocabulary_terms_novel_id"),
        UniqueConstraint(
            "novel_id",
            "preset_id",
            "preset_version",
            "preset_item_key",
            name="uq_project_vocabulary_preset_item",
        ),
        ForeignKeyConstraint(
            ["novel_id", "id", "current_revision_id"],
            [
                "project_vocabulary_revisions.novel_id",
                "project_vocabulary_revisions.term_id",
                "project_vocabulary_revisions.id",
            ],
            name="fk_project_vocabulary_term_current_revision",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["novel_id", "redirect_to_id"],
            ["project_vocabulary_terms.novel_id", "project_vocabulary_terms.id"],
            name="fk_project_vocabulary_term_redirect_same_novel",
        ),
        Index(
            "ix_project_vocabulary_terms_novel_kind_status",
            "novel_id",
            "kind",
            "status",
        ),
    )

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType)
    redirect_to_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    author_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    preset_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    preset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preset_item_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class ProjectVocabularyRevision(Base, UUIDMixin, NovelMixin):
    """Immutable canonical snapshot for a project vocabulary term."""

    __tablename__ = "project_vocabulary_revisions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "id", name="uq_project_vocabulary_revisions_novel_id"
        ),
        UniqueConstraint(
            "novel_id",
            "term_id",
            "id",
            name="uq_project_vocabulary_revision_term_id",
        ),
        UniqueConstraint(
            "novel_id",
            "term_id",
            "revision_number",
            name="uq_project_vocabulary_revision_number",
        ),
        ForeignKeyConstraint(
            ["novel_id", "term_id"],
            ["project_vocabulary_terms.novel_id", "project_vocabulary_terms.id"],
            name="fk_project_vocabulary_revision_term_same_novel",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["novel_id", "term_id", "previous_revision_id"],
            [
                "project_vocabulary_revisions.novel_id",
                "project_vocabulary_revisions.term_id",
                "project_vocabulary_revisions.id",
            ],
            name="fk_project_vocabulary_revision_previous_same_novel",
        ),
        CheckConstraint(
            "revision_number >= 1", name="ck_project_vocabulary_revision_number"
        ),
        Index(
            "ix_project_vocabulary_revisions_novel_term",
            "novel_id",
            "term_id",
            "revision_number",
        ),
    )

    term_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, nullable=True
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
