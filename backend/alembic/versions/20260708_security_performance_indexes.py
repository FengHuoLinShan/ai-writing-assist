"""add security audit performance indexes

Revision ID: 20260708_security_performance_indexes
Revises: 20260708_entity_relation_review_meta
"""

import sqlalchemy as sa

from alembic import op

revision = "20260708_security_performance_indexes"
down_revision = "20260708_entity_relation_review_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    specs = {
        "rag_chunks": {
            "ix_rag_chunks_novel_source_chapter_order": [
                "novel_id",
                "source_type",
                "chapter_index",
                "chunk_index",
                "id",
            ]
        },
        "entity_relations": {
            "ix_entity_relations_novel_status_source": [
                "novel_id",
                "status",
                "source_id",
            ],
            "ix_entity_relations_novel_status_target": [
                "novel_id",
                "status",
                "target_id",
            ],
        },
    }
    for table_name, indexes in specs.items():
        existing = {
            index["name"] for index in inspector.get_indexes(table_name)
        }
        for index_name, columns in indexes.items():
            if index_name not in existing:
                op.create_index(index_name, table_name, columns, unique=False)


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
