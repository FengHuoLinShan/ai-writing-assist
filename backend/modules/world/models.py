"""
World ORM 模型

对应 4 张数据库表：
- world_entities: 世界对象正史库
- relationships: 对象间关系
- entity_aliases: 对象别名
- entity_candidates: AI 生成的候选对象池

生产环境 embedding 字段使用 pgvector Vector(1024) 类型。
测试环境（SQLite）使用 Text 存储 JSON 序列化的浮点数列表。
"""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base import Base, NovelMixin, StatusMixin, TimestampMixin, UUIDMixin

# 尝试导入 pgvector Vector 类型；不可用时回退到 Text
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
# WorldEntity — 世界对象正史库
# ============================================================

class WorldEntity(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """世界对象 — 需要长期维护的结构化创作资产"""

    __tablename__ = "world_entities"
    __table_args__ = {"comment": "世界对象正史库"}

    entity_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        comment="对象类型：location/faction/item/event/rule/power_system/secret/legend/resource/character_ref",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="对象名称",
    )
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="概要/简要描述",
    )
    public_info: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="对外公开信息（读者已知或角色可获取）",
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
        comment="扩展信息 JSON（生产环境使用 JSONB）",
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
        comment="重要性级别：core/important/normal/temporary/alias",
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

    # 别名通过 EntityAliasRepository 查询，不定义 ORM relationship

    def __repr__(self) -> str:
        return f"<WorldEntity id={self.id} type={self.entity_type} name={self.name!r}>"


# ============================================================
# Relationship — 对象间关系
# ============================================================

class Relationship(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """世界对象/人物之间的关系边"""

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
        comment="源对象 ID（UUID hex，通用引用，不强制 FK）",
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
        comment="目标对象 ID（UUID hex，通用引用，不强制 FK）",
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
            f"{self.source_type}:{self.source_id} → "
            f"{self.relation_type} → "
            f"{self.target_type}:{self.target_id}>"
        )


# ============================================================
# EntityAlias — 对象别名
# ============================================================

class EntityAlias(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """世界对象的别名/称号/化名

    别名不独立建 WorldEntity，而是关联到已有对象。
    避免同一个概念因为不同名称而被重复创建。
    """

    __tablename__ = "entity_aliases"
    __table_args__ = {"comment": "世界对象别名"}

    entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("world_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属对象 ID（UUID hex，FK -> world_entities.id）",
    )
    alias: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="别名文本",
    )
    alias_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="name",
        comment="别名类型：name/title/nickname/alias/translation/abbreviation",
    )
    source_chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="首次出现的章节索引",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.8,
        comment="别名确认置信度 0.0~1.0",
    )

    # 所属实体通过 EntityAliasRepository 查询，不定义 ORM relationship

    def __repr__(self) -> str:
        return f"<EntityAlias id={self.id} alias={self.alias!r} → entity={self.entity_id}>"


# ============================================================
# EntityCandidate — 候选对象池
# ============================================================

class EntityCandidate(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """AI 生成的世界对象候选

    AI 不直接创建正史对象。
    所有结构化生成的候选先进入此表，经去重、复查和用户确认后才进入 world_entities。
    """

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
        comment="建议动作：create_new/merge_with_existing/alias_of_existing/ignore/temporary_only/needs_user_decision",
    )
    suggested_existing_entity_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="建议关联的已有对象 ID（当 suggested_action 为 merge/alias 时使用）",
    )
    embedding_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用于向量化的文本",
    )
    embedding = _vector_column()

    def __repr__(self) -> str:
        return f"<EntityCandidate id={self.id} name={self.name!r} action={self.suggested_action}>"
