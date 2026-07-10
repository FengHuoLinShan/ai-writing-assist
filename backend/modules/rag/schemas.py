"""
RAG Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ============================================================
# 请求 Schema
# ============================================================


class RagChunkCreate(BaseModel):
    """创建 RAG 片段请求"""

    source_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "来源类型（chapter_text / world_entity / character / memory / outline）"
        ),
    )
    source_id: str | None = Field(
        None,
        description="来源对象 ID (UUID hex string)",
    )
    content_mode: Literal["canonical", "working"] = "canonical"
    source_content_hash: str | None = Field(None, min_length=64, max_length=64)
    chapter_index: int | None = Field(
        None,
        ge=1,
        description="关联章节索引（从 1 开始）",
    )
    chunk_index: int | None = Field(
        None,
        ge=0,
        description="章节内 chunk 序号（从 0 开始）",
    )
    start_offset: int | None = Field(
        None,
        ge=0,
        description="chunk 在原始章节正文中的起始字符位置",
    )
    end_offset: int | None = Field(
        None,
        ge=0,
        description="chunk 在原始章节正文中的结束字符位置",
    )
    char_count: int | None = Field(
        None,
        ge=0,
        description="chunk 正文字符数",
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
    scene_id: str | None = Field(
        None,
        description="关联的 Scene ID (UUID hex string)",
    )
    scene_span_id: str | None = Field(
        None,
        description="关联的 SceneSpan ID (UUID hex string)",
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
    index_version: str = Field(
        default="legacy",
        max_length=32,
        description="RAG 索引版本",
    )
    embedding_status: str = Field(
        default="pending",
        max_length=32,
        description="embedding 状态",
    )
    embedding_error: str | None = Field(
        None,
        description="embedding 失败原因",
    )
    index_warnings: list[str] = Field(
        default_factory=list,
        description="索引过程告警",
    )
    meta: dict = Field(
        default_factory=dict,
        description="扩展元数据",
    )

    @field_validator("index_version")
    @classmethod
    def validate_index_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("index_version 不能为空")
        return normalized


class RagQuery(BaseModel):
    """RAG 检索请求"""

    query: str = Field(
        ...,
        min_length=1,
        description="检索查询文本",
    )
    content_mode: Literal["canonical", "working"] = "canonical"
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
    visible_until_chapter: int | None = Field(
        None,
        ge=1,
        description="读者进度上界；只召回该章节及之前的片段",
    )
    scene_id: str | None = Field(
        None,
        description="限制关联 Scene ID (UUID hex string)",
    )
    strict_scene_filter: bool = Field(
        False,
        description="是否严格按 Scene 过滤，排除未标注 Scene 的片段",
    )
    visibility: str | None = Field(
        None,
        description="可见性过滤（author_only / reader_known / public，不传则不限制）",
    )
    mode: Literal["search", "context", "extraction"] = Field(
        default="search",
        description="检索模式：search / context / extraction",
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


class RagRebuildRequest(BaseModel):
    """项目级 RAG 重建请求"""

    novel_id: str = Field(
        ...,
        min_length=1,
        description="小说项目 ID (UUID hex string)",
    )
    content_mode: Literal["canonical", "working"] = "canonical"
    start_chapter: int | None = Field(
        None,
        ge=1,
        description="起始章节索引（从 1 开始，包含）",
    )
    end_chapter: int | None = Field(
        None,
        ge=1,
        description="结束章节索引（从 1 开始，包含）",
    )

    @model_validator(mode="after")
    def check_chapter_range(self) -> RagRebuildRequest:
        """当两者均提供时，结束章节必须不小于起始章节。"""
        if (
            self.start_chapter is not None
            and self.end_chapter is not None
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("end_chapter 必须大于等于 start_chapter")
        return self


class RagRetryEmbeddingsRequest(BaseModel):
    """失败 embedding 重试请求"""

    novel_id: str = Field(
        ...,
        min_length=1,
        description="小说项目 ID (UUID hex string)",
    )
    start_chapter: int | None = Field(
        None,
        ge=1,
        description="起始章节索引（从 1 开始，包含）",
    )
    end_chapter: int | None = Field(
        None,
        ge=1,
        description="结束章节索引（从 1 开始，包含）",
    )
    statuses: list[Literal["failed", "pending_vectorization"]] = Field(
        default_factory=lambda: ["failed", "pending_vectorization"],
        description="需要重试的 embedding 状态",
    )

    @model_validator(mode="after")
    def check_retry_request(self) -> RagRetryEmbeddingsRequest:
        if (
            self.start_chapter is not None
            and self.end_chapter is not None
            and self.end_chapter < self.start_chapter
        ):
            raise ValueError("end_chapter 必须大于等于 start_chapter")
        if not self.statuses:
            raise ValueError("statuses 不能为空")
        return self


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
    content_mode: str = "canonical"
    source_content_hash: str | None = None
    chapter_index: int | None = None
    chunk_index: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    char_count: int | None = None
    text: str
    summary: str | None = None
    entity_ids: list[str] = []
    character_ids: list[str] = []
    thread_ids: list[str] = []
    scene_id: str | None = None
    scene_span_id: str | None = None
    visibility: str = "author_only"
    importance: float = 0.5
    index_version: str = "legacy"
    embedding_status: str = "pending"
    embedding_error: str | None = None
    index_warnings: list[str] = []
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

    @field_validator("scene_id", "scene_span_id", mode="before")
    @classmethod
    def coerce_scene_ids(cls, v: object) -> str | None:
        """将 Scene 相关 UUID 转为字符串"""
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
    warnings: list[str] = []
    """检索过程告警"""
    degraded: bool = False
    """是否发生降级（如 embedding/LLM 不可用）"""


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
