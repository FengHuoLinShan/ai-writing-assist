"""
Character Pydantic Schema 定义

Character 现在是扩展表（entity_id PK+FK → core_entities）。
公共字段（name, aliases, status）在 core_entities，此模块只处理特有字段。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# Request schemas
# ============================================================

class CharacterCreate(BaseModel):
    """创建人物扩展记录 — 在 core_entities 已创建后调用"""

    entity_id: str = Field(
        ...,
        description="人物 entity_id = core_entities.id",
    )
    novel_id: str = Field(
        ...,
        description="小说项目 ID",
    )
    role: str | None = Field(None, max_length=64, description="角色定位")
    appearance: str | None = Field(None, description="外貌描述")
    personality: str | None = Field(None, description="性格描述")
    desire: str | None = Field(None, description="渴望/目标")
    fear: str | None = Field(None, description="恐惧/软肋")
    secret: str | None = Field(None, description="秘密（作者视角）")
    weakness: str | None = Field(None, description="弱点")
    current_goal: str | None = Field(None, description="当前短期目标")
    current_state: str | None = Field(None, description="当前状态摘要")
    current_emotion: str | None = Field(None, max_length=64, description="当前情绪")
    stance: str | None = Field(None, description="人物立场/态度")
    voice_style: str | None = Field(None, description="语言风格描述")
    behavior_rules: list[dict] = Field(default_factory=list, max_length=50, description="行为规则列表")
    relationship_summary: str | None = Field(None, description="人物关系摘要")
    meta: dict = Field(default_factory=dict, description="扩展元数据")


class CharacterUpdate(BaseModel):
    """更新人物扩展字段（所有字段可选）"""

    role: Annotated[str | None, Field(None, max_length=64)]
    appearance: Annotated[str | None, Field(None)]
    personality: Annotated[str | None, Field(None)]
    desire: Annotated[str | None, Field(None)]
    fear: Annotated[str | None, Field(None)]
    secret: Annotated[str | None, Field(None)]
    weakness: Annotated[str | None, Field(None)]
    current_goal: Annotated[str | None, Field(None)]
    current_state: Annotated[str | None, Field(None)]
    current_emotion: Annotated[str | None, Field(None, max_length=64)]
    stance: Annotated[str | None, Field(None)]
    voice_style: Annotated[str | None, Field(None)]
    behavior_rules: Annotated[list[dict] | None, Field(None)]
    relationship_summary: Annotated[str | None, Field(None)]
    meta: Annotated[dict | None, Field(None)]


class CharacterKnowledgeCreate(BaseModel):
    """创建人物知识记录请求"""

    novel_id: str = Field(..., description="小说项目 ID")
    character_id: str = Field(..., description="人物 entity_id（core_entities.id）")
    target_type: str = Field(..., max_length=64, description="目标类型")
    target_id: str = Field(..., description="目标对象 ID")
    knowledge_level: str = Field(..., max_length=32, description="了解程度（unknown/rumor/partial/full/false_belief）")
    known_content: str | None = Field(None, description="角色已知的内容")
    misconception: str | None = Field(None, description="角色的误解内容")
    source_chapter_index: int | None = Field(None, ge=0, description="信息来源章节")
    source_memory_id: str | None = Field(None, description="关联的 memory 记录 ID")
    status: str = Field(default="canonical", max_length=32, description="状态")


class CharacterKnowledgeUpdate(BaseModel):
    """更新人物知识记录请求"""

    knowledge_level: Annotated[str | None, Field(None, max_length=32)]
    known_content: Annotated[str | None, Field(None)]
    misconception: Annotated[str | None, Field(None)]
    source_chapter_index: Annotated[int | None, Field(None, ge=0)]
    source_memory_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


# ============================================================
# Response schemas
# ============================================================

class CharacterResponse(BaseModel):
    """人物扩展记录响应 — 不包含 name/aliases/status（在 core_entities）"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    entity_id: str
    novel_id: str
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
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("entity_id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class CharacterKnowledgeResponse(BaseModel):
    """人物知识响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    character_id: str
    target_type: str
    target_id: str
    knowledge_level: str
    known_content: str | None = None
    misconception: str | None = None
    source_chapter_index: int | None = None
    source_memory_id: str | None = None
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "character_id", "target_id", "source_memory_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class CharacterListResponse(BaseModel):
    """人物列表响应"""

    items: list[CharacterResponse]
    total: int


class CharacterKnowledgeListResponse(BaseModel):
    """人物知识列表响应"""

    items: list[CharacterKnowledgeResponse]
    total: int


# ============================================================
# Filter-Context schemas
# ============================================================

class FilterContextRequest(BaseModel):
    """按人物知识过滤上下文的请求"""

    context_items: list[dict] = Field(..., description="待过滤的上下文项列表")


class FilterContextResponse(BaseModel):
    """按人物知识过滤上下文的结果"""

    filtered_items: list[dict] = Field(..., description="过滤后的上下文项列表")
    removed_count: int = Field(..., description="被移除的项数")
    replaced_count: int = Field(..., description="被替换为误解的项数")


# ============================================================
# Facade output schemas
# ============================================================

class CharacterContextItem(BaseModel):
    """人物上下文中单个人物的信息"""

    model_config = ConfigDict(from_attributes=True)

    entity_id: str
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
    """人物上下文聚合"""

    characters: list[CharacterContextItem] = Field(..., description="人物列表")
    total: int = Field(..., description="总人物数")
    reveal_mode: str = Field(default="author_safe", description="使用的揭示模式")
