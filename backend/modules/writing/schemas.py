"""
Writing Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.types import ChapterIndex


# ============================================================
# 请求 Schema
# ============================================================

class WritingDraftCreate(BaseModel):
    """创建/保存草稿请求

    如果相同 novel_id + chapter_index 已有草稿，应创建新版本。
    """

    novel_id: str = Field(
        ...,
        description="小说项目 ID",
    )
    chapter_index: int = Field(
        ...,
        ge=1,
        description="章节索引（从 1 开始）",
    )
    chapter_card_id: str | None = Field(
        None,
        description="关联的章节卡 ID",
    )
    title: str | None = Field(
        None,
        description="草稿标题",
    )
    content: str | None = Field(
        None,
        description="草稿正文",
    )


class WritingDraftUpdate(BaseModel):
    """更新草稿请求（所有字段可选）"""

    title: str | None = Field(None, description="草稿标题")
    content: str | None = Field(None, description="草稿正文")
    status: str | None = Field(
        None,
        description="状态：draft / candidate / canonical / deprecated",
    )


# ============================================================
# 响应 Schema
# ============================================================

class WritingDraftResponse(BaseModel):
    """草稿响应 — 从 ORM 转换时自动处理 UUID→str"""

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={uuid.UUID: str},
    )

    id: str
    novel_id: str
    chapter_index: int
    chapter_card_id: str | None = None
    title: str | None = None
    content: str | None = None
    version_number: int = 1
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", "chapter_card_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: object) -> str | None:
        """将 UUID 属性的原始值转为字符串"""
        if v is None:
            return None
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class DraftListItem(BaseModel):
    """草稿版本列表项"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    title: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id_to_str(cls, v: object) -> str:
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, str):
            return v
        return str(v)


class VersionHistoryResponse(BaseModel):
    """版本历史响应"""

    novel_id: str
    chapter_index: int
    versions: list[DraftListItem]
    total: int
