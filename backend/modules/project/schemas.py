"""
Project Pydantic Schemas
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    """创建项目请求"""

    title: str = Field(..., min_length=1, max_length=255, description="项目标题")
    genre: str | None = Field(None, max_length=64, description="题材")
    tone: str | None = Field(None, max_length=64, description="风格基调")
    language: str = Field(default="zh", max_length=16, description="创作语言")
    target_length: str | None = Field(None, max_length=32, description="目标规模")
    current_stage: str | None = Field(None, max_length=32, description="创作阶段")
    default_reveal_policy: str = Field(default="author_safe", max_length=32, description="默认揭示策略")
    settings: dict = Field(default={}, description="小说配置（JSON）")


class ProjectUpdate(BaseModel):
    """更新项目请求（所有字段可选）"""

    title: Annotated[str | None, Field(None, min_length=1, max_length=255)]
    genre: Annotated[str | None, Field(None, max_length=64)]
    tone: Annotated[str | None, Field(None, max_length=64)]
    language: Annotated[str | None, Field(None, max_length=16)]
    target_length: Annotated[str | None, Field(None, max_length=32)]
    current_stage: Annotated[str | None, Field(None, max_length=32)]
    default_reveal_policy: Annotated[str | None, Field(None, max_length=32)]
    settings: Annotated[dict | None, Field(None, description="小说配置（JSON）")]


class ProjectResponse(BaseModel):
    """项目响应"""

    model_config = ConfigDict(from_attributes=True, json_encoders={uuid.UUID: str})

    id: str
    title: str
    genre: str | None = None
    tone: str | None = None
    language: str = "zh"
    target_length: str | None = None
    current_stage: str | None = None
    default_reveal_policy: str = "author_safe"
    settings: dict = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class ProjectListResponse(BaseModel):
    """项目列表响应"""

    items: list[ProjectResponse]
    total: int


class ProjectContext(BaseModel):
    """项目上下文 — 供其他模块读取的项目信息"""

    model_config = ConfigDict(from_attributes=True)

    novel_id: str
    title: str
    genre: str | None = None
    tone: str | None = None
    language: str = "zh"
    target_length: str | None = None
    current_stage: str | None = None
    default_reveal_policy: str = "author_safe"
    settings: dict = {}
