"""Facade 上下文输出 schema。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from modules.world.schemas._common import UuidStr

# Facade 输出 Schema（供其他模块读取/使用）
# ============================================================


class WorldEntityContext(BaseModel):
    """世界对象上下文 — 供其他模块读取的简化对象信息"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: UuidStr
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "canonical"
    aliases: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)


class WorldContextBundle(BaseModel):
    """世界上下文组合包 — 供 Context Compiler 或其他模块使用"""

    novel_id: str
    entities: list[WorldEntityContext] = Field(default_factory=list)
    total_count: int = 0
    reveal_mode: str = "author_safe"


class CharacterContextItem(BaseModel):
    """人物上下文中单个人物的信息"""

    model_config = ConfigDict(from_attributes=True)

    character_id: str
    name: str
    role: str | None = None
    appearance: str | None = None
    personality: str | None = None
    desire: str | None = None
    fear: str | None = None
    secret: str | None = None
    weakness: str | None = None
    current_goal: str | None = None
    current_state: str | None = None
    current_emotion: str | None = None
    stance: str | None = None
    voice_style: str | None = None
    behavior_rules: list[dict] = []
    relationship_summary: str | None = None
    meta: dict = {}


class CharacterKnowledgeContext(BaseModel):
    """人物知识上下文 — 单条知识"""

    model_config = ConfigDict(from_attributes=True)

    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None


class CharacterContextBundle(BaseModel):
    """人物上下文聚合 — 返回给其他模块的完整人物信息包"""

    characters: list[CharacterContextItem] = Field(
        ...,
        description="人物列表",
    )
    total: int = Field(..., description="总人物数")
    reveal_mode: str = Field(
        default="author_safe",
        description="使用的揭示模式",
    )


class FilterContextRequest(BaseModel):
    """按人物知识过滤上下文的请求"""

    context_items: list[dict] = Field(
        ...,
        description="待过滤的上下文项列表",
    )


class FilterContextResponse(BaseModel):
    """按人物知识过滤上下文的结果"""

    filtered_items: list[dict] = Field(..., description="过滤后的上下文项列表")
    removed_count: int = Field(..., description="被移除的项数")
    replaced_count: int = Field(..., description="被替换为误解的项数")


class EventContext(BaseModel):
    """事件上下文 — 供其他模块使用"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
    entity_name: str
    timeline_order: int
    occurrence_time_label: str | None = None
    location_name: str | None = None


class EventsContextBundle(BaseModel):
    """事件上下文组合包"""

    novel_id: str
    events: list[EventContext] = Field(default_factory=list)
    total_count: int = 0
