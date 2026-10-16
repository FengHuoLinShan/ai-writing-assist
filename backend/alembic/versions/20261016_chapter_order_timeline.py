"""Persist author chapter-order previews and Story binding receipts.

Revision ID: 20261016_chapter_order
Revises: 20261016_story_arc_guard
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_chapter_order"
down_revision: str | None = "20261016_story_arc_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
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
    ]


def upgrade() -> None:
    op.create_table(
        "writing_chapter_order_operations",
        *_identity_columns(),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_order_json", sa.JSON(), nullable=False),
        sa.Column("target_order_json", sa.JSON(), nullable=False),
        sa.Column("before_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("preview_hash", sa.String(length=64), nullable=False),
        sa.Column("after_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("story_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("story_receipt_id", sa.UUID(), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("restore_preview_hash", sa.String(length=64), nullable=True),
        sa.Column("restore_preview_json", sa.JSON(), nullable=True),
        sa.Column("result_ref_json", sa.JSON(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('previewed', 'executed', 'restored')",
            name="ck_writing_chapter_order_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", "id", name="uq_writing_chapter_order_novel_id"),
        comment="章节顺序操作预览、回执与恢复基线",
    )
    op.create_index(
        "ix_writing_chapter_order_operations_novel_id",
        "writing_chapter_order_operations",
        ["novel_id"],
    )
    op.create_index(
        "ix_writing_chapter_order_novel_created",
        "writing_chapter_order_operations",
        ["novel_id", "created_at"],
    )

    op.create_table(
        "story_chapter_order_receipts",
        *_identity_columns(),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("chapter_map_json", sa.JSON(), nullable=False),
        sa.Column("before_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("after_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('applied', 'restored')",
            name="ck_story_chapter_order_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", "id", name="uq_story_chapter_order_novel_id"),
        comment="章节重排对Story绑定与派生状态的回执",
    )
    op.create_index(
        "ix_story_chapter_order_receipts_novel_id",
        "story_chapter_order_receipts",
        ["novel_id"],
    )
    op.create_index(
        "ix_story_chapter_order_novel_created",
        "story_chapter_order_receipts",
        ["novel_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_story_chapter_order_novel_created", table_name="story_chapter_order_receipts"
    )
    op.drop_index(
        "ix_story_chapter_order_receipts_novel_id",
        table_name="story_chapter_order_receipts",
    )
    op.drop_table("story_chapter_order_receipts")
    op.drop_index(
        "ix_writing_chapter_order_novel_created",
        table_name="writing_chapter_order_operations",
    )
    op.drop_index(
        "ix_writing_chapter_order_operations_novel_id",
        table_name="writing_chapter_order_operations",
    )
    op.drop_table("writing_chapter_order_operations")
