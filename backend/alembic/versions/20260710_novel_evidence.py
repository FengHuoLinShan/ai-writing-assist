"""add stable manuscript sources and deterministic evidence provenance

Revision ID: 20260710_novel_evidence
Revises: 20260709_scene_spans_rag_visibility
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa

from alembic import op
from core.base import UUIDType

revision = "20260710_novel_evidence"
down_revision = "20260709_scene_spans_rag_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "writing_drafts" in tables:
        _upgrade_writing_drafts(bind, inspector)
    if "character_knowledge" in tables:
        _upgrade_character_knowledge(inspector)
    if "scene_spans" in tables:
        _upgrade_scene_spans(bind, inspector)
    if "scene_summary_checkpoints" not in tables:
        _create_scene_summary_checkpoints()
    if "rag_chunks" in tables:
        _upgrade_rag_chunks(bind, inspector)
    if "rag_index_state" not in tables:
        _create_rag_index_state()
    if "evidence_links" not in tables:
        _create_evidence_links()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table in ("evidence_links", "rag_index_state", "scene_summary_checkpoints"):
        if table in tables:
            op.drop_table(table)

    if "rag_chunks" in tables:
        op.execute("DROP INDEX IF EXISTS uq_rag_chunks_chapter_text_key")
        op.execute("DROP INDEX IF EXISTS uq_rag_chunks_object_source_key")
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_chunks_chapter_text_key
            ON rag_chunks (
                novel_id, source_type, chapter_index, chunk_index, index_version
            )
            WHERE source_type = 'chapter_text'
              AND chapter_index IS NOT NULL
              AND chunk_index IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_chunks_object_source_key
            ON rag_chunks (
                novel_id, source_type, source_id, chapter_index,
                chunk_index, index_version
            )
            WHERE source_id IS NOT NULL
              AND chunk_index IS NOT NULL
            """
        )
        columns = {column["name"] for column in inspector.get_columns("rag_chunks")}
        indexes = {index["name"] for index in inspector.get_indexes("rag_chunks")}
        if "ix_rag_chunks_source_content_hash" in indexes:
            op.drop_index("ix_rag_chunks_source_content_hash", table_name="rag_chunks")
        if "ix_rag_chunks_content_mode" in indexes:
            op.drop_index("ix_rag_chunks_content_mode", table_name="rag_chunks")
        if "source_content_hash" in columns:
            op.drop_column("rag_chunks", "source_content_hash")
        if "content_mode" in columns:
            op.drop_column("rag_chunks", "content_mode")

    if "scene_spans" in tables:
        constraints = {
            item["name"] for item in inspector.get_unique_constraints("scene_spans")
        }
        if "uq_scene_spans_novel_scene_part" in constraints:
            op.drop_constraint(
                "uq_scene_spans_novel_scene_part",
                "scene_spans",
                type_="unique",
            )
            op.create_unique_constraint(
                "uq_scene_spans_novel_scene_part",
                "scene_spans",
                ["novel_id", "scene_id", "part_no"],
            )
        columns = {column["name"] for column in inspector.get_columns("scene_spans")}
        for name in (
            "anchor_excerpt",
            "anchor_hash",
            "mapping_status",
            "source_content_hash",
            "source_draft_id",
            "content_mode",
        ):
            if name in columns:
                op.drop_column("scene_spans", name)

    if "writing_drafts" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("writing_drafts")}
        if "ix_writing_drafts_content_hash" in indexes:
            op.drop_index("ix_writing_drafts_content_hash", table_name="writing_drafts")
        columns = {column["name"] for column in inspector.get_columns("writing_drafts")}
        if "content_hash" in columns:
            op.drop_column("writing_drafts", "content_hash")

    if "character_knowledge" in tables:
        columns = {
            column["name"] for column in inspector.get_columns("character_knowledge")
        }
        if "is_public_baseline" in columns:
            op.drop_column("character_knowledge", "is_public_baseline")


def _upgrade_writing_drafts(bind, inspector) -> None:  # type: ignore[no-untyped-def]
    columns = {column["name"] for column in inspector.get_columns("writing_drafts")}
    if "content_hash" not in columns:
        op.add_column(
            "writing_drafts",
            sa.Column("content_hash", sa.String(64), nullable=True),
        )
    rows = bind.execute(sa.text("SELECT id, content FROM writing_drafts")).mappings()
    for row in rows:
        digest = hashlib.sha256((row["content"] or "").encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE writing_drafts SET content_hash = :digest WHERE id = :draft_id"
            ),
            {"digest": digest, "draft_id": row["id"]},
        )
    op.alter_column("writing_drafts", "content_hash", nullable=False)
    indexes = {index["name"] for index in inspector.get_indexes("writing_drafts")}
    if "ix_writing_drafts_content_hash" not in indexes:
        op.create_index(
            "ix_writing_drafts_content_hash",
            "writing_drafts",
            ["content_hash"],
        )


