"""Preserve long source-bound delta categories without rolling back a Scene."""

import sqlalchemy as sa

from alembic import op

revision = "20261013_delta_category_text"
down_revision = "20261013_codex_text_connection"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("delta_log", "category", existing_type=sa.String(32), type_=sa.Text())


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM delta_log WHERE length(category) > 32")
    ):
        raise RuntimeError(
            "Long delta categories prevent downgrade; no history is truncated"
        )
    op.alter_column("delta_log", "category", existing_type=sa.Text(), type_=sa.String(32))
