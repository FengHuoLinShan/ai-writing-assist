"""
RAG Pydantic Schema 定义

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

class RagChunkCreate(BaseModel):
    """创建 RAG 片段请求"""

    source_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="来源类型（chapter_text / world_entity / character / memory / outline）",
    )
    source_id: str | None = Field(
        None,
        description="来源对象 ID (UUID hex string)",
    )
    chapter_index: int | None = Field(
        None,
        ge=1,
        description="关联章节索引（从 1 开始）",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="片段文本内容",
    )
    summary: str | None = Field(
        None,
        description="片段摘要（可选，用于检索预览）",
    )
    entity_ids: list[str] = Field(
        default_factory=list,
        description="关联的世界对象 ID 列表",
    )
    character_ids: list[str] = Field(
        default_factory=list,
        description="关联的人物 ID 列表",
    )
    thread_ids: list[str] = Field(
        default_factory=list,
        description="关联的剧情线 ID 列表",
    )
    visibility: str = Field(
        default="author_only",
        max_length=32,
        description="信息可见性",
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="重要性评分（0.0-1.0）",
    )
    meta: dict = Field(
        default_factory=dict,
        description="扩展元数据",
    )


class RagQuery(BaseModel):
    """RAG 检索请求"""

    query: str = Field(
        ...,
        min_length=1,
        description="检索查询文本",
    )
    entity_ids: list[str] | None = Field(
        None,
        description="限制关联的世界对象 ID 列表",
    )
    character_ids: list[str] | None = Field(
        None,
        description="限制关联的人物 ID 列表",
    )
    thread_ids: list[str] | None = Field(
        None,
        description="限制关联的剧情线 ID 列表",
    )
    chapter_index: int | None = Field(
        None,
        ge=1,
        description="限制关联章节索引",
    )
    top_k: int = Field(
        default=12,
        ge=1,
        le=50,
        description="返回的最大结果数",
    )


# ============================================================
# 响应 Schema
# ============================================================

class RagChunkResponse(BaseModel):
    """RAG 片段响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    source_type: str
    source_id: str | None = None
    chapter_index: int | None = None
    text: str
    summary: str | None = None
    entity_ids: list[str] = []
    character_ids: list[str] = []
    thread_ids: list[str] = []
    visibility: str = "author_only"
    importance: float = 0.5
    meta: dict = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # 检索结果附加字段（检索时填充）
    score: float | None = Field(
        None,
        description="混合检索评分（仅在检索结果中填充）",
    )

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str:
        """将 UUID 属性的原始值转为字符串"""
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)

    @field_validator("source_id", mode="before")
    @classmethod
    def coerce_source_id(cls, v: object) -> str | None:
        """将 source_id UUID 转为字符串"""
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return None


class RagResult(BaseModel):
    """RAG 检索结果"""

    chunks: list[RagChunkResponse]
    """检索到的片段列表（按评分降序）"""
    total: int
    """匹配总数"""
    query: str
    """原始查询文本"""


class SimilarEntity(BaseModel):
    """相似实体结果"""

    entity_id: str = Field(
        ...,
        description="实体 ID (UUID hex string)",
    )
    name: str = Field(
        ...,
        description="实体名称",
    )
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="相似度评分（0.0-1.0）",
    )


class SimilarEntityResponse(BaseModel):
    """相似实体检索响应"""

    items: list[SimilarEntity]
    """相似实体列表"""
    total: int
    """结果总数"""
