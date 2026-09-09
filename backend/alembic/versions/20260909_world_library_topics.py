"""Add world library topic directory and author workspace tables.

Revision ID: 20260909_world_library_topics
Revises: 20260908_unified_map
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260909_world_library_topics"
down_revision = "20260908_unified_map"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "world_library_topics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("novel_id", "id", name="uq_world_library_topic_novel_id"),
        sa.ForeignKeyConstraint(
            ["novel_id", "parent_id"],
            ["world_library_topics.novel_id", "world_library_topics.id"],
            ondelete="CASCADE",
            name="fk_world_library_topic_parent_same_novel",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_world_library_topic_status",
        ),
        {"comment": "资料库主题目录（作者组织方式，不构成事实依赖）"},
    )
    op.create_index(
        "ix_world_library_topics_novel_id", "world_library_topics", ["novel_id"]
    )
    op.create_index(
        "ix_world_library_topics_novel_parent_sort",
        "world_library_topics",
        ["novel_id", "parent_id", "sort_order"],
    )

    op.create_table(
        "world_library_topic_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "novel_id",
            "topic_id",
            "target_kind",
            "target_id",
            name="uq_world_library_topic_member",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "topic_id"],
            ["world_library_topics.novel_id", "world_library_topics.id"],
            ondelete="CASCADE",
            name="fk_world_library_topic_member_same_novel",
        ),
        sa.CheckConstraint(
            "target_kind IN ('page', 'draft', 'entity')",
            name="ck_world_library_topic_member_kind",
        ),
        {"comment": "主题成员：对 Page / Draft / Entity 的多主题引用"},
    )
    op.create_index(
        "ix_world_library_topic_members_novel_id",
        "world_library_topic_members",
        ["novel_id"],
    )
    op.create_index(
        "ix_world_library_topic_members_target",
        "world_library_topic_members",
        ["novel_id", "target_kind", "target_id"],
    )

    common_recent_columns = [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]
    op.create_table(
        "world_library_favorites",
        *common_recent_columns,
        sa.CheckConstraint(
            "target_kind IN ('page', 'draft', 'entity')",
            name="ck_world_library_favorites_kind",
        ),
        sa.UniqueConstraint(
            "novel_id", "target_kind", "target_id", name="uq_world_library_favorite"
        ),
        {"comment": "作者工作区收藏"},
    )
    op.create_index(
        "ix_world_library_favorites_novel_id",
        "world_library_favorites",
        ["novel_id"],
    )
    op.create_table(
        "world_library_recents",
        *common_recent_columns,
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "target_kind IN ('page', 'draft', 'entity')",
            name="ck_world_library_recents_kind",
        ),
        sa.UniqueConstraint(
            "novel_id", "target_kind", "target_id", name="uq_world_library_recent"
        ),
        {"comment": "作者工作区最近访问"},
    )
    op.create_index(
        "ix_world_library_recents_novel_id",
        "world_library_recents",
        ["novel_id"],
    )
    op.create_index(
        "ix_world_library_recents_novel_opened",
        "world_library_recents",
        ["novel_id", "last_opened_at"],
    )

    op.create_table(
        "world_library_workspace_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("view_prefs_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("novel_id", name="uq_world_library_workspace_novel"),
        {"comment": "作者工作区视图偏好"},
    )
    op.create_index(
        "ix_world_library_workspace_profiles_novel_id",
        "world_library_workspace_profiles",
        ["novel_id"],
    )


def downgrade():
    op.drop_table("world_library_workspace_profiles")
    op.drop_table("world_library_recents")
    op.drop_table("world_library_favorites")
    op.drop_table("world_library_topic_members")
    op.drop_table("world_library_topics")
