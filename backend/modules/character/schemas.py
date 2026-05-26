"""
Character Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# 请求 Schema
# ============================================================

class CharacterCreate(BaseModel):
    """创建人物请求"""

    novel_id: str = Field(
        ...,
        description="小说项目 ID",
    )
    world_entity_id: str | None = Field(
        None,
        description="关联的世界对象 ID",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="人物名称",
    )
    aliases: list[dict] = Field(
        default_factory=list,
        description="别名列表 JSONB（[{alias: str, type: str}]）",
    )
    role: str | None = Field(
        None,
        max_length=64,
        description="角色定位",
    )
    appearance: str | None = Field(
        None,
        description="外貌描述",
    )
    personality: str | None = Field(
        None,
        description="性格描述",
    )
    desire: str | None = Field(
        None,
        description="渴望/目标",
    )
    fear: str | None = Field(
        None,
        description="恐惧/软肋",
    )
    secret: str | None = Field(
        None,
        description="秘密（作者视角）",
    )
    weakness: str | None = Field(
        None,
        description="弱点",
    )
    current_goal: str | None = Field(
        None,
        description="当前短期目标",
    )
    current_state: str | None = Field(
        None,
        description="当前状态摘要",
    )
    current_emotion: str | None = Field(
        None,
        max_length=64,
        description="当前情绪",
    )
    stance: str | None = Field(
        None,
        description="人物立场/态度",
    )
    voice_style: str | None = Field(
        None,
        description="语言风格描述",
    )
    behavior_rules: list[dict] = Field(
        default_factory=list,
        max_length=50,
        description="行为规则列表 JSONB（最多 50 条）",
    )
    relationship_summary: str | None = Field(
        None,
        description="人物关系摘要",
    )
    meta: dict = Field(
        default_factory=dict,
        description="扩展元数据",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )


class CharacterUpdate(BaseModel):
    """更新人物请求（所有字段可选）"""

    world_entity_id: Annotated[str | None, Field(None, description="关联的世界对象 ID")]
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    aliases: Annotated[list[dict] | None, Field(None)]
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
    status: Annotated[str | None, Field(None, max_length=32)]


class CharacterKnowledgeCreate(BaseModel):
    """创建人物知识记录请求"""

    novel_id: str = Field(
        ...,
        description="小说项目 ID",
    )
    character_id: str = Field(
        ...,
        description="人物 ID",
    )
    target_type: str = Field(
        ...,
        max_length=64,
        description="目标类型（entity/character/event/location 等）",
    )
    target_id: str = Field(
        ...,
        description="目标对象 ID",
    )
    knowledge_level: str = Field(
        ...,
        max_length=32,
        description="了解程度（unknown/rumor/partial/full/false_belief）",
    )
    known_content: str | None = Field(
        None,
        description="角色已知的内容",
    )
    misconception: str | None = Field(
        None,
        description="角色的误解内容（仅 false_belief 时使用）",
    )
    source_chapter_index: int | None = Field(
        None,
        ge=0,
        description="信息来源章节",
    )
    source_memory_id: str | None = Field(
        None,
        description="关联的 memory 记录 ID",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )


class CharacterKnowledgeUpdate(BaseModel):
    """更新人物知识记录请求（所有字段可选）"""

    knowledge_level: Annotated[str | None, Field(None, max_length=32)]
    known_content: Annotated[str | None, Field(None)]
    misconception: Annotated[str | None, Field(None)]
    source_chapter_index: Annotated[int | None, Field(None, ge=0)]
    source_memory_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


# ============================================================
# 响应 Schema
# ============================================================

class CharacterResponse(BaseModel):
    """人物响应 — 从 ORM 转换"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    world_entity_id: str | None = None
    name: str
    aliases: list[dict] = []
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
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)

    @field_validator("world_entity_id", mode="before")
    @classmethod
    def coerce_optional_uuid_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class CharacterKnowledgeResponse(BaseModel):
    """人物知识响应 — 从 ORM 转换"""

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
# Filter-Context 相关 Schema
# ============================================================

class FilterContextRequest(BaseModel):
    """按人物知识过滤上下文的请求"""

    context_items: list[dict] = Field(
        ...,
        description="待过滤的上下文项列表，每项应包含 target_type、target_id 等字段",
    )


class FilterContextResponse(BaseModel):
    """按人物知识过滤上下文的结果"""

    filtered_items: list[dict] = Field(
        ...,
        description="过滤后的上下文项列表",
    )
    removed_count: int = Field(
        ...,
        description="被移除的项数",
    )
    replaced_count: int = Field(
        ...,
        description="被替换为误解的项数",
    )


# ============================================================
# Facade 输出 Schema（供其他模块读取/使用）
# ============================================================

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
    total: int = Field(
        ...,
        description="总人物数",
    )
    reveal_mode: str = Field(
        default="author_safe",
        description="使用的揭示模式",
    )
