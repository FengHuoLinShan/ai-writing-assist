"""
Memory Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# 请求 Schema
# ============================================================

class MemoryRecordCreate(BaseModel):
    """创建记忆记录请求"""

    memory_type: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="记忆类型",
    )
    target_type: str | None = Field(
        None,
        max_length=64,
        description="关联目标类型",
    )
    target_id: str | None = Field(
        None,
        description="关联目标 ID (UUID hex)",
    )
    chapter_index: int | None = Field(
        None,
        ge=1,
        description="所属章节索引",
    )
    title: str | None = Field(
        None,
        max_length=255,
        description="记忆标题",
    )
    summary: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="记忆摘要",
    )
    content_json: dict[str, Any] = Field(
        default_factory=dict,
        description="详细内容",
    )
    visibility: str = Field(
        default="reader_known",
        max_length=32,
        description="可见性",
    )
    known_by_character_ids: list[str] = Field(
        default_factory=list,
        description="已知该记忆的角色 ID 列表",
    )
    related_entity_ids: list[str] = Field(
        default_factory=list,
        description="关联世界对象 ID 列表",
    )
    related_character_ids: list[str] = Field(
        default_factory=list,
        description="关联角色 ID 列表",
    )
    related_thread_ids: list[str] = Field(
        default_factory=list,
        description="关联剧情线 ID 列表",
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="重要性",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="状态",
    )
    source_text_excerpt: str | None = Field(
        None,
        description="来源文本摘录",
    )


class MemoryRecordUpdate(BaseModel):
    """更新记忆记录请求（所有字段可选）"""

    title: str | None = Field(None, max_length=255)
    summary: str | None = Field(None, min_length=1)
    content_json: dict[str, Any] | None = None
    visibility: str | None = Field(None, max_length=32)
    known_by_character_ids: list[str] | None = None
    importance: float | None = Field(None, ge=0.0, le=1.0)
    status: str | None = Field(None, max_length=32)


class MemoryProposalDecision(BaseModel):
    """处理记忆提案请求"""

    decision: str = Field(
        ...,
        pattern="^(approved|rejected)$",
        description="决策（approved / rejected）",
    )
    edited_payload: dict[str, Any] | None = Field(
        None,
        description="编辑后的提案内容（仅在 approved 时可用）",
    )
    decided_by: str | None = Field(
        None,
        max_length=128,
        description="决策者标识",
    )


# ============================================================
# 响应 Schema
# ============================================================

class MemoryRecordResponse(BaseModel):
    """记忆记录响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    memory_type: str
    target_type: str | None = None
    target_id: str | None = None
    chapter_index: int | None = None
    title: str | None = None
    summary: str
    content_json: dict[str, Any] = {}
    visibility: str = "reader_known"
    known_by_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_character_ids: list[str] = []
    related_thread_ids: list[str] = []
    importance: float = 0.5
    status: str = "canonical"
    source_text_excerpt: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "id",
        "novel_id",
        "target_id",
        mode="before",
    )
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str | None:
        """将 UUID 转为字符串"""
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)

    @field_validator(
        "known_by_character_ids",
        "related_entity_ids",
        "related_character_ids",
        "related_thread_ids",
        mode="before",
    )
    @classmethod
    def coerce_jsonb_list(cls, v: object) -> list[str]:
        """确保 JSONB 列表字段为 list[str]"""
        if isinstance(v, list):
            return [str(x) if isinstance(x, uuid.UUID) else x for x in v]
        return list(v) if v else []


class MemoryProposalResponse(BaseModel):
    """记忆提案响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    chapter_id: str | None = None
    chapter_index: int | None = None
    proposal_type: str
    payload: dict[str, Any]
    confidence: float = 0.5
    reason: str | None = None
    source_text_excerpt: str | None = None
    decision: str = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    created_at: datetime | None = None

    @field_validator("id", "novel_id", "chapter_id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class MemoryRecordListResponse(BaseModel):
    """记忆记录列表响应"""

    items: list[MemoryRecordResponse]
    total: int


class MemoryProposalListResponse(BaseModel):
    """记忆提案列表响应"""

    items: list[MemoryProposalResponse]
    total: int


# ============================================================
# Facade 输出 Schema
# ============================================================

class MemoryRecordContext(BaseModel):
    """记忆记录上下文 — 供其他模块读取的简版记忆信息"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_type: str
    chapter_index: int | None = None
    title: str | None = None
    summary: str
    visibility: str = "reader_known"
    known_by_character_ids: list[str] = []
    related_entity_ids: list[str] = []
    related_character_ids: list[str] = []
    related_thread_ids: list[str] = []
    importance: float = 0.5

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)

    @field_validator(
        "known_by_character_ids",
        "related_entity_ids",
        "related_character_ids",
        "related_thread_ids",
        mode="before",
    )
    @classmethod
    def coerce_jsonb_list(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x) if isinstance(x, uuid.UUID) else x for x in v]
        return list(v) if v else []


class MemoryUpdateProposalContext(BaseModel):
    """记忆提案上下文 — 供其他模块读取"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    proposal_type: str
    payload: dict[str, Any]
    confidence: float = 0.5
    reason: str | None = None
    decision: str = "pending"

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        return str(v)
