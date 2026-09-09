"""Add world co-creation session and message tables (ADR-0021).

Revision ID: 20260909_world_cocreation_sessions
Revises: 20260909_world_library_topics
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260909_world_cocreation_sessions"
down_revision = "20260909_world_library_topics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "world_cocreation_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "workflow_preset",
            sa.String(32),
            nullable=False,
            server_default="world_core",
        ),
        sa.Column("target_kind", sa.String(32), nullable=True),
        sa.Column("source_page_id", UUID(as_uuid=True), nullable=True),
        sa.Column("current_checkpoint_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "checkpoint_round", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "checkpoint_depth",
            sa.String(16),
            nullable=False,
            server_default="seed",
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="active"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("novel_id", "id", name="uq_world_cocreation_session_novel"),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_world_cocreation_session_status",
        ),
        sa.CheckConstraint(
            "source_kind IN ('project', 'world_bible_page', 'core_entity', "
            "'world_library_topic')",
            name="ck_world_cocreation_session_source",
        ),
        sa.CheckConstraint(
            "(source_kind = 'project') = (source_id IS NULL)",
            name="ck_world_cocreation_session_source_id",
        ),
        sa.CheckConstraint(
            "checkpoint_depth IN ('seed', 'candidate', 'instance')",
            name="ck_world_cocreation_session_depth",
        ),
        {"comment": "共创会话：绑定项目内主题/资料/世界核心的持久化讨论载体"},
    )
    op.create_index(
        "ix_world_cocreation_sessions_novel_id",
        "world_cocreation_sessions",
        ["novel_id"],
    )
    op.create_index(
        "ix_world_cocreation_sessions_novel_activity",
        "world_cocreation_sessions",
        ["novel_id", "last_message_at"],
    )
    op.create_index(
        "ix_world_cocreation_sessions_status",
        "world_cocreation_sessions",
        ["status"],
    )

    op.create_table(
        "world_cocreation_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="message"),
        sa.Column("action", sa.String(16), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("context_confirmation_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("async_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("outcome_suggestion_id", UUID(as_uuid=True), nullable=True),
        sa.Column("outcome_kind", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["novel_id", "session_id"],
            [
                "world_cocreation_sessions.novel_id",
                "world_cocreation_sessions.id",
            ],
            ondelete="CASCADE",
            name="fk_world_cocreation_message_session_same_novel",
        ),
        sa.CheckConstraint(
            "role IN ('author', 'assistant')",
            name="ck_world_cocreation_message_role",
        ),
        sa.CheckConstraint(
            "kind IN ('message', 'decision')",
            name="ck_world_cocreation_message_kind",
        ),
        sa.CheckConstraint(
            "action IS NULL OR action IN ('expand', 'connect', 'pressure', "
            "'consolidate')",
            name="ck_world_cocreation_message_action",
        ),
        {"comment": "共创会话消息：终态作者消息/模型回复/作者决定，含来源与成果引用"},
    )
    op.create_index(
        "ix_world_cocreation_messages_novel_id",
        "world_cocreation_messages",
        ["novel_id"],
    )
    op.create_index(
        "ix_world_cocreation_messages_session_created",
        "world_cocreation_messages",
        ["novel_id", "session_id", "created_at"],
    )


def downgrade():
    op.drop_table("world_cocreation_messages")
    op.drop_table("world_cocreation_sessions")
