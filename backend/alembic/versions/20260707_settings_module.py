"""create settings module tables

Revision ID: 20260707_settings
Revises: 20260703_scene_chapter_links
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260707_settings"
down_revision = "20260703_scene_chapter_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_llm_defaults",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id", UUID(as_uuid=True), nullable=False, unique=True, index=True
        ),
        sa.Column("provider_id", sa.String(64), nullable=True),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("model", sa.String(256), nullable=True),
        sa.Column("timeout", sa.Integer, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("top_p", sa.Float, nullable=True),
        sa.Column("extra", JSONB, nullable=True),
        sa.Column("creative_mode", sa.String(32), nullable=True),
        sa.Column("deep_import", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "global_author_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id", UUID(as_uuid=True), nullable=False, unique=True, index=True
        ),
        sa.Column("daily_goal", sa.Integer, nullable=True),
        sa.Column("editor_font", sa.String(32), nullable=True),
        sa.Column("default_focus_mode", sa.Boolean, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "project_author_preferences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("daily_goal", sa.Integer, nullable=True),
        sa.Column("editor_font", sa.String(32), nullable=True),
        sa.Column("default_focus_mode", sa.Boolean, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("project_author_preferences")
    op.drop_table("global_author_preferences")
    op.drop_table("global_llm_defaults")
