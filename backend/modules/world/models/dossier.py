"""World-owned, revisioned dossier entries for core entities."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, text

from .common import (
    JSON,
    PG_UUID,
    Base,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    NovelMixin,
    String,
    Text,
    TimestampMixin,
    UniqueConstraint,
    UUIDMixin,
    mapped_column,
    uuid,
)


class WorldObjectDossierEntry(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """One immutable content revision in a logical dossier-entry history."""

    __tablename__ = "world_object_dossier_entries"
    __table_args__ = (
        CheckConstraint(
            "facing_kind IN ('core', 'project')",
            name="ck_world_dossier_facing_kind",
        ),
        CheckConstraint(
            "(facing_kind = 'core' AND vocabulary_term_id IS NULL) OR "
            "(facing_kind = 'project' AND vocabulary_term_id IS NOT NULL)",
            name="ck_world_dossier_facing_reference",
        ),
        CheckConstraint(
            "source IN ('author', 'author_assistant', 'evolution_adoption', "
            "'spreadsheet_migration', 'legacy_import', 'object_completion')",
            name="ck_world_dossier_source",
        ),
        CheckConstraint(
            "visibility IN ('public', 'secret')",
            name="ck_world_dossier_visibility",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'needs_review', "
            "'covered_by_plot', 'cleared')",
            name="ck_world_dossier_status",
        ),
        CheckConstraint("revision_number >= 1", name="ck_world_dossier_revision_number"),
        CheckConstraint(
            "(start_anchor_kind IS NULL AND start_anchor_id IS NULL) OR "
            "(start_anchor_kind IN ('scene', 'chapter') AND start_anchor_id IS NOT NULL)",
            name="ck_world_dossier_start_anchor",
        ),
        CheckConstraint(
            "(end_anchor_kind IS NULL AND end_anchor_id IS NULL) OR "
            "(end_anchor_kind IN ('scene', 'chapter') AND end_anchor_id IS NOT NULL)",
            name="ck_world_dossier_end_anchor",
        ),
        UniqueConstraint("novel_id", "id", name="uq_world_dossier_novel_id"),
        UniqueConstraint(
            "novel_id",
            "entry_group_id",
            "revision_number",
            name="uq_world_dossier_revision_number",
        ),
        UniqueConstraint(
            "novel_id",
            "entry_group_id",
            "id",
            name="uq_world_dossier_group_revision_id",
        ),
        ForeignKeyConstraint(
            ["novel_id", "entry_group_id", "previous_revision_id"],
            [
                "world_object_dossier_entries.novel_id",
                "world_object_dossier_entries.entry_group_id",
                "world_object_dossier_entries.id",
            ],
            name="fk_world_dossier_previous_revision_same_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["novel_id", "vocabulary_term_id"],
            ["project_vocabulary_terms.novel_id", "project_vocabulary_terms.id"],
            name="fk_world_dossier_vocabulary_same_novel",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_world_dossier_entity_status_facing",
            "novel_id",
            "entity_id",
            "status",
            "facing_kind",
            "facing_key",
        ),
        Index(
            "ix_world_dossier_legacy_field_status",
            "novel_id",
            "entity_id",
            "legacy_field_key",
            "status",
        ),
        Index(
            "uq_world_dossier_active_group",
            "novel_id",
            "entry_group_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        {"comment": "World object dossier entry history"},
    )

    entry_group_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    facing_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    facing_key: Mapped[str] = mapped_column(String(96), nullable=False)
    vocabulary_term_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    legacy_field_key: Mapped[str | None] = mapped_column(String(96), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    legacy_value_json: Mapped[object | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_refs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    quote_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    start_anchor_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    start_anchor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    end_anchor_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    end_anchor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    revision_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    restored_from_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
