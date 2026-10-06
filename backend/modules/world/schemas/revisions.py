"""实体修订、合并、融合与回滚 schema。"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

# EntityRevision Schema
# ============================================================


class RevisionListResponse(BaseModel):
    """版本列表响应"""

    items: list[dict[str, Any]]
    total: int


class RollbackRequest(BaseModel):
    """回滚请求"""

    target_revision_id: str = Field(
        ...,
        description="目标版本 ID",
    )


class EntityRollbackRequest(BaseModel):
    """实体按 Scene 索引回滚请求"""

    target_scene_index: int = Field(
        ...,
        ge=0,
        description="目标 Scene 索引",
    )


class EntityMergeRequest(BaseModel):
    """实体合并请求"""

    target_entity_id: str = Field(
        ...,
        description="合并目标实体 ID",
    )


class EntityMergeResponse(BaseModel):
    """实体合并响应"""

    target_entity_id: str
    candidate_entity_id: str | None = None
    affected_ids: list[str] = Field(default_factory=list)
    merged_ids: list[str] = Field(default_factory=list)


class EntityFusionSuggestionRequest(BaseModel):
    """请求生成世界对象 LLM 融合/合并建议。"""

    novel_id: str
    entity_type: str | None = Field(None, max_length=64)
    status: str | None = Field(None, max_length=32)
    limit: int = Field(default=200, ge=2, le=1000)
    max_suggestions: int = Field(default=50, ge=1, le=200)
    operation_id: uuid.UUID | None = None
    context_confirmation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class EntityFusionSuggestionResponse(BaseModel):
    """世界对象融合建议任务响应。"""

    task_id: str
    status: str = "pending"


class EntityFusionApplyItem(BaseModel):
    """一条用户确认要应用的融合建议。"""

    action: str = Field(..., pattern="^(merge|alias_only)$")
    source_entity_id: str
    target_entity_id: str
    alias: str | None = Field(None, max_length=255)
    allow_canonical_merge: bool = False
    allow_canonical_alias: bool = False


class EntityFusionApplyRequest(BaseModel):
    """应用已确认的融合建议。"""

    novel_id: str
    confirmed: bool = False
    suggestions: list[EntityFusionApplyItem] = Field(..., min_length=1)


class EntityFusionApplyResponse(BaseModel):
    """应用融合建议的结果。"""

    applied: int = 0
    skipped: int = 0
    results: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EntityRollbackResponse(BaseModel):
    """实体回滚响应"""

    entity_id: str
    target_scene_index: int | None
    restored_fields: list[str]
    warnings: list[str]


class TextArchiveSeedRequest(BaseModel):
    """E2E 测试专用：写入 TextArchive 归档请求"""

    novel_id: str
    field_name: str = "summary"
    text_content: str
    scene_index: int = 0


class TextArchiveSeedResponse(BaseModel):
    """E2E 测试专用：写入 TextArchive 归档响应"""

    status: str = "ok"
    entity_id: str
    field_name: str
    archive_id: str
