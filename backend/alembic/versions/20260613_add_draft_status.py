"""添加 writing_drafts.status 列

Revision ID: 20260613_add_writing_draft_status
Revises: 20260611_add_project_soft_delete
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260613_add_draft_status"
down_revision: str | None = "20260611_add_project_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_exists(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if _column_exists("writing_drafts", "status"):
        return
    op.add_column(
        "writing_drafts",
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
            comment="状态：draft / candidate / canonical / deprecated",
        ),
    )


def downgrade() -> None:
    if _column_exists("writing_drafts", "status"):
        op.drop_column("writing_drafts", "status")
