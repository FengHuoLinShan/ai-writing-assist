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
