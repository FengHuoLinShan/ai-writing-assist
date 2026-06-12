"""
Writing Pydantic Schema 定义

用于 API 请求/响应校验和 Facade 输出。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================
# 请求 Schema
# ============================================================


class WritingDraftCreate(BaseModel):
    """创建/发布草稿请求

    每次调用自动递增版本号。
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
    title: str | None = Field(
        None,
        max_length=500,
        description="草稿标题",
    )
    content: str | None = Field(
        None,
        max_length=100000,
        description="草稿正文",
    )


class WritingDraftUpdate(BaseModel):
    """暂存草稿请求（原地更新最新版本，不递增版本号）"""

    title: str | None = Field(None, description="草稿标题")
    content: str | None = Field(None, description="草稿正文")
    expected_version: int | None = Field(
        None,
        ge=1,
        description="期望的版本号，用于多 Tab 冲突检测",
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
    title: str | None = None
    content: str | None = None
    version_number: int = 1
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("id", "novel_id", mode="before")
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
    word_count: int = 0
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


class ChapterSplitRequest(BaseModel):
    split_pos: int = Field(..., ge=1, description="编辑器 offset，必须位于正文中间")
    source_scene_id: str | None = Field(
        None, description="当前 Scene ID，用于同步 scene_chunks"
    )


class SceneSplitItem(BaseModel):
    """章节切分后同步更新的 Scene 项"""

    id: str
    novel_id: str
    scene_index: int
    title: str | None = None
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str | None = None
    source: str | None = None
    scene_chunks: list[dict] = []
    chapter_ids: list[str] = []
    pov_character_id: str | None = None
    status: str | None = None


class ChapterSplitResponse(BaseModel):
    source_chapter_index: int
    new_chapter_index: int
    source_draft: WritingDraftResponse
    new_draft: WritingDraftResponse
    scenes: list[SceneSplitItem] = Field(default_factory=list)
