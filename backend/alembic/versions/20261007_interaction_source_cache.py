"""Add the private RP interaction source cache table.

Revision ID: 20261007_interaction_source_cache
Revises: 20261007_rag_lexical_terms

`context_interaction_source_cache`（ADR-0018 2026-10-07 修订例外，M1 契约 §4）：
一行保存一份完整预算前材料与至多一个预算的编译正文。私有派生表——
不进导出/备份/日志；consumer/source 项目删除级联清空；UNIQUE(novel_id,
material_key_hash) 支撑幂等覆盖写。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20261007_interaction_source_cache"
down_revision = "20261007_rag_lexical_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_interaction_source_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False),
        sa.Column("material_key_hash", sa.String(64), nullable=False),
        sa.Column("material_key", JSONB(), nullable=False),
        sa.Column("material_body", JSONB(), nullable=False),
        sa.Column("material_body_sha", sa.String(64), nullable=False),
        sa.Column("material_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compiled_body", sa.Text(), nullable=True),
        sa.Column("compiled_spec", JSONB(), nullable=True),
        sa.Column("compiled_sha", sa.String(64), nullable=True),
        sa.Column("compiled_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("method_versions", JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "novel_id",
            "material_key_hash",
            name="uq_interaction_source_cache_key",
        ),
        sa.Index("ix_context_interaction_source_cache_novel_id", "novel_id"),
        sa.Index("ix_interaction_source_cache_expires", "novel_id", "expires_at"),
        sa.Index("ix_interaction_source_cache_source", "source_novel_id"),
        comment="RP 原作包派生缓存（完整预算前材料+编译正文）",
    )


def downgrade() -> None:
    op.drop_table("context_interaction_source_cache")
