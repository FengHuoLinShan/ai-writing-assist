"""add generation center prompt templates

Revision ID: 20260707_gen_prompt_templates
Revises: 20260707_settings
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260707_gen_prompt_templates"
down_revision = "20260707_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_prompt_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("target_kind", sa.String(64), nullable=False, index=True),
        sa.Column("template_key", sa.String(128), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("object_template", sa.String(32), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("variables_json", JSONB, nullable=False),
        sa.Column("validation_state", sa.String(16), nullable=False),
        sa.Column("validation_issues_json", JSONB, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
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
        sa.UniqueConstraint(
            "novel_id",
            "target_kind",
            "template_key",
            name="uq_generation_prompt_template_key",
        ),
    )
    op.create_index(
        "ix_generation_prompt_templates_novel_target_status_updated",
        "generation_prompt_templates",
        ["novel_id", "target_kind", "status", "updated_at"],
    )
    op.create_table(
        "generation_prompt_template_revisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("generation_prompt_templates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("object_template", sa.String(32), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("variables_json", JSONB, nullable=False),
        sa.Column("validation_state", sa.String(16), nullable=False),
        sa.Column("validation_issues_json", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_meta_json", JSONB, nullable=False),
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
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_generation_prompt_template_revision",
        ),
    )
    op.create_index(
        "ix_generation_prompt_template_revisions_novel_template",
        "generation_prompt_template_revisions",
        ["novel_id", "template_id"],
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_generation_prompt_template_revisions_novel_template"
    )
    op.drop_table("generation_prompt_template_revisions")
    op.execute(
        "DROP INDEX IF EXISTS ix_generation_prompt_templates_novel_target_status_updated"
    )
    op.drop_table("generation_prompt_templates")
