"""
World ORM 模型 — v3 因果时空网

<<<<<<< HEAD
数据库表：
- core_entities: 共享核心实体表（取代 world_entities + entity_aliases）
- relationships: 对象间关系
- entity_candidates: AI 生成的候选对象池
=======
7 张表：
- core_entities: 统一核心实体（原 world_entities 改名）
- events: 事件扩展表（entity_id PK+FK）
- entity_relations: 关系边（UUID FK + 追溯字段）
- entity_revisions: 快照版本表
- characters: 人物扩展表（entity_id PK+FK，从 character 模块迁入）
- character_knowledge: 知识边界（从 character 模块迁入）
>>>>>>> origin/worktree-grill-v3

公共字段（name, aliases, summary 等）统一存储在 core_entities。
character/geo 子系统通过 1:1 FK (entity_id = PK) 扩展核心表。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
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
<<<<<<< HEAD
# CoreEntity — 共享核心实体表
# ============================================================

class CoreEntity(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """共享核心实体 — 所有子系统的公共字段统一存储"""

    __tablename__ = "core_entities"
    __table_args__ = {"comment": "共享核心实体表"}
=======
# CoreEntity — 统一核心实体
# ============================================================

class CoreEntity(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """统一核心实体 — 所有世界对象的正史记录"""

    __tablename__ = "core_entities"
    __table_args__ = {"comment": "统一核心实体（原 world_entities）"}
>>>>>>> origin/worktree-grill-v3

    entity_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
<<<<<<< HEAD
        comment="对象类型：character/location/faction/item/concept/event/creature/skill/rule/other",
=======
        comment="实体类型（自由字符串，如 character/faction/item/location/event）",
>>>>>>> origin/worktree-grill-v3
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="实体名称",
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
<<<<<<< HEAD
        comment="扩展信息 JSON",
=======
        comment="扩展信息 JSON（含动态属性、别名等）",
>>>>>>> origin/worktree-grill-v3
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

<<<<<<< HEAD
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
=======
    # 1:1 扩展
    event: Mapped["Event | None"] = relationship(
        "Event", back_populates="core_entity", uselist=False,
        foreign_keys="Event.entity_id",
    )
    character: Mapped["Character | None"] = relationship(
        "Character", back_populates="core_entity", uselist=False,
        foreign_keys="Character.entity_id",
    )

    # 1:N 关系
    source_relations: Mapped[list["EntityRelation"]] = relationship(
        "EntityRelation", back_populates="source",
        foreign_keys="EntityRelation.source_id",
    )
    target_relations: Mapped[list["EntityRelation"]] = relationship(
        "EntityRelation", back_populates="target",
        foreign_keys="EntityRelation.target_id",
    )

    # geo_location 使用字符串引用避免循环导入（详见 geo/models.py）
    geo_location: Mapped[list["GeoLocation"]] = relationship(
        "GeoLocation", uselist=False,
        primaryjoin="CoreEntity.id == foreign(GeoLocation.world_entity_id)",
        viewonly=True,
>>>>>>> origin/worktree-grill-v3
    )

    def __repr__(self) -> str:
        return f"<CoreEntity id={self.id} type={self.entity_type} name={self.name!r}>"
<<<<<<< HEAD


# 延迟导入避免循环引用（SQLAlchemy 标准模式）
from modules.character.models import Character  # noqa: E402, F401
from modules.geo.models import GeoLocation  # noqa: E402, F401
=======
>>>>>>> origin/worktree-grill-v3


# ============================================================
# Event — 事件扩展
# ============================================================

<<<<<<< HEAD
class Relationship(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """对象间关系边 — source_id/target_id 指向 core_entities.id"""
=======
class Event(Base, NovelMixin):
    """事件扩展表 — entity_id 为 PK+FK 1:1 绑定 CoreEntity"""
>>>>>>> origin/worktree-grill-v3

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

    core_entity: Mapped["CoreEntity"] = relationship(
        "CoreEntity", back_populates="event",
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
    __table_args__ = {"comment": "实体关系边"}

    novel_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
<<<<<<< HEAD
        comment="源对象 ID（core_entities.id UUID hex）",
=======
>>>>>>> origin/worktree-grill-v3
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
<<<<<<< HEAD
        comment="目标对象 ID（core_entities.id UUID hex）",
=======
>>>>>>> origin/worktree-grill-v3
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
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="canonical",
        comment="状态：canonical/deprecated",
    )

    source: Mapped["CoreEntity"] = relationship(
        "CoreEntity", back_populates="source_relations",
        foreign_keys=[source_id],
    )
    target: Mapped["CoreEntity"] = relationship(
        "CoreEntity", back_populates="target_relations",
        foreign_keys=[target_id],
    )

    def __repr__(self) -> str:
        return (
<<<<<<< HEAD
            f"<Relationship id={self.id} "
            f"{self.source_type}:{self.source_id} -> "
            f"{self.relation_type} -> "
            f"{self.target_type}:{self.target_id}>"
=======
            f"<EntityRelation id={self.id} "
            f"{self.source_id} → {self.relation_type} → {self.target_id}>"
>>>>>>> origin/worktree-grill-v3
        )


# ============================================================
<<<<<<< HEAD
# EntityCandidate — 候选对象池
# ============================================================

class EntityCandidate(Base, UUIDMixin, TimestampMixin, StatusMixin, NovelMixin):
    """AI 生成的世界对象候选 — 确认后进入 core_entities"""

    __tablename__ = "entity_candidates"
    __table_args__ = {"comment": "世界对象候选池"}
=======
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
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<EntityRevision id={self.id} entity={self.entity_id} reason={self.revision_reason}>"


# ============================================================
# Character — 人物扩展（从 character 模块迁入）
# ============================================================

class Character(Base, TimestampMixin, StatusMixin):
    """人物档案 — entity_id PK+FK → core_entities"""

    __tablename__ = "characters"
    __table_args__ = {"comment": "人物档案"}
>>>>>>> origin/worktree-grill-v3

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

    core_entity: Mapped["CoreEntity"] = relationship(
        "CoreEntity", back_populates="character",
    )

    def __repr__(self) -> str:
        return f"<Character entity_id={self.entity_id} name={self.name!r}>"


# ============================================================
# 向后兼容别名（已废弃）
# ============================================================

WorldEntity = CoreEntity
WorldEntityAlias = object  # 别名模型已废弃
EntityCandidate = object  # 候选模型已废弃
Relationship = object  # 关系模型已废弃
EntityAlias = object  # 别名模型已废弃


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
        PG_UUID(as_uuid=True),
        nullable=True,
        comment="关联的 memory 记录 ID",
    )
<<<<<<< HEAD
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
=======
>>>>>>> origin/worktree-grill-v3

    def __repr__(self) -> str:
        return (
            f"<CharacterKnowledge character={self.character_id} "
            f"target={self.target_type}:{self.target_id} "
            f"level={self.knowledge_level}>"
        )


# 需要 datetime/function 用于 EntityRevision.created_at
from datetime import datetime, timezone  # noqa: E402
from sqlalchemy import DateTime, func  # noqa: E402
