"""
Project Pydantic Schemas
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from infrastructure.llm.profiles import sanitize_project_settings


def _sanitize_title(v: str) -> str:
    """去除首尾空白，并拒绝空字节与纯空白"""
    if "\x00" in v:
        raise ValueError("title must not contain null bytes")
    v = v.strip()
    if not v:
        raise ValueError("title must not be empty")
    return v


class ProjectCreate(BaseModel):
    """创建项目请求"""

    title: str = Field(..., min_length=1, max_length=255, description="项目标题")
    genre: str | None = Field(None, max_length=64, description="题材")
    tone: str | None = Field(None, max_length=64, description="风格基调")
    language: str = Field(default="zh", max_length=16, description="创作语言")
    target_length: str | None = Field(None, max_length=32, description="目标规模")
    current_stage: str | None = Field(None, max_length=32, description="创作阶段")
    default_reveal_policy: str = Field(
        default="author_safe", max_length=32, description="默认揭示策略"
    )
    settings: dict = Field(default={}, description="小说配置（JSON）")

    @field_validator("title")
    @classmethod
    def _sanitize_title_field(cls, v: str) -> str:
        return _sanitize_title(v)

    @field_validator("default_reveal_policy")
    @classmethod
    def _check_reveal_policy(cls, v: str) -> str:
        valid = {"author_safe", "author_only", "reader_known", "public"}
        if v not in valid:
            raise ValueError(f"default_reveal_policy must be one of {valid}")
        return v


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

    @field_validator("title")
    @classmethod
    def _sanitize_title_field(cls, v: str | None) -> str | None:
        return _sanitize_title(v) if v else v

    @field_validator("default_reveal_policy")
    @classmethod
    def _check_reveal_policy(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"author_safe", "author_only", "reader_known", "public"}
        if v not in valid:
            raise ValueError(f"default_reveal_policy must be one of {valid}")
        return v


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

    @field_validator("settings", mode="before")
    @classmethod
    def sanitize_settings(cls, v: object) -> dict:
        if isinstance(v, dict):
            return sanitize_project_settings(v)
        return {}


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


class LLMProviderTemplateResponse(BaseModel):
    """User-facing LLM provider preset."""

    id: str
    name: str
    category: str
    base_url: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)
    description: str = ""
    docs_url: str = ""


class LLMProviderTemplateListResponse(BaseModel):
    """LLM provider preset list."""

    items: list[LLMProviderTemplateResponse]


class ProjectLLMSettingsUpdate(BaseModel):
    """Project-level LLM settings update.

    api_key is write-only. Empty api_key preserves an existing key unless
    clear_api_key is true.
    """

    provider_id: str = Field(default="openai-compatible", max_length=64)
    label: str | None = Field(default=None, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=512)
    model: str = Field(..., min_length=1, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False

    @field_validator("provider_id", "label", "base_url", "model", "api_key")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class ProjectLLMSettingsResponse(BaseModel):
    """Project-level LLM settings response without secrets."""

    provider_id: str = "openai-compatible"
    label: str | None = None
    base_url: str = ""
    model: str = ""
    api_key_configured: bool = False
