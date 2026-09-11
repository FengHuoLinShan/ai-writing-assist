"""Assistant-owned discussion persistence; legacy table names retain identity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin

COCREATION_SOURCE_KINDS = (
    "project",
    "world_bible_page",
    "core_entity",
    "world_library_topic",
)
COCREATION_ACTIONS = ("expand", "connect", "pressure", "consolidate")
COCREATION_CHECKPOINT_TARGET_TYPES = (
    "world_design_checkpoint",
    "world_core_checkpoint",
)


class AssistantSession(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "world_cocreation_sessions"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_world_cocreation_session_novel"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_world_cocreation_session_status",
        ),
        CheckConstraint(
            "source_kind IN ('project', 'world_bible_page', 'core_entity', "
            "'world_library_topic')",
            name="ck_world_cocreation_session_source",
        ),
        CheckConstraint(
            "(source_kind = 'project') = (source_id IS NULL)",
            name="ck_world_cocreation_session_source_id",
        ),
        CheckConstraint(
            "checkpoint_depth IN ('seed', 'candidate', 'instance')",
            name="ck_world_cocreation_session_depth",
        ),
        Index(
            "ix_world_cocreation_sessions_novel_activity",
            "novel_id",
            "last_message_at",
        ),
        {"comment": "共创会话：绑定项目内主题/资料/世界核心的持久化讨论载体"},
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    workflow_preset: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="world_core",
    )
    target_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    # 工作区指针：指向 suggestion 队列中的 checkpoint 行，由 service 校验存在与同项目。
    current_checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    checkpoint_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_depth: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="seed",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )


class AssistantMessage(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "world_cocreation_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["novel_id", "session_id"],
            [
                "world_cocreation_sessions.novel_id",
                "world_cocreation_sessions.id",
            ],
            ondelete="CASCADE",
            name="fk_world_cocreation_message_session_same_novel",
        ),
        CheckConstraint(
            "role IN ('author', 'assistant')",
            name="ck_world_cocreation_message_role",
        ),
        CheckConstraint(
            "kind IN ('message', 'decision')",
            name="ck_world_cocreation_message_kind",
        ),
        CheckConstraint(
            "action IS NULL OR action IN ('expand', 'connect', 'pressure', "
            "'consolidate')",
            name="ck_world_cocreation_message_action",
        ),
        Index(
            "ix_world_cocreation_messages_session_created",
            "novel_id",
            "session_id",
            "created_at",
        ),
        {"comment": "共创会话消息：终态作者消息/模型回复/作者决定，含来源与成果引用"},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="message")
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 生成回合的来源 confirmation 与长任务回执，均由调用时的门禁校验有效性。
    context_confirmation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    outcome_suggestion_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    outcome_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
