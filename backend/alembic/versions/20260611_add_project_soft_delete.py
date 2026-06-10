"""add project soft delete

Revision ID: 20260611_add_project_soft_delete
Revises: 20260611_add_text_archive
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260611_add_project_soft_delete"
down_revision: str | None = "20260611_add_text_archive"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True,
                  comment="软删除时间，NULL 表示未删除"),
    )
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_projects_deleted_at")
    op.drop_column("projects", "deleted_at")
