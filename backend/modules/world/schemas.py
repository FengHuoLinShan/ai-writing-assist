"""
World Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# 内部工具
# ============================================================

def _uuid_validator(v: object) -> str:
    """将 UUID 原始值转为字符串"""
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


# ============================================================
# WorldEntity Schema
# ============================================================

class WorldEntityCreate(BaseModel):
    """创建世界对象请求"""

    entity_type: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="对象类型：location/faction/item/event/rule/power_system/secret/legend/resource/character_ref",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="对象名称",
    )
    summary: str | None = Field(
        None,
        description="概要",
    )
    public_info: str | None = Field(
        None,
        description="对外公开信息",
    )
    hidden_truth: str | None = Field(
        None,
        description="隐藏真相（仅作者视角）",
    )
    content_json: dict | None = Field(
        default=None,
        description="扩展信息 JSON",
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="重要性 0.0~1.0",
    )
    importance_level: str = Field(
        default="normal",
        max_length=16,
        description="重要性级别：core/important/normal/temporary/alias",
    )
    reveal_level: str = Field(
        default="author_only",
        max_length=16,
        description="揭示层级：author_only/hinted/revealed/fully_known",
    )
    status: str = Field(
        default="draft",
        max_length=32,
        description="状态",
    )
    created_by: str | None = Field(
        None,
        max_length=64,
        description="创建者标识",
    )


class WorldEntityUpdate(BaseModel):
    """更新世界对象请求（所有字段可选）"""

    entity_type: Annotated[str | None, Field(None, min_length=1, max_length=32)]
    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    summary: Annotated[str | None, Field(None)]
    public_info: Annotated[str | None, Field(None)]
    hidden_truth: Annotated[str | None, Field(None)]
    content_json: Annotated[dict | None, Field(None)]
    importance: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    importance_level: Annotated[str | None, Field(None, max_length=16)]
    reveal_level: Annotated[str | None, Field(None, max_length=16)]
    status: Annotated[str | None, Field(None, max_length=32)]
    approved_by: Annotated[str | None, Field(None, max_length=64)]


class WorldEntityResponse(BaseModel):
    """世界对象响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    entity_type: str
    name: str
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    content_json: dict | None = None
    importance: float = 0.5
    importance_level: str = "normal"
    reveal_level: str = "author_only"
    status: str = "draft"
    embedding_text: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# Relationship Schema
# ============================================================

class RelationshipCreate(BaseModel):
    """创建关系请求"""

    source_type: str = Field(
        ...,
        max_length=32,
        description="源对象类型",
    )
    source_id: str = Field(
        ...,
        description="源对象 ID",
    )
    target_type: str = Field(
        ...,
        max_length=32,
        description="目标对象类型",
    )
    target_id: str = Field(
        ...,
        description="目标对象 ID",
    )
    relation_type: str = Field(
        ...,
        max_length=32,
        description="关系类型",
    )
    description: str | None = Field(
        None,
        description="关系描述",
    )
    visibility: str = Field(
        default="author_only",
        max_length=20,
        description="可见性：author_only/author_safe/reader_known/public",
    )
    strength: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="关系强度 0.0~1.0",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )


class RelationshipUpdate(BaseModel):
    """更新关系请求（所有字段可选）"""

    source_type: Annotated[str | None, Field(None, max_length=32)]
    source_id: Annotated[str | None, Field(None)]
    target_type: Annotated[str | None, Field(None, max_length=32)]
    target_id: Annotated[str | None, Field(None)]
    relation_type: Annotated[str | None, Field(None, max_length=32)]
    description: Annotated[str | None, Field(None)]
    visibility: Annotated[str | None, Field(None, max_length=20)]
    strength: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    status: Annotated[str | None, Field(None, max_length=32)]


