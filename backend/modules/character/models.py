"""
Character ORM 模型

对应数据库 characters 扩展表和 character_knowledge 表。
Character 以 entity_id 为 PK+FK（1:1 关联 core_entities），仅存储人物特有字段。
公共字段（name, aliases, summary 等）在 core_entities 中。
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, StatusMixin, TimestampMixin, UUIDMixin


class Character(Base):
    """人物档案扩展表 — 仅存储人物特有字段，公共字段在 core_entities"""

    __tablename__ = "characters"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        primary_key=True,
        comment="人物 entity_id = core_entities.id",
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="小说项目 ID",
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
        comment="行为规则列表 JSONB",
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
    created_at = TimestampMixin.created_at  # type: ignore[assignment]
    updated_at = TimestampMixin.updated_at  # type: ignore[assignment]

    # ORM 关系：1:1 回到 core_entities
    core_entity: Mapped["CoreEntity"] = relationship(
        "CoreEntity", back_populates="character",
        primaryjoin="Character.entity_id == foreign(CoreEntity.id)",
    )

    def __repr__(self) -> str:
        return f"<Character entity_id={self.entity_id}>"


class CharacterKnowledge(Base, UUIDMixin, TimestampMixin, StatusMixin):
    """人物知识边界 — 角色知道什么、不知道什么、误解什么"""

    __tablename__ = "character_knowledge"

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="小说项目 ID",
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("core_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="人物 entity_id（core_entities.id, entity_type='character'）",
    )
    target_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="目标类型（entity/character/event/location 等）",
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="目标对象 ID",
    )
    knowledge_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
        comment="了解程度（unknown/rumor/partial/full/false_belief）",
    )
    known_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="角色已知的内容",
    )
    misconception: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="角色的误解内容（仅 false_belief 时使用）",
    )
    source_chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="信息来源章节",
    )
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="关联的 memory 记录 ID",
    )

    def __repr__(self) -> str:
        return (
            f"<CharacterKnowledge character={self.character_id} "
            f"target={self.target_type}:{self.target_id} "
            f"level={self.knowledge_level}>"
        )


# 延迟导入避免循环引用
from modules.world.models import CoreEntity  # noqa: E402, F401
