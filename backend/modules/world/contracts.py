"""
World 对外契约 — v3 因果时空网

定义其他模块可以安全依赖的世界模块接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CoreEntityContract:
    """核心实体契约 — 其他模块通过此契约获取对象信息"""

    novel_id: str
    entity_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "draft"


@dataclass(frozen=True)
class EventContract:
    """事件契约"""

    novel_id: str
<<<<<<< HEAD
    """项目 ID"""
    relationship_id: str
    """关系 ID"""
    source_type: str
    """源对象类型"""
    source_id: str
    """源对象 ID"""
    target_type: str
    """目标对象类型"""
    target_id: str
    """目标对象 ID"""
    relation_type: str
    """关系类型"""
    description: str | None = None
    """关系描述"""
    visibility: str = "author_only"
    """可见性"""
    strength: float = 0.5
    """关系强度"""


@dataclass(frozen=True)
class EntityCandidateContract:
    """候选对象契约 — 其他模块通过此契约获取候选信息"""
=======
    entity_id: str
    entity_name: str
    entity_type: str = "event"
    timeline_order: int = 0
    occurrence_time_label: str | None = None
    location_entity_id: str | None = None
    location_name: str | None = None


@dataclass(frozen=True)
class EntityRelationContract:
    """关系契约"""
>>>>>>> origin/worktree-grill-v3

    novel_id: str
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    description: str | None = None
    strength: float = 0.5
    quote: str | None = None
    status: str = "canonical"


@dataclass(frozen=True)
class EntityRevisionContract:
    """版本快照契约"""

    entity_id: str
    revision_id: str
    revision_reason: str = "ai_import"
    created_at: str | None = None


@dataclass(frozen=True)
class CharacterContract:
    """人物契约 — 其他模块通过此契约获取人物信息"""

    character_id: str
    name: str
    role: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = field(default_factory=list)
    relationship_summary: str | None = None


@dataclass(frozen=True)
class CharacterKnowledgeContract:
    """人物知识契约 — 用于 Context Compiler 和 Review 模块"""

    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None


@dataclass(frozen=True)
class DuplicateSuggestion:
    """去重建议（向后兼容）"""
    candidate_id: str = ""
    candidate_name: str = ""
    existing_entity_id: str = ""
    existing_entity_name: str = ""
    similarity_score: float = 0.0
    match_method: str = ""
    action: str = "needs_user_decision"


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.world.schemas import (  # noqa: F401
<<<<<<< HEAD
    DuplicateSuggestionResult,
    WorldContextBundle,
    CoreEntityContext,
    CoreEntityResponse,
=======
    CharacterContextBundle,
    CharacterKnowledgeContext,
    CharacterResponse,
    CoreEntityResponse,
    DuplicateSuggestionResult,
    EntityRelationResponse,
    EventContext,
    EventsContextBundle,
    WorldContextBundle,
    WorldEntityContext,
>>>>>>> origin/worktree-grill-v3
)
