"""
Project Pydantic Schemas
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from infrastructure.llm.profiles import sanitize_project_settings
from shared.constants import DEFAULT_LLM_MAX_TOKENS
from shared.deep_import_settings import clean_deep_import_settings


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
    word_count: int | None = None
    total_words: int | None = None
    chapter_count: int | None = None
    total_chapters: int | None = None
    stats: dict[str, int] | None = None
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

    @field_validator("stats", mode="before")
    @classmethod
    def sanitize_stats(cls, v: object) -> dict[str, int] | None:
        return v if isinstance(v, dict) else None


class ProjectListResponse(BaseModel):
    """项目列表响应"""

    items: list[ProjectResponse]
    total: int


class ProjectBulkPermanentDeleteRequest(BaseModel):
    """批量永久删除回收站项目请求。"""

    project_ids: list[str] = Field(..., min_length=1, max_length=100)
    confirmed: bool = Field(
        default=False,
        description="用户已完成不可恢复操作的二次确认",
    )


class ProjectBulkPermanentDeleteResponse(BaseModel):
    """批量永久删除结果。"""

    deleted_ids: list[str]
    deleted_count: int


class ProjectContext(BaseModel):
    """项目上下文 — 供其他模块读取的项目信息"""

    model_config = ConfigDict(from_attributes=True)

    novel_id: str
    owner_id: str | None = None
    project_kind: str = "author"
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
    default_parameters: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    docs_url: str = ""


class LLMProviderTemplateListResponse(BaseModel):
    """LLM provider preset list."""

    items: list[LLMProviderTemplateResponse]


class ProjectLLMSettingsUpdate(BaseModel):
    """Compatibility update for project-owned non-secret LLM/workflow fields.

    Secret fields remain in the wire shape for old clients, but the service rejects
    any attempt to write or clear them. Keys are account-scoped.
    """

    provider_id: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=128)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=256)
    timeout: int | None = Field(default=None, ge=1, le=3600)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    extra: dict[str, Any] = Field(default_factory=dict)
    deep_import: dict[str, Any] = Field(default_factory=dict)
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    clear_all_api_keys: bool = False

    @field_validator("provider_id", "label", "base_url", "model", "api_key")
    @classmethod
    def strip_text(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("deep_import", mode="before")
    @classmethod
    def clean_deep_import(cls, v: object) -> dict[str, Any]:
        # D4/D6: 空 dict 或 None 表示「恢复继承」，保留为空；非空才走 clean 填默认。
        # 旧实现无论输入都返回完整默认，导致 PUT {} 实际写入全默认而非清除 key。
        if not v:
            return {}
        return clean_deep_import_settings(v)


class ProjectLLMSettingsResponse(BaseModel):
    """Project-level LLM settings response without secrets."""

    provider_id: str = "deepseek"
    label: str | None = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout: int | None = 180
    max_tokens: int | None = DEFAULT_LLM_MAX_TOKENS
    temperature: float | None = 0.3
    top_p: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    deep_import: dict[str, Any] = Field(default_factory=dict)
    api_key_configured: bool = False
    api_key_configured_providers: list[str] = Field(default_factory=list)


class SmartDedupScanRequest(BaseModel):
    """Request one project-wide smart dedupe scan."""

    scopes: list[str] | None = Field(
        default=None,
        description="资产范围；为空时扫描世界对象和全部 outline 结构资产",
    )
    limit_per_scope: int = Field(default=1000, ge=2, le=5000)
    max_suggestions: int = Field(default=120, ge=1, le=300)


class SmartDedupScanResponse(BaseModel):
    """Async smart dedupe scan task response."""

    task_id: str
    status: str = "pending"


class SmartDedupApplyItem(BaseModel):
    """One user-confirmed smart dedupe suggestion."""

    asset_type: str = Field(..., max_length=64)
    action: str = Field(..., max_length=64)
    source_asset_id: str
    target_asset_id: str
    alias: str | None = Field(None, max_length=255)
    allow_canonical_merge: bool = False
    allow_canonical_alias: bool = False


class SmartDedupGroupOperation(BaseModel):
    source_asset_id: str
    action: str = Field(
        ...,
        pattern="^(merge|ai_fusion|alias_only|deprecate_duplicate|keep_separate)$",
    )
    alias: str | None = Field(None, max_length=255)
    expected_source_execution_fingerprint: str = Field(..., min_length=64, max_length=64)
    expected_target_execution_fingerprint: str = Field(..., min_length=64, max_length=64)
    allow_canonical_merge: bool = False
    allow_canonical_alias: bool = False
    scene_preview_confirmed: bool = False


class SmartDedupApplyGroup(BaseModel):
    group_id: str = Field(..., min_length=1, max_length=128)
    asset_type: str = Field(..., max_length=64)
    primary_asset_id: str
    operations: list[SmartDedupGroupOperation] = Field(..., min_length=1)


class SmartDedupApplyRequest(BaseModel):
    """Apply selected smart dedupe suggestions after user confirmation."""

    confirmed: bool = False
    scan_task_id: str | None = None
    suggestions: list[SmartDedupApplyItem] | None = None
    groups: list[SmartDedupApplyGroup] | None = None

    @model_validator(mode="after")
    def validate_apply_mode(self) -> SmartDedupApplyRequest:
        has_legacy = bool(self.suggestions)
        has_groups = bool(self.groups)
        if has_legacy == has_groups:
            raise ValueError("exactly one of suggestions or groups is required")
        if has_groups and not self.scan_task_id:
            raise ValueError("scan_task_id is required for group apply")
        return self


class SmartDedupApplyResponse(BaseModel):
    """Smart dedupe apply result."""

    applied: int = 0
    skipped: int = 0
    results: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    group_results: list[dict[str, Any]] = Field(default_factory=list)


class LLMFieldResetResponse(BaseModel):
    """Project LLM field-level reset response."""

    field: str
    reset: bool = True
