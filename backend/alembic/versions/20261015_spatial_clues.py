"""add reviewed spatial clue candidates

Revision ID: 20261015_spatial_clues
Revises: 20261015_map_spatial_v2
Create Date: 2026-10-15 14:49:02.863649
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261015_spatial_clues"
down_revision: str | None = "20261015_map_spatial_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "map_spatial_clues",
        sa.Column("run_id", sa.String(length=120), nullable=False),
        sa.Column("attempt_id", sa.String(length=120), nullable=False),
        sa.Column("scene_id", sa.String(length=128), nullable=False),
        sa.Column("scene_index", sa.Integer(), nullable=False),
        sa.Column("clue_key", sa.String(length=64), nullable=False),
        sa.Column("source_manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("method_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_content_mode", sa.String(length=16), nullable=False),
        sa.Column("source_binding", sa.JSON(), nullable=False),
        sa.Column("clue_payload", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("verification_note", sa.Text(), nullable=True),
        sa.Column("merged_into_id", sa.UUID(), nullable=True),
        sa.Column("decision_action", sa.String(length=16), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "source_content_mode IN ('canonical', 'working')",
            name="ck_map_spatial_clues_source_content_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'pending_verification', 'adopted', "
            "'rejected', 'superseded')",
            name="ck_map_spatial_clues_status",
        ),
        sa.CheckConstraint("scene_index >= 0", name="ck_map_spatial_clues_scene_index"),
        sa.ForeignKeyConstraint(
            ["novel_id", "merged_into_id"],
            ["map_spatial_clues.novel_id", "map_spatial_clues.id"],
            name="fk_map_spatial_clues_merge_same_novel",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("novel_id", "id", name="uq_map_spatial_clues_novel_id"),
        sa.UniqueConstraint(
            "novel_id",
            "run_id",
            "attempt_id",
            "clue_key",
            name="uq_map_spatial_clues_attempt_key",
        ),
    )
    op.create_index(
        op.f("ix_map_spatial_clues_novel_id"),
        "map_spatial_clues",
        ["novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_spatial_clues_novel_scene",
        "map_spatial_clues",
        ["novel_id", "scene_index", "id"],
        unique=False,
    )
    op.create_index(
        "ix_map_spatial_clues_novel_status_scene",
        "map_spatial_clues",
        ["novel_id", "status", "scene_index", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_map_spatial_clues_status"), "map_spatial_clues", ["status"], unique=False
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM map_spatial_clues)"))
        .scalar()
    ):
        raise RuntimeError(
            "Spatial clue candidates exist; downgrade would discard author data"
        )
    op.drop_index(op.f("ix_map_spatial_clues_status"), table_name="map_spatial_clues")
    op.drop_index(
        "ix_map_spatial_clues_novel_status_scene", table_name="map_spatial_clues"
    )
    op.drop_index("ix_map_spatial_clues_novel_scene", table_name="map_spatial_clues")
    op.drop_index(op.f("ix_map_spatial_clues_novel_id"), table_name="map_spatial_clues")
    op.drop_table("map_spatial_clues")
