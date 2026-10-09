"""Persist derived themes and immutable revisions; no Canon writes or backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261008_evolution_ledger"
down_revision = "20261008_writing_recompute_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evolution_ledger_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin_key", sa.String(64), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("head_revision", sa.Integer(), nullable=False),
        sa.Column("author_decision_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("novel_id", "origin_key", name="uq_evolution_ledger_origin"),
        sa.UniqueConstraint("id", "novel_id", name="uq_evolution_ledger_identity"),
    )
    op.create_index(
        "ix_evolution_ledger_entries_novel_id", "evolution_ledger_entries", ["novel_id"]
    )
    op.create_table(
        "evolution_ledger_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_id", UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("operation_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("scene_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("body_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["entry_id", "novel_id"],
            ["evolution_ledger_entries.id", "evolution_ledger_entries.novel_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("entry_id", "revision", name="uq_evolution_ledger_revision"),
        sa.UniqueConstraint(
            "novel_id", "operation_key", name="uq_evolution_ledger_operation"
        ),
    )
    op.create_index(
        "ix_evolution_ledger_revisions_novel_id",
        "evolution_ledger_revisions",
        ["novel_id"],
    )
    op.create_index(
        "ix_evolution_ledger_scene",
        "evolution_ledger_revisions",
        ["novel_id", "scene_index"],
    )


def downgrade():
    op.drop_table("evolution_ledger_revisions")
    op.drop_table("evolution_ledger_entries")
