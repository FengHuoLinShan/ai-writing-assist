"""Public and provider contracts for read-only unified author notices."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NoticeScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: UUID | None = None
    chapter_index: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def has_focus(self):
        if self.scene_id is None and self.chapter_index is None:
            raise ValueError("需要选择场景或章节")
        return self


class NoticeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notice_key: str = Field(min_length=1, max_length=200)
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,80}$")
    category: str = Field(min_length=1, max_length=80)
    severity: Literal["high", "medium", "low", "info"]
    target: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(min_length=1, max_length=4000)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    stale: bool = False
    status: Literal["unread", "read", "snoozed", "ignored"] = "unread"
    wake_at: datetime | None = None
    row_version: int = Field(default=0, ge=0)
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=8)


class NoticeSourceUnavailable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    label: str
    message: str = "暂时无法读取"


class NoticeListResponse(BaseModel):
    novel_id: UUID
    scope: NoticeScope
    items: list[NoticeItem]
    unavailable_sources: list[NoticeSourceUnavailable] = Field(default_factory=list)
    muted_categories: list[dict[str, Any]] = Field(default_factory=list)
    partial: bool = False


class NoticeDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: UUID
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,80}$")
    notice_key: str = Field(min_length=1, max_length=200)
    basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: NoticeScope
    expected_row_version: int = Field(ge=0)
    action: Literal["read", "snooze", "ignore"]
    duration_hours: int | None = Field(default=None, ge=1, le=720)

    @model_validator(mode="after")
    def snooze_has_duration(self):
        if self.action == "snooze" and self.duration_hours is None:
            raise ValueError("稍后提醒需要指定时长")
        if self.action != "snooze" and self.duration_hours is not None:
            raise ValueError("只有稍后提醒可以指定时长")
        return self


class NoticeCategoryMuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: UUID
    expected_row_version: int = Field(ge=0)


class NoticeOperationDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,80}$")
    notice_key: str = Field(min_length=1, max_length=200)
    basis_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: NoticeScope
    expected_row_version: int = Field(ge=0)
    action: Literal["read", "snooze", "ignore"]
    duration_hours: int | None = Field(default=None, ge=1, le=720)

    @model_validator(mode="after")
    def snooze_has_duration(self):
        if self.action == "snooze" and self.duration_hours is None:
            raise ValueError("稍后提醒需要指定时长")
        if self.action != "snooze" and self.duration_hours is not None:
            raise ValueError("只有稍后提醒可以指定时长")
        return self


class NoticeOperationCategoryMute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,80}$")
    category: str = Field(min_length=1, max_length=80)
    expected_row_version: int = Field(ge=0)
