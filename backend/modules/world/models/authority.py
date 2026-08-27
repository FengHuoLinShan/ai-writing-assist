"""Immutable world authority records and the mutable per-project Canon head."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, event

from .common import (
    JSON,
    PG_UUID,
    Base,
    DateTime,
    ForeignKey,
    Integer,
    Mapped,
    String,
    TimestampMixin,
    UniqueConstraint,
    UUIDMixin,
    mapped_column,
)


class WorldAssertion(Base, UUIDMixin):
    __tablename__ = "world_assertions"
    __table_args__ = (
        CheckConstraint(
            "regime_kind IN ('world', 'belief')", name="ck_world_assertion_regime"
        ),
        CheckConstraint(
            "polarity IN ('positive', 'negative')", name="ck_world_assertion_polarity"
        ),
        CheckConstraint(
            "(regime_kind = 'world' AND belief_holder_entity_id IS NULL) OR "
            "(regime_kind = 'belief' AND belief_holder_entity_id IS NOT NULL)",
            name="ck_world_assertion_belief_holder",
        ),
        UniqueConstraint("id", "novel_id", name="uq_world_assertion_id_novel"),
        UniqueConstraint(
            "novel_id", "content_hash", name="uq_world_assertion_content_hash"
        ),
        {"comment": "Immutable author-admitted world assertion"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    regime_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    belief_holder_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    statement_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    statement_version: Mapped[int] = mapped_column(Integer, nullable=False)
    statement_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    schema_ref_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    time_scope_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_revision_ref_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    hard_ground_refs_json: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    cite_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provenance_actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorldCanonRevision(Base, UUIDMixin):
    __tablename__ = "world_canon_revisions"
    __table_args__ = (
        UniqueConstraint("id", "novel_id", name="uq_world_canon_revision_id_novel"),
        ForeignKeyConstraint(
            ["parent_id", "novel_id"],
            ["world_canon_revisions.id", "world_canon_revisions.novel_id"],
            ondelete="CASCADE",
            name="fk_world_canon_parent_same_novel",
        ),
        {"comment": "Immutable complete world Canon manifest"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    kernel_spec_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    admission_receipt_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorldCanonHead(Base):
    __tablename__ = "world_canon_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["canon_revision_id", "novel_id"],
            ["world_canon_revisions.id", "world_canon_revisions.novel_id"],
            ondelete="CASCADE",
            name="fk_world_canon_head_same_novel",
        ),
        {"comment": "Mutable per-project CAS pointer to the current Canon revision"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    canon_revision_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False
    )
    head_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EntityProfileTemplateRevision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "entity_profile_template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "version_number", name="uq_entity_profile_template_revision"
        ),
        UniqueConstraint(
            "id", "novel_id", name="uq_entity_profile_template_revision_id_novel"
        ),
        {"comment": "Immutable typed entity profile schema revision"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("entity_profile_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_type: Mapped[str] = mapped_column(String(64), nullable=False)
    template_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    display_schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


def _reject_immutable_write(_mapper, _connection, target) -> None:  # noqa: ANN001
    raise ValueError(f"{type(target).__name__} is immutable")


for _immutable_model in (
    WorldAssertion,
    WorldCanonRevision,
    EntityProfileTemplateRevision,
):
    event.listen(_immutable_model, "before_update", _reject_immutable_write)
    event.listen(_immutable_model, "before_delete", _reject_immutable_write)
