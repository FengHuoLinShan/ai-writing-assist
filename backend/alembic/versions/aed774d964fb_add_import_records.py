"""add import_records table

Revision ID: aed774d964fb
Revises: 0001
Create Date: 2026-05-25 16:14:09.883054
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "aed774d964fb"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("timezone('utc', now())"), nullable=True),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("total_chapters", sa.Integer(), nullable=False),
        sa.Column("imported_chapters", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_import_records_novel_id"), "import_records", ["novel_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_import_records_novel_id"), table_name="import_records")
    op.drop_table("import_records")
