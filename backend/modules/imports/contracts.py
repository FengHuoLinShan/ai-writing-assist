"""Imports 对外契约

定义其他模块可以安全依赖的 Imports 接口和数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_IMPORT_FILE_SIZE = 50 * 1024 * 1024


class TaskNotFoundError(Exception):
    """任务不存在"""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Task not found: {task_id}")


@dataclass(frozen=True)
class SourceUpdateChapterContract:
    chapter_index: int
    title: str
    content_hash: str
    change: str


@dataclass(frozen=True)
class SourceUpdatePreviewContract:
    preview_hash: str
    mode: str
    title: str
    project_id: str | None
    chapter_count: int
    changes: list[SourceUpdateChapterContract] = field(default_factory=list)
    requires_destructive_confirmation: bool = False


@dataclass(frozen=True)
class SourceUpdateApplyContract:
    project_id: str
    import_record_id: str
    chapter_count: int
    first_chapter: int
    last_chapter: int
    changed_chapters: list[int] = field(default_factory=list)


from typing import Annotated  # noqa: E402
from uuid import UUID  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: E402


class ImportConsultScope(BaseModel):
    """Exact author-selected groups; consultation never grants their adoption."""

    model_config = ConfigDict(extra="forbid")
    workflow_id: UUID | None = None
    chapter_from: int = Field(ge=1)
    chapter_to: int = Field(ge=1)
    asset_keys: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=30
    )
    expected_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def exact_range(self):
        if not self.chapter_from <= self.chapter_to < self.chapter_from + 20:
            raise ValueError("会诊范围需要一至二十个连续章节")
        if len(self.asset_keys) != len(set(self.asset_keys)):
            raise ValueError("所选待决组不能重复")
        return self
