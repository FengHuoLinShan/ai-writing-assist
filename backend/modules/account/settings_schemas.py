"""Settings module Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GlobalLLMDefaultsUpdate(BaseModel):
    """全局 LLM 默认 update（拒绝 api_key）。"""

    model_config = {"extra": "forbid"}
    provider_id: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=256)
    timeout: int | None = Field(default=None, ge=1, le=3600)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    extra: dict[str, Any] | None = None
    creative_mode: str | None = Field(default=None, max_length=32)

    @field_validator("provider_id", "label", "base_url", "model", "creative_mode")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class GlobalLLMDefaultsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    provider_id: str | None = None
    label: str | None = None
    base_url: str | None = None
    model: str | None = None
    timeout: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    extra: dict[str, Any] | None = None
    creative_mode: str | None = None
    deep_import: dict[str, Any] | None = None  # 本期永远 None（D9）


class GlobalAuthorPrefsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: int | None = Field(default=None, ge=0, le=100000)
    editor_font: str | None = Field(default=None, max_length=32)
    default_focus_mode: bool | None = None


class GlobalAuthorPrefsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: int | None = None
    editor_font: str | None = None
    default_focus_mode: bool | None = None


class AccountLLMConnectionUpdate(BaseModel):
    """Write-only account provider connection input."""

    model_config = {"extra": "forbid"}
    api_key: str = Field(min_length=1, max_length=4096)

    @field_validator("api_key")
    @classmethod
    def strip_api_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("API Key 不能为空")
        return stripped


class AccountLLMProviderState(BaseModel):
    model_config = {"extra": "forbid"}
    provider_id: str
    label: str
    model: str
    connected: bool
    active: bool
    verified_at: datetime | None = None


class AccountLLMConnectionsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    active_provider_id: str
    providers: list[AccountLLMProviderState]


class AccountLLMRuntimeProfile(BaseModel):
    """Internal stable shape returned across the settings facade."""

    model_config = {"extra": "forbid"}
    provider_id: str
    label: str
    api_key: str
    base_url: str
    model: str
    timeout: int
    max_tokens: int
    temperature: float | None = None
    top_p: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AccountImageConnectionUpdate(BaseModel):
    """Write-only OpenAI image connection input."""

    model_config = {"extra": "forbid"}
    api_key: str = Field(min_length=1, max_length=4096)

    @field_validator("api_key")
    @classmethod
    def strip_image_api_key(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("API Key 不能为空")
        return stripped


class AccountImageConnectionResponse(BaseModel):
    model_config = {"extra": "forbid"}
    provider_id: str = "openai-image"
    label: str = "OpenAI 图片"
    model: str = "gpt-image-2"
    connected: bool
    verified_at: datetime | None = None
    verification_scope: str = "credential_only"


class AccountImageRuntimeProfile(BaseModel):
    """Internal image connection resolved through the settings facade."""

    model_config = {"extra": "forbid"}
    provider_id: str = "openai-image"
    label: str = "OpenAI 图片"
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-image-2"
    timeout: int = 180


class AccountLLMBalanceItem(BaseModel):
    model_config = {"extra": "forbid"}
    provider_id: str
    status: str
    amount: str | None = None
    currency: str | None = None
    queried_at: datetime


class AccountLLMBalancesResponse(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[AccountLLMBalanceItem]
