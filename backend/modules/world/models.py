"""
World ORM 模型

数据库表：
- core_entities: 共享核心实体表（取代 world_entities + entity_aliases）
- relationships: 对象间关系
- entity_candidates: AI 生成的候选对象池

公共字段（name, aliases, summary 等）统一存储在 core_entities。
character/geo 子系统通过 1:1 FK (entity_id = PK) 扩展核心表。
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin

try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]

    _HAS_PGVECTOR = True
except ImportError:
    _HAS_PGVECTOR = False


def _vector_column(dim: int = 1024):
    """返回 pgvector Vector 列或 Text 回退列（用于 SQLite 测试）"""
    if _HAS_PGVECTOR:
        from pgvector.sqlalchemy import Vector

        return mapped_column(Vector(dim), nullable=True)
    return mapped_column(Text, nullable=True, comment="embedding 向量（JSON 序列化）")


# ============================================================
# CoreEntity — 共享核心实体表
# ============================================================

class CoreEntity(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """共享核心实体 — 所有子系统的公共字段统一存储"""

    __tablename__ = "core_entities"
    __table_args__ = {"comment": "共享核心实体表"}

    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="对象类型：character/location/faction/item/concept/event/creature/skill/rule/other",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="对象名称",
    )
    aliases: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
        comment="别名列表 JSONB [{alias: str, type: str}]",
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
        comment="扩展信息 JSON",
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

    # 延迟引用避免循环 import
    character: Mapped["Character | None"] = relationship(
        "Character", back_populates="core_entity", uselist=False,
        cascade="all, delete-orphan",
        primaryjoin="CoreEntity.id == foreign(Character.entity_id)",
    )
    geo_location: Mapped["GeoLocation | None"] = relationship(
        "GeoLocation", back_populates="core_entity", uselist=False,
        cascade="all, delete-orphan",
        primaryjoin="CoreEntity.id == foreign(GeoLocation.entity_id)",
    )

    def __repr__(self) -> str:
        return f"<CoreEntity id={self.id} type={self.entity_type} name={self.name!r}>"


# 延迟导入避免循环引用（SQLAlchemy 标准模式）
from modules.character.models import Character  # noqa: E402, F401
from modules.geo.models import GeoLocation  # noqa: E402, F401


# ============================================================
# Relationship — 对象间关系
# ============================================================

class Relationship(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """对象间关系边 — source_id/target_id 指向 core_entities.id"""

    __tablename__ = "relationships"
    __table_args__ = {"comment": "对象间关系边"}

    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="源对象类型",
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="源对象 ID（core_entities.id UUID hex）",
    )
    target_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="目标对象类型",
    )
    target_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="目标对象 ID（core_entities.id UUID hex）",
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="关系类型",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="关系描述",
    )
    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="author_only",
        comment="可见性：author_only/author_safe/reader_known/public",
    )
    strength: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="关系强度 0.0~1.0",
    )

    def __repr__(self) -> str:
        return (
            f"<Relationship id={self.id} "
            f"{self.source_type}:{self.source_id} -> "
            f"{self.relation_type} -> "
            f"{self.target_type}:{self.target_id}>"
        )


# ============================================================
# EntityCandidate — 候选对象池
# ============================================================

class EntityCandidate(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """AI 生成的世界对象候选 — 确认后进入 core_entities"""

    __tablename__ = "entity_candidates"
    __table_args__ = {"comment": "世界对象候选池"}

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="候选对象名称",
    )
    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="候选对象类型",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="候选对象概要",
    )
    source_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="来源文本摘录",
    )
    source_chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="来源章节索引",
    )
    importance_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="重要性评分 0.0~1.0",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        comment="置信度 0.0~1.0",
    )
    candidate_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="推荐该候选对象的理由",
    )
    suggested_action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="needs_user_decision",
        comment="建议动作",
    )
    suggested_existing_entity_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="建议关联的已有对象 ID（core_entities.id）",
    )
    embedding_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用于向量化的文本",
    )
    embedding = _vector_column()

    def __repr__(self) -> str:
        return f"<EntityCandidate id={self.id} name={self.name!r} action={self.suggested_action}>"
