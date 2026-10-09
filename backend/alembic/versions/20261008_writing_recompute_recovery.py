"""Persist recompute operation receipts and invalidation notices.

Revision ID: 20261008_writing_recompute_recovery
Revises: 20261007_scene_checkpoint_basis

阶段 2 审查整改（S2 / F7）：

- ``writing_recompute_operations``：已完成重算操作的回执（novel_id +
  operation_id 唯一）。同编号异摘要的请求须被拒绝，已完成操作在来源变化后
  仍能回放原回执，不再依赖「再改一次正文」才能找回入口。
- ``writing_invalidation_notices``：保存触发的失效提示（待重算状态）落库，
  编辑器加载时回读；重算覆盖该章后消解。此前提示只挂在草稿行瞬态属性上，
  作者「暂不重算」并离开后就丢失。

均为新增表，不回填旧数据；旧行为（无行）等价于「没有可恢复状态」。
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261008_writing_recompute_recovery"
down_revision = "20261007_scene_checkpoint_basis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "writing_recompute_operations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation_id", sa.String(length=120), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("expected_source_digest", sa.String(length=128), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id", "operation_id", name="uq_writing_recompute_operation_id"
        ),
        sa.Index("ix_writing_recompute_operations_novel_id", "novel_id"),
        comment="失效重算操作回执（跨会话重查与幂等回放）",
    )
    op.create_index(
        "ix_writing_recompute_operations_novel_created",
        "writing_recompute_operations",
        ["novel_id", "created_at"],
    )
    op.create_table(
        "writing_invalidation_notices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("receipt_id", sa.String(length=120), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column("notice_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id", "receipt_id", name="uq_writing_invalidation_notice_receipt"
        ),
        sa.Index("ix_writing_invalidation_notices_novel_id", "novel_id"),
        comment="改稿失效提示（待重算状态，跨会话可回读）",
    )
    op.create_index(
        "ix_writing_invalidation_notices_chapter_index",
        "writing_invalidation_notices",
        ["chapter_index"],
    )
    op.create_index(
        "ix_writing_invalidation_notices_novel_open",
        "writing_invalidation_notices",
        ["novel_id", "status", "chapter_index"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_writing_invalidation_notices_novel_open",
        table_name="writing_invalidation_notices",
    )
    op.drop_table("writing_invalidation_notices")
    op.drop_index(
        "ix_writing_recompute_operations_novel_created",
        table_name="writing_recompute_operations",
    )
    op.drop_table("writing_recompute_operations")
