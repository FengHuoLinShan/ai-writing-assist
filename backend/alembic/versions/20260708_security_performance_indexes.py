"""add security audit performance indexes

Revision ID: 20260708_security_performance_indexes
Revises: 20260708_entity_relation_review_meta
"""

from alembic import op

revision = "20260708_security_performance_indexes"
down_revision = "20260708_entity_relation_review_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_rag_chunks_novel_source_chapter_order",
        "rag_chunks",
        ["novel_id", "source_type", "chapter_index", "chunk_index", "id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_relations_novel_status_source",
        "entity_relations",
        ["novel_id", "status", "source_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_relations_novel_status_target",
        "entity_relations",
        ["novel_id", "status", "target_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_entity_relations_novel_status_target",
        table_name="entity_relations",
    )
    op.drop_index(
        "ix_entity_relations_novel_status_source",
        table_name="entity_relations",
    )
    op.drop_index(
        "ix_rag_chunks_novel_source_chapter_order",
        table_name="rag_chunks",
    )