def _upgrade_character_knowledge(inspector) -> None:  # type: ignore[no-untyped-def]
    columns = {column["name"] for column in inspector.get_columns("character_knowledge")}
    if "is_public_baseline" not in columns:
        op.add_column(
            "character_knowledge",
            sa.Column(
                "is_public_baseline",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def _upgrade_scene_spans(bind, inspector) -> None:  # type: ignore[no-untyped-def]
    columns = {column["name"] for column in inspector.get_columns("scene_spans")}
    additions = (
        sa.Column(
            "content_mode",
            sa.String(16),
            nullable=False,
            server_default="canonical",
        ),
        sa.Column("source_draft_id", UUIDType, nullable=True),
        sa.Column("source_content_hash", sa.String(64), nullable=True),
        sa.Column(
            "mapping_status",
            sa.String(32),
            nullable=False,
            server_default="chapter_only",
        ),
        sa.Column("anchor_hash", sa.String(64), nullable=True),
        sa.Column("anchor_excerpt", sa.Text(), nullable=True),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("scene_spans", column)
    bind.execute(
        sa.text(
            "UPDATE scene_spans SET content_mode = 'canonical', "
            "mapping_status = 'chapter_only'"
        )
    )
    constraints = {
        item["name"] for item in inspector.get_unique_constraints("scene_spans")
    }
    if "uq_scene_spans_novel_scene_part" in constraints:
        op.drop_constraint(
            "uq_scene_spans_novel_scene_part",
            "scene_spans",
            type_="unique",
        )
    op.create_unique_constraint(
        "uq_scene_spans_novel_scene_part",
        "scene_spans",
        ["novel_id", "scene_id", "content_mode", "part_no"],
    )


def _upgrade_rag_chunks(bind, inspector) -> None:  # type: ignore[no-untyped-def]
    columns = {column["name"] for column in inspector.get_columns("rag_chunks")}
    if "content_mode" not in columns:
        op.add_column(
            "rag_chunks",
            sa.Column(
                "content_mode",
                sa.String(16),
                nullable=False,
                server_default="canonical",
            ),
        )
    if "source_content_hash" not in columns:
        op.add_column(
            "rag_chunks",
            sa.Column("source_content_hash", sa.String(64), nullable=True),
        )
    indexes = {index["name"] for index in inspector.get_indexes("rag_chunks")}
    if "ix_rag_chunks_content_mode" not in indexes:
        op.create_index("ix_rag_chunks_content_mode", "rag_chunks", ["content_mode"])
    if "ix_rag_chunks_source_content_hash" not in indexes:
        op.create_index(
            "ix_rag_chunks_source_content_hash",
            "rag_chunks",
            ["source_content_hash"],
        )
    op.execute("DROP INDEX IF EXISTS uq_rag_chunks_chapter_text_key")
    op.execute("DROP INDEX IF EXISTS uq_rag_chunks_object_source_key")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_rag_chunks_chapter_text_key
        ON rag_chunks (
            novel_id, source_type, content_mode,
            chapter_index, chunk_index, index_version
        )
        WHERE source_type = 'chapter_text'
          AND chapter_index IS NOT NULL
          AND chunk_index IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_rag_chunks_object_source_key
        ON rag_chunks (
            novel_id, source_type, content_mode, source_id,
            chapter_index, chunk_index, index_version
        )
        WHERE source_id IS NOT NULL
          AND chunk_index IS NOT NULL
        """
    )
    # Derived data is intentionally discarded; both modes rebuild from writing_drafts.
    bind.execute(sa.text("DELETE FROM rag_chunks"))


def _create_scene_summary_checkpoints() -> None:
    op.create_table(
        "scene_summary_checkpoints",
        sa.Column("id", UUIDType, primary_key=True),
        sa.Column(
            "novel_id",
            UUIDType,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id",
            UUIDType,
            sa.ForeignKey("scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_mode", sa.String(16), nullable=False),
        sa.Column("through_chapter", sa.Integer(), nullable=False),
        sa.Column(
            "through_offset",
            sa.Integer(),
            nullable=False,
            server_default="-1",
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("based_on_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.UniqueConstraint(
            "novel_id",
            "scene_id",
            "content_mode",
            "through_chapter",
            "through_offset",
            name="uq_scene_summary_checkpoint_cursor",
        ),
    )
    op.create_index(
        "ix_scene_summary_checkpoints_lookup",
        "scene_summary_checkpoints",
        ["novel_id", "scene_id", "content_mode", "through_chapter"],
    )
    op.create_index(
        "ix_scene_summary_checkpoints_novel_id",
        "scene_summary_checkpoints",
        ["novel_id"],
    )
    op.create_index(
        "ix_scene_summary_checkpoints_scene_id",
        "scene_summary_checkpoints",
        ["scene_id"],
    )


def _create_rag_index_state() -> None:
    op.create_table(
        "rag_index_state",
        sa.Column("id", UUIDType, primary_key=True),
        sa.Column(
            "novel_id",
            UUIDType,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("content_mode", sa.String(16), nullable=False),
        sa.Column("requested_source_id", UUIDType, nullable=True),
        sa.Column("requested_hash", sa.String(64), nullable=True),
        sa.Column("indexed_source_id", UUIDType, nullable=True),
        sa.Column("indexed_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.UniqueConstraint(
            "novel_id",
            "chapter_index",
            "content_mode",
            name="uq_rag_index_state_chapter_mode",
        ),
    )
    op.create_index("ix_rag_index_state_novel_id", "rag_index_state", ["novel_id"])
    op.create_index("ix_rag_index_state_status", "rag_index_state", ["status"])


def _create_evidence_links() -> None:
    op.create_table(
        "evidence_links",
        sa.Column("id", UUIDType, primary_key=True),
        sa.Column(
            "novel_id",
            UUIDType,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_ref", sa.JSON(), nullable=False),
        sa.Column("target_hash", sa.String(64), nullable=False),
        sa.Column("claim_path", sa.String(512), nullable=False),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=False),
        sa.Column("precision", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
    )
    op.create_index("ix_evidence_links_novel_id", "evidence_links", ["novel_id"])
    op.create_index(
        "ix_evidence_links_novel_target",
        "evidence_links",
        ["novel_id", "target_hash"],
    )
    op.create_index(
        "ix_evidence_links_novel_status",
        "evidence_links",
        ["novel_id", "status"],
    )
