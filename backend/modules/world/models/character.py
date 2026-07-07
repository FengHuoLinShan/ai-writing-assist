"""Character ORM models within the world module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .common import (
    JSON,
    PG_UUID,
    Base,
    ForeignKey,
    Integer,
    Mapped,
    StatusMixin,
    String,
    Text,
    TimestampMixin,
    UUIDMixin,
    mapped_column,
    relationship,
    uuid,
)

if TYPE_CHECKING:
    from .core import CoreEntity

# ============================================================
# Character — 人物扩展（从 character 模块迁入）
# ============================================================


class Character(Base, TimestampMixin, StatusMixin):
    """人物档案 — entity_id PK+FK → core_entities"""

    __tablename__ = "characters"
    __table_args__ = {"comment": "人物档案", "extend_existing": True}

    entity_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="人物名称",
    )
    aliases: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="别名列表 JSON（[{alias: str, type: str}]）",
    )
    role: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="角色定位（protagonist/antagonist/supporting/minor 等）",
    )
    appearance: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="外貌描述",
    )
    personality: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="性格描述",
    )
    desire: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="渴望/目标",
    )
    fear: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="恐惧/软肋",
    )
    secret: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="秘密（作者视角）",
    )
    weakness: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="弱点",
    )
    current_goal: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="当前短期目标",
    )
    current_state: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="当前状态摘要",
    )
    current_emotion: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="当前情绪",
    )
    stance: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="人物立场/态度",
    )
    voice_style: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="语言风格描述",
    )
    behavior_rules: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="行为规则列表 JSON",
    )
    relationship_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="人物关系摘要",
    )
    meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="扩展元数据（AI 抽取建议等）",
    )

    core_entity: Mapped[CoreEntity] = relationship(
        "CoreEntity",
        back_populates="character",
    )

    def __repr__(self) -> str:
        return f"<Character entity_id={self.entity_id} name={self.name!r}>"


# ============================================================
# CharacterKnowledge — 人物知识边界（从 character 模块迁入）
# ============================================================


class CharacterKnowledge(Base, UUIDMixin, TimestampMixin, StatusMixin):
    """人物知识边界 — 角色知道什么、不知道什么、误解什么"""

    __tablename__ = "character_knowledge"
    __table_args__ = {"comment": "人物知识边界"}

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("characters.entity_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="目标类型（entity/character/event/location 等）",
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="目标对象 ID",
    )
    knowledge_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
        comment="了解程度（unknown/rumor/partial/full/false_belief/restricted/misunderstood）",
    )
    known_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="角色已知的内容",
    )
    misconception: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="角色的误解内容（false_belief 或 misunderstood 时使用）",
    )
    source_chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="信息来源章节",
    )
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        comment="关联的 memory 记录 ID",
    )

    def __repr__(self) -> str:
        return (
            f"<CharacterKnowledge character={self.character_id} "
            f"target={self.target_type}:{self.target_id} "
            f"level={self.knowledge_level}>"
        )