class RelationshipResponse(BaseModel):
    """关系响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    description: str | None = None
    visibility: str = "author_only"
    strength: float = 0.5
    status: str = "canonical"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# EntityAlias Schema
# ============================================================

class EntityAliasCreate(BaseModel):
    """创建别名请求"""

    entity_id: str = Field(
        ...,
        description="所属世界对象 ID",
    )
    alias: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="别名文本",
    )
    alias_type: str = Field(
        default="name",
        max_length=20,
        description="别名类型：name/title/nickname/alias/translation/abbreviation",
    )
    source_chapter_index: int | None = Field(
        None,
        ge=0,
        description="首次出现的章节索引",
    )
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="确认置信度",
    )
    status: str = Field(
        default="confirmed",
        max_length=32,
        description="状态",
    )


class EntityAliasResponse(BaseModel):
    """别名响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    entity_id: str
    alias: str
    alias_type: str = "name"
    source_chapter_index: int | None = None
    confidence: float = 0.8
    status: str = "confirmed"
    created_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# EntityCandidate Schema
# ============================================================

class EntityCandidateCreate(BaseModel):
    """创建候选对象请求"""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="候选对象名称",
    )
    entity_type: str = Field(
        ...,
        max_length=32,
        description="候选对象类型",
    )
    summary: str | None = Field(
        None,
        description="候选概要",
    )
    source_text: str | None = Field(
        None,
        description="来源文本摘录",
    )
    source_chapter_index: int | None = Field(
        None,
        ge=0,
        description="来源章节索引",
    )
    importance_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="重要性评分",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="置信度",
    )
    candidate_reason: str | None = Field(
        None,
        description="推荐理由",
    )
    suggested_action: str = Field(
        default="needs_user_decision",
        max_length=32,
        description="建议动作",
    )
    suggested_existing_entity_id: str | None = Field(
        None,
        description="建议关联的已有对象 ID",
    )
    status: str = Field(
        default="pending",
        max_length=32,
        description="状态",
    )


class EntityCandidateUpdate(BaseModel):
    """更新候选对象请求（所有字段可选）"""

    name: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    entity_type: Annotated[str | None, Field(None, max_length=32)]
    summary: Annotated[str | None, Field(None)]
    source_text: Annotated[str | None, Field(None)]
    source_chapter_index: Annotated[int | None, Field(None, ge=0)]
    importance_score: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    confidence: Annotated[float | None, Field(None, ge=0.0, le=1.0)]
    candidate_reason: Annotated[str | None, Field(None)]
    suggested_action: Annotated[str | None, Field(None, max_length=32)]
    suggested_existing_entity_id: Annotated[str | None, Field(None)]
    status: Annotated[str | None, Field(None, max_length=32)]


class EntityCandidateResponse(BaseModel):
    """候选对象响应"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    novel_id: str
    name: str
    entity_type: str
    summary: str | None = None
    source_text: str | None = None
    source_chapter_index: int | None = None
    importance_score: float = 0.5
    confidence: float = 0.5
    candidate_reason: str | None = None
    suggested_action: str = "needs_user_decision"
    suggested_existing_entity_id: str | None = None
    status: str = "pending"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# 列表响应
# ============================================================

class WorldEntityListResponse(BaseModel):
    """世界对象列表响应"""

    items: list[WorldEntityResponse]
    total: int


class RelationshipListResponse(BaseModel):
    """关系列表响应"""

    items: list[RelationshipResponse]
    total: int


class EntityAliasListResponse(BaseModel):
    """别名列表响应"""

    items: list[EntityAliasResponse]
    total: int


class EntityCandidateListResponse(BaseModel):
    """候选对象列表响应"""

    items: list[EntityCandidateResponse]
    total: int


# ============================================================
# Facade 输出 Schema（供其他模块读取）
# ============================================================

class WorldEntityContext(BaseModel):
    """世界对象上下文 — 供其他模块读取的简化对象信息"""

    model_config = ConfigDict(from_attributes=True)

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
    aliases: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)

    @field_validator("entity_id", mode="before")
    @classmethod
    def coerce_entity_id(cls, v: object) -> str:
        return _uuid_validator(v)


class WorldContextBundle(BaseModel):
    """世界上下文组合包 — 供 Context Compiler 或其他模块使用"""

    novel_id: str
    entities: list[WorldEntityContext] = Field(default_factory=list)
    total_count: int = 0
    reveal_mode: str = "author_safe"


class DuplicateSuggestionResult(BaseModel):
    """去重建议结果"""

    candidate_id: str
    candidate_name: str
    existing_entity_id: str
    existing_entity_name: str
    similarity_score: float
    match_method: str
    action: str
