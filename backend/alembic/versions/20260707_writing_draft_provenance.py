"""ensure writing draft provenance column

Revision ID: 20260707_writing_draft_provenance
Revises: 20260707_gen_prompt_templates
"""

import sqlalchemy as sa

from alembic import op

revision = "20260707_writing_draft_provenance"
down_revision = "20260707_gen_prompt_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("writing_drafts")}
    if "provenance_json" not in columns:
        op.add_column("writing_drafts", sa.Column("provenance_json", sa.JSON()))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("writing_drafts")}
    if "provenance_json" in columns:
        op.drop_column("writing_drafts", "provenance_json")
