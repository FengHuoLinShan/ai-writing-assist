"""Project preference and effective-settings wire schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FieldValueSource(BaseModel):
    model_config = {"extra": "forbid"}
    value: Any = None
    source: str = Field(description="project | global | system | unset")


class EffectiveLLMSettingsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    provider_id: FieldValueSource
    label: FieldValueSource
    base_url: FieldValueSource
    model: FieldValueSource
    timeout: FieldValueSource
    max_tokens: FieldValueSource
    temperature: FieldValueSource
    top_p: FieldValueSource
    extra: FieldValueSource
    creative_mode: FieldValueSource
    api_key_configured: FieldValueSource
    api_key_configured_providers: FieldValueSource
    deep_import: FieldValueSource


class EffectiveAuthorPrefsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: FieldValueSource
    editor_font: FieldValueSource
    default_focus_mode: FieldValueSource


class ProjectAuthorPrefsUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: int | None = Field(default=None, ge=0, le=100000)
    editor_font: str | None = Field(default=None, max_length=32)
    default_focus_mode: bool | None = None


class ProjectAuthorPrefsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    daily_goal: int | None = None
    editor_font: str | None = None
    default_focus_mode: bool | None = None


class FieldResetResponse(BaseModel):
    model_config = {"extra": "forbid"}
    field: str
    reset: bool = True


class ProjectsUsingDefaultsItem(BaseModel):
    model_config = {"extra": "forbid"}
    project_id: str
    title: str
    inherited_fields: list[str]


class ProjectsUsingDefaultsResponse(BaseModel):
    model_config = {"extra": "forbid"}
    items: list[ProjectsUsingDefaultsItem]
    total: int
    truncated: bool = False
