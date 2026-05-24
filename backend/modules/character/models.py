"""
Character ORM 模型

对应数据库 characters 表和 character_knowledge 表。
Person 模块属于事实层，依赖 project 模块提供 novel_id。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin


class Character(Base, UUIDMixin, NovelMixin, TimestampMixin, StatusMixin):
    """人物档案 — 小说人物核心数据"""

    __tablename__ = "characters"

    world_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联的世界对象 ID（可选）",
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
        comment="别名列表 JSONB（[{alias: str, type: str}]）",
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

    def __repr__(self) -> str:
        return f"<Character id={self.id} name={self.name!r}>"


class CharacterKnowledge(Base, UUIDMixin, StatusMixin):
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
        nullable=False,
        index=True,
        comment="人物 ID",
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
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        comment="创建时间",
    )

    def __repr__(self) -> str:
        return (
            f"<CharacterKnowledge character={self.character_id} "
            f"target={self.target_type}:{self.target_id} "
            f"level={self.knowledge_level}>"
        )
