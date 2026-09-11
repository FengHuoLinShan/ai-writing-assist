"""World library topic directory and author workspace ORM models."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
)

from .common import (
    JSON,
    PG_UUID,
    Base,
    DateTime,
    ForeignKey,
    Integer,
    Mapped,
    String,
    Text,
    TimestampMixin,
    UniqueConstraint,
    UUIDMixin,
    datetime,
    mapped_column,
    uuid,
)

LIBRARY_TARGET_KINDS = ("page", "draft", "entity")


class WorldLibraryTopic(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_library_topics"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_world_library_topic_novel_id"),
        ForeignKeyConstraint(
            ["novel_id", "parent_id"],
            ["world_library_topics.novel_id", "world_library_topics.id"],
            ondelete="CASCADE",
            name="fk_world_library_topic_parent_same_novel",
        ),
        Index(
            "ix_world_library_topics_novel_parent_sort",
            "novel_id",
            "parent_id",
            "sort_order",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_world_library_topic_status",
        ),
        {"comment": "资料库主题目录（作者组织方式，不构成事实依赖）"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )


class WorldLibraryTopicMember(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_library_topic_members"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "topic_id",
            "target_kind",
            "target_id",
            name="uq_world_library_topic_member",
        ),
        ForeignKeyConstraint(
            ["novel_id", "topic_id"],
            ["world_library_topics.novel_id", "world_library_topics.id"],
            ondelete="CASCADE",
            name="fk_world_library_topic_member_same_novel",
        ),
        Index(
            "ix_world_library_topic_members_target",
            "novel_id",
            "target_kind",
            "target_id",
        ),
        CheckConstraint(
            "target_kind IN ('page', 'draft', 'entity')",
            name="ck_world_library_topic_member_kind",
        ),
        {"comment": "主题成员：对 Page / Draft / Entity 的多主题引用"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class WorldLibraryFavorite(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_library_favorites"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "target_kind",
            "target_id",
            name="uq_world_library_favorite",
        ),
        CheckConstraint(
            "target_kind IN ('page', 'draft', 'entity')",
            name="ck_world_library_favorite_kind",
        ),
        {"comment": "作者工作区收藏"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


class WorldLibraryRecent(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_library_recents"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "target_kind",
            "target_id",
            name="uq_world_library_recent",
        ),
        CheckConstraint(
            "target_kind IN ('page', 'draft', 'entity')",
            name="ck_world_library_recent_kind",
        ),
        Index(
            "ix_world_library_recents_novel_opened",
            "novel_id",
            "last_opened_at",
        ),
        {"comment": "作者工作区最近访问"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    last_opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorldLibraryWorkspaceProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "world_library_workspace_profiles"
    __table_args__ = (
        UniqueConstraint("novel_id", name="uq_world_library_workspace_novel"),
        {"comment": "作者工作区视图偏好"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    view_prefs_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
