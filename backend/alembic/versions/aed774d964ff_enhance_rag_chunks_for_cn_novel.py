"""enhance rag chunks for chinese novel extraction

Revision ID: aed774d964ff
Revises: aed774d964fe
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "aed774d964ff"
down_revision: Union[str, None] = "aed774d964fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rag_chunks", sa.Column("chunk_index", sa.Integer(), nullable=True))
    op.add_column("rag_chunks", sa.Column("start_offset", sa.Integer(), nullable=True))
    op.add_column("rag_chunks", sa.Column("end_offset", sa.Integer(), nullable=True))
    op.add_column("rag_chunks", sa.Column("char_count", sa.Integer(), nullable=True))
    op.add_column(
        "rag_chunks",
        sa.Column("index_version", sa.String(32), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("embedding_status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.add_column("rag_chunks", sa.Column("embedding_error", sa.Text(), nullable=True))
    op.add_column(
        "rag_chunks",
        sa.Column("index_warnings", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_rag_chunks_chapter_order",
        "rag_chunks",
        ["novel_id", "chapter_index", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_chapter_order", table_name="rag_chunks")
    op.drop_column("rag_chunks", "index_warnings")
    op.drop_column("rag_chunks", "embedding_error")
    op.drop_column("rag_chunks", "embedding_status")
    op.drop_column("rag_chunks", "index_version")
    op.drop_column("rag_chunks", "char_count")
    op.drop_column("rag_chunks", "end_offset")
    op.drop_column("rag_chunks", "start_offset")
    op.drop_column("rag_chunks", "chunk_index")
