"""migrate embedding columns to 768-dim with HNSW ip indexes

Drop and recreate rag_chunks.embedding and core_entities.embedding as
vector(768) columns. Create HNSW indexes with inner product (<#>)
operator. Mark all existing chunks as pending_vectorization so the
background worker can rebuild them with the new BGE model.

Revision ID: d967c0547256
Revises: d967c0547255
Create Date: 2026-05-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d967c0547256"
down_revision: Union[str, None] = "d967c0547255"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- rag_chunks: drop old embedding, add new vector(768) ----
    op.execute("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE rag_chunks ADD COLUMN embedding vector(768)")

    # Mark all existing chunks for re-vectorization with the new model
    op.execute(
        "UPDATE rag_chunks SET embedding_status = 'pending_vectorization'"
        " WHERE embedding_status IN ('succeeded', 'pending')"
    )

    # HNSW index on rag_chunks (inner product for L2-normalized vectors)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw"
        " ON rag_chunks USING hnsw (embedding vector_ip_ops)"
        " WITH (m = 16, ef_construction = 200)"
    )

    # ---- core_entities: same treatment ----
    op.execute("ALTER TABLE core_entities DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE core_entities ADD COLUMN embedding vector(768)")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_core_entities_embedding_hnsw"
        " ON core_entities USING hnsw (embedding vector_ip_ops)"
        " WITH (m = 16, ef_construction = 200)"
    )


def downgrade() -> None:
    # Drop HNSW indexes
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_core_entities_embedding_hnsw")

    # Revert to vector(1024)
    op.execute("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE rag_chunks ADD COLUMN embedding vector(1024)")
    op.execute("ALTER TABLE core_entities DROP COLUMN IF EXISTS embedding")
    op.execute("ALTER TABLE core_entities ADD COLUMN embedding vector(1024)")

    # Un-mark pending_vectorization
    op.execute(
        "UPDATE rag_chunks SET embedding_status = 'pending'"
        " WHERE embedding_status = 'pending_vectorization'"
    )
