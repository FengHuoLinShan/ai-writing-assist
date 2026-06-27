"""
Review Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
# ReviewWarning Schema
# ============================================================


class ReviewWarning(BaseModel):
    """复查警告项"""

    type: str = Field(
        ...,
        description="警告类型：schema/entity_reference/early_reveal/"
        "character_knowledge/timeline_conflict/geo_conflict/duplicate",
    )
    message: str = Field(
        ...,
        description="警告描述",
    )
    severity: str = Field(
        default="medium",
        description="严重程度：low/medium/high",
    )
    location: dict[str, Any] = Field(
        default_factory=dict,
        description="问题位置（如字段路径、行号等）",
    )


# ============================================================
# ReviewReport Schema
# ============================================================


class ReviewReportCreate(BaseModel):
    """创建复查报告请求"""

    target_type: str = Field(
        ...,
        max_length=32,
        description="复查目标类型",
    )
    target_id: str | None = Field(
        None,
        description="复查目标 ID（可选）",
    )
    status: str = Field(
        default="canonical",
        max_length=32,
        description="报告状态：draft/canonical/deprecated",
    )
    decision: str = Field(
        ...,
        max_length=32,
        description="复查决策",
    )
    score: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="综合评分",
    )
    problems: list[ReviewWarning] = Field(
        default_factory=list,
        description="问题列表",
    )
    conflict_warnings: list[ReviewWarning] = Field(
        default_factory=list,
        description="冲突警告",
    )
    early_reveal_warnings: list[ReviewWarning] = Field(
        default_factory=list,
        description="提前揭示警告",
    )
    character_knowledge_warnings: list[ReviewWarning] = Field(
        default_factory=list,
        description="人物知识边界警告",
    )
    duplicate_entity_warnings: list[ReviewWarning] = Field(
        default_factory=list,
        description="对象重复警告",
    )
    geo_warnings: list[ReviewWarning] = Field(
        default_factory=list,
        description="地理冲突警告",
    )
    revision_instructions: list[str] = Field(
        default_factory=list,
        description="修改建议列表",
    )


class ReviewRequest(BaseModel):
    """提交复查请求

    传入候选结构 payload 和元信息，由服务层执行所有检查。
    """

    novel_id: str = Field(
        ...,
        description="项目 ID",
    )
    target_type: str = Field(
        ...,
        max_length=32,
        description="复查目标类型：world_structure/plot_structure/"
        "chapter_cards/memory_update/entity_candidates",
    )
    target_id: str | None = Field(
        None,
        description="复查目标 ID（可选）",
    )
    candidate_payload: dict[str, Any] = Field(
        ...,
        description="候选结构数据",
    )


class ReviewListResponse(BaseModel):
    """复查报告列表响应"""

    items: list[ReviewReportResponse] = []
    total: int = 0


class ReviewReportResponse(BaseModel):
    """复查报告响应"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    target_type: str
    target_id: str | None = None
    status: str = "canonical"
    decision: str
    score: float | None = None
    problems: list[dict] = []
    conflict_warnings: list[dict] = []
    early_reveal_warnings: list[dict] = []
    character_knowledge_warnings: list[dict] = []
    duplicate_entity_warnings: list[dict] = []
    geo_warnings: list[dict] = []
    revision_instructions: list[str] = []
    created_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)


# ============================================================
# Facade 输出 Schema
# ============================================================


class ReviewReportContext(BaseModel):
    """复查报告上下文 — 供其他模块读取"""

    model_config = ConfigDict(from_attributes=True)

    report_id: str
    novel_id: str
    target_type: str
    target_id: str | None = None
    status: str = "canonical"
    decision: str
    score: float | None = None
    problems: list[dict] = []
    conflict_warnings: list[dict] = []
    early_reveal_warnings: list[dict] = []
    character_knowledge_warnings: list[dict] = []
    duplicate_entity_warnings: list[dict] = []
    geo_warnings: list[dict] = []
    revision_instructions: list[str] = []

    @field_validator("report_id", "novel_id", mode="before")
    @classmethod
    def coerce_uuid(cls, v: object) -> str:
        return _uuid_validator(v)
