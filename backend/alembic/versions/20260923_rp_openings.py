"""Persist owner-curated source-bound RP entry cards."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260923_rp_openings"
down_revision = "20260923_rp_reference_refresh"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "interaction_openings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("interaction_source_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("experience_kind", sa.String(32), nullable=False),
        sa.Column("source_setup", sa.JSON(), nullable=False),
        sa.Column("opening_text", sa.Text(), nullable=False),
        sa.Column("image_reference", sa.JSON(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_interaction_openings_novel_id", "interaction_openings", ["novel_id"]
    )
    op.create_index(
        "ix_interaction_openings_source_revision_id",
        "interaction_openings",
        ["source_revision_id"],
    )


def downgrade():
    op.drop_table("interaction_openings")
