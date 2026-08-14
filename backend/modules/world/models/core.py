"""Core world entity ORM models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .common import (
    JSON,
    PG_UUID,
    UTC,
    Base,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    NovelMixin,
    StatusMixin,
    String,
    Text,
    TimestampMixin,
    UUIDMixin,
    _vector_column,
    datetime,
    func,
    mapped_column,
    relationship,
    uuid,
)

if TYPE_CHECKING:
    from .character import Character

# ============================================================
# CoreEntity — 统一核心实体
# ============================================================


class CoreEntity(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """统一核心实体 — 所有世界对象的正史记录"""

    __tablename__ = "core_entities"
    __table_args__ = {"comment": "统一核心实体（原 world_entities）"}

    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="实体类型（自由字符串，如 character/faction/item/location/event）",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="实体名称",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="概要/简要描述",
    )
    public_info: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="对外公开信息",
    )
    hidden_truth: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="隐藏真相（仅作者视角）",
    )
    content_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="扩展信息 JSON（含动态属性、别名等）",
    )
    importance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="重要性 0.0~1.0",
    )
    importance_level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="normal",
        comment="重要性级别：core/important/normal/temporary",
    )
    reveal_level: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="author_only",
        comment="揭示层级：author_only/hinted/revealed/fully_known",
    )
    embedding_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用于向量化的文本",
    )
    embedding = _vector_column()
    search_text: Mapped[str | None] = mapped_column(
        Text,
        Computed("name || ' ' || COALESCE(content_json->>'aliases', '')", persisted=True),
        nullable=True,
        comment="用于 pg_trgm 模糊搜索的生成列",
    )
    pinyin_string: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="name 的拼音字符串缓存（用于去重音似特征）",
    )
    created_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="创建者标识",
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="确认者标识",
    )
    image_version: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        comment="当前对象图片版本",
    )
    image_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="对象图片更新时间",
    )

    @property
    def has_image(self) -> bool:
        return self.image_version is not None

    # 1:1 扩展
    event: Mapped[Event | None] = relationship(
        "Event",
        back_populates="core_entity",
        uselist=False,
        foreign_keys="Event.entity_id",
    )
    character: Mapped[Character | None] = relationship(
        "Character",
        back_populates="core_entity",
        uselist=False,
        foreign_keys="Character.entity_id",
    )

    # 1:N 关系
    source_relations: Mapped[list[EntityRelation]] = relationship(
        "EntityRelation",
        back_populates="source",
        foreign_keys="EntityRelation.source_id",
    )
    target_relations: Mapped[list[EntityRelation]] = relationship(
        "EntityRelation",
        back_populates="target",
        foreign_keys="EntityRelation.target_id",
    )

    # minimal-core: geo_location 关系已移除（geo 模块暂时切分）

    def __repr__(self) -> str:
        return f"<CoreEntity id={self.id} type={self.entity_type} name={self.name!r}>"


# ============================================================
# Event — 事件扩展
# ============================================================


class Event(Base, NovelMixin):
    """事件扩展表 — entity_id 为 PK+FK 1:1 绑定 CoreEntity"""

    __tablename__ = "events"
    __table_args__ = {"comment": "事件扩展表"}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_chapter_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("imported_chapters.id", ondelete="CASCADE"),
        nullable=False,
        comment="来源章节 ID",
    )
    location_entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="RESTRICT"),
        nullable=False,
        comment="事件发生地实体 ID",
    )
    timeline_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="时间线顺序",
    )
    occurrence_time_label: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="发生时间标签（如'三年前'）",
    )

    core_entity: Mapped[CoreEntity] = relationship(
        "CoreEntity",
        back_populates="event",
        foreign_keys=[entity_id],
    )

    def __repr__(self) -> str:
        return f"<Event entity_id={self.entity_id} order={self.timeline_order}>"


# ============================================================
# EntityRelation — 实体关系边
# ============================================================


class EntityRelation(Base, UUIDMixin, TimestampMixin):
    """实体关系边 — UUID FK → core_entities + 章节追溯"""

    __tablename__ = "entity_relations"
    __table_args__ = (
        Index(
            "ix_entity_relations_novel_status_source",
            "novel_id",
            "status",
            "source_id",
        ),
        Index(
            "ix_entity_relations_novel_status_target",
            "novel_id",
            "status",
            "target_id",
        ),
        {"comment": "实体关系边"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="关系类型（自由字符串）",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="关系描述",
    )
    strength: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="关系强度 0.0~1.0",
    )
    source_chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("imported_chapters.id", ondelete="SET NULL"),
        nullable=True,
        comment="来源章节 ID",
    )
    caused_by_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="SET NULL"),
        nullable=True,
        comment="导致此关系的事件 ID",
    )
    quote: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="原文依据",
    )
    review_meta: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
        comment="人工复核审计元数据",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="canonical",
        comment="状态：candidate/canonical/deprecated",
    )

    source: Mapped[CoreEntity] = relationship(
        "CoreEntity",
        back_populates="source_relations",
        foreign_keys=[source_id],
    )
    target: Mapped[CoreEntity] = relationship(
        "CoreEntity",
        back_populates="target_relations",
        foreign_keys=[target_id],
    )

    def __repr__(self) -> str:
        return (
            f"<EntityRelation id={self.id} "
            f"{self.source_id} → {self.relation_type} → {self.target_id}>"
        )


# ============================================================
# EntityRevision — 实体快照版本
# ============================================================


class EntityRevision(Base, UUIDMixin):
    """实体快照版本表 — 每次 AI 导入或用户编辑自动打快照"""

    __tablename__ = "entity_revisions"
    __table_args__ = {"comment": "实体快照版本"}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="实体完整快照 JSON",
    )
    source_chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("imported_chapters.id", ondelete="SET NULL"),
        nullable=True,
        comment="触发快照的章节 ID",
    )
    revision_reason: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai_import",
        comment="快照原因：ai_import/manual_edit/rollback/batch_update",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.timezone("utc", func.now()),
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return (
            f"<EntityRevision id={self.id} "
            f"entity={self.entity_id} "
            f"reason={self.revision_reason}>"
        )


class TextArchive(Base, UUIDMixin, NovelMixin):
    """文本归档 — 记录长文本字段每次变更的快照，用于版本回滚"""

    __tablename__ = "text_archive"
    __table_args__ = {"comment": "文本归档"}

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联实体 ID",
    )
    field_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="字段名",
    )
    text_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="变更后的文本内容",
    )
    scene_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="变更时的 Scene 索引锚点",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manual_edit",
        comment="来源: manual_edit / ai_extraction / manual_rollback",
    )
    meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<TextArchive id={self.id} entity={self.entity_id} "
            f"field={self.field_name} scene={self.scene_index}>"
        )
