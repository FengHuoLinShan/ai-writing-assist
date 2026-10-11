"""Add per-chunk lexical terms for indexed recall.

Revision ID: 20261007_rag_lexical_terms
Revises: 20261006_event_soft_delete

``rag_chunks.lexical_terms`` 是可重建的派生索引列（中文 2–4 字 n-gram +
英文词，与查询侧共用规范化形式）：PG 用 TEXT[] + GIN array_ops ``&&``
召回，SQLite 以 JSON 窄适配。本迁移对存量行做 Python 回填——只改派生
列，不重算 embedding，不动 chapter 锁/新鲜度机制；空值/空数组表示该行
词法索引未就绪，查询侧走带版本诊断的旧词法路径。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op
from modules.evidence.indexing.lexical_plan import extract_index_terms

revision = "20261007_rag_lexical_terms"
down_revision = "20261006_event_soft_delete"
branch_labels = None
depends_on = None

_BATCH_SIZE = 500


def upgrade() -> None:
    op.add_column(
        "rag_chunks",
        sa.Column(
            "lexical_terms",
            sa.ARRAY(sa.Text()),
            nullable=True,
            comment="索引期词法词项（中文 2–4 字 n-gram + 英文词；可重建派生索引列）",
        ),
    )
    bind = op.get_bind()
    rag_chunks = sa.table(
        "rag_chunks",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("text", sa.Text),
        sa.column("lexical_terms", sa.ARRAY(sa.Text)),
    )
    result = bind.execute(
        sa.select(rag_chunks.c.id, rag_chunks.c.text).execution_options(
            yield_per=_BATCH_SIZE,
        )
    ).mappings()
    for batch in result.partitions(_BATCH_SIZE):
        bind.execute(
            rag_chunks.update()
            .where(rag_chunks.c.id == sa.bindparam("_row_id"))
            .values(lexical_terms=sa.bindparam("_row_terms", type_=sa.ARRAY(sa.Text()))),
            [
                {
                    "_row_id": row["id"],
                    "_row_terms": extract_index_terms(row["text"] or ""),
                }
                for row in batch
            ],
        )
    op.create_index(
        "ix_rag_chunks_lexical_terms_gin",
        "rag_chunks",
        ["lexical_terms"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_lexical_terms_gin", table_name="rag_chunks")
    op.drop_column("rag_chunks", "lexical_terms")
