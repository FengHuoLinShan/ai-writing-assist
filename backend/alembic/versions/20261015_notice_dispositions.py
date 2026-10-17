"""store author dispositions for unified notices

Revision ID: 20261015_notice_dispositions
Revises: 20261015_map_node_merge
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_notice_dispositions"
down_revision: str | None = "20261015_map_node_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_notice_dispositions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("notice_key", sa.String(length=200), nullable=False),
        sa.Column("basis_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('read','snoozed','ignored')",
            name="ck_assistant_notice_disposition_status",
        ),
        sa.CheckConstraint(
            "row_version >= 1", name="ck_assistant_notice_disposition_version"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "source_id",
            "notice_key",
            "basis_fingerprint",
            name="uq_assistant_notice_disposition_basis",
        ),
        comment="统一提醒展示处置，按来源依据指纹隔离",
    )
    op.create_index(
        "ix_assistant_notice_dispositions_novel_id",
        "assistant_notice_dispositions",
        ["novel_id"],
    )
    op.create_index(
        "ix_assistant_notice_dispositions_novel_status",
        "assistant_notice_dispositions",
        ["novel_id", "status", "wake_at"],
    )
    op.create_table(
        "assistant_notice_category_mutes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("is_muted", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "row_version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.CheckConstraint(
            "row_version >= 1", name="ck_assistant_notice_category_mute_version"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "source_id",
            "category",
            name="uq_assistant_notice_category_mute",
        ),
        comment="作者按来源和类别设置的统一提醒静默状态",
    )
    op.create_index(
        "ix_assistant_notice_category_mutes_novel_id",
        "assistant_notice_category_mutes",
        ["novel_id"],
    )
    op.create_index(
        "ix_assistant_notice_category_mutes_novel_muted",
        "assistant_notice_category_mutes",
        ["novel_id", "is_muted"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_notice_category_mutes_novel_id",
        table_name="assistant_notice_category_mutes",
    )
    op.drop_index(
        "ix_assistant_notice_category_mutes_novel_muted",
        table_name="assistant_notice_category_mutes",
    )
    op.drop_table("assistant_notice_category_mutes")
    op.drop_index(
        "ix_assistant_notice_dispositions_novel_id",
        table_name="assistant_notice_dispositions",
    )
    op.drop_index(
        "ix_assistant_notice_dispositions_novel_status",
        table_name="assistant_notice_dispositions",
    )
    op.drop_table("assistant_notice_dispositions")
