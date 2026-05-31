"""
Character ORM 模型（旧兼容 — 核心模型已迁入 modules.world.models）
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin


class Character(Base, UUIDMixin, NovelMixin, TimestampMixin, StatusMixin):
    """人物档案（旧兼容 — 使用 world.models.Character）"""

    __tablename__ = "characters"
    __table_args__ = {"extend_existing": True}

    world_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    appearance: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    desire: Mapped[str | None] = mapped_column(Text, nullable=True)
    fear: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    weakness: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_emotion: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stance: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voice_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    behavior_rules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    relationship_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:
        return f"<Character id={self.id} name={self.name!r}>"


class CharacterKnowledge(Base, UUIDMixin, TimestampMixin, StatusMixin):
    """人物知识边界（旧兼容 — 使用 world.models.CharacterKnowledge）"""

    __tablename__ = "character_knowledge"
    __table_args__ = {"extend_existing": True}

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    character_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True,
    )
    knowledge_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown",
    )
    known_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    misconception: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<CharacterKnowledge character={self.character_id} "
            f"target={self.target_type}:{self.target_id} "
            f"level={self.knowledge_level}>"
        )
