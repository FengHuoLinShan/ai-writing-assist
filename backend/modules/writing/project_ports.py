"""Project-facing workspace stats port owned by Writing (AO-4).

project 是 L1 隔离根，不得顶层 import writing 聚合统计；组合根把这里的
adapter 注册为 ``project.workspace.writing_stats``，adapter 经本模块
facade 委托，属 writing 内部合法调用。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.contracts import (
    WorkspaceAttentionItem,
    WorkspaceChapterDraft,
    WorkspaceCreationProgressItem,
    WorkspaceWritingStats,
)
from modules.writing import facade as writing_facade

# 进度投影纳入的 writing 类任务；done 的任务由其候选/已采用条目呈现，
# 不重复出一条"任务成功"。
_WRITING_PROGRESS_TASK_TYPES = frozenset(
    {
        "writing_generate",
        "writing_semantic_review",
        "writing_targeted_revision",
    }
)
_WRITING_TASK_LABELS = {
    "writing_generate": "生成正文",
    "writing_semantic_review": "独立语义审查",
    "writing_targeted_revision": "定向返修",
}
_PROGRESS_RANK = {
    "task_running": 0,
    "candidate": 1,
    "adopted": 2,
    "task_closed": 3,
}


class WritingWorkspaceStatsAdapter:
    """Adapt manuscript statistics and conflict checks to the project provider."""

    async def get_project_stats(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> WorkspaceWritingStats:
        stats = await writing_facade.get_project_writing_stats(db, novel_id)
        return WorkspaceWritingStats(
            novel_id=stats.novel_id,
            chapter_count=stats.chapter_count,
            word_count=stats.word_count,
        )

    async def list_project_stats(
        self,
        db: AsyncSession,
        novel_ids: list[str],
    ) -> dict[str, WorkspaceWritingStats]:
        stats = await writing_facade.list_project_writing_stats(db, novel_ids)
        return {
            novel_id: WorkspaceWritingStats(
                novel_id=contract.novel_id,
                chapter_count=contract.chapter_count,
                word_count=contract.word_count,
            )
            for novel_id, contract in stats.items()
        }

    async def list_chapter_indices(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> list[int]:
        return await writing_facade.list_chapter_indices(db, novel_id)

    async def list_latest_drafts(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
        *,
        content_limit: int | None = None,
    ) -> list[WorkspaceChapterDraft]:
        drafts = await writing_facade.list_latest_drafts_for_chapters(
            db,
            novel_id,
            chapter_indices,
            content_limit=content_limit,
        )
        return [
            WorkspaceChapterDraft(
                chapter_index=draft.chapter_index,
                title=draft.title,
                status=draft.status,
                created_at=draft.created_at,
                updated_at=draft.updated_at,
            )
            for draft in drafts
        ]

    async def get_attention_items(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> Sequence[WorkspaceAttentionItem]:
        items = await writing_facade.get_author_attention_items(db, novel_id)
        return tuple(
            WorkspaceAttentionItem(
                key=item.key,
                title=item.title,
                summary=item.summary,
                author_action=item.author_action,
                severity=item.severity,
                item_id=item.item_id,
                chapter_index=item.chapter_index,
                scene_id=item.scene_id,
                updated_at=item.updated_at,
            )
            for item in items
        )

    async def get_creation_progress(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 6,
    ) -> Sequence[WorkspaceCreationProgressItem]:
        """作品进度投影（BR-1b）：在途/失败任务 + 候选与已采用成果。

        任务概要经 BR-1a 的 tasks 只读缝取回，仅保留 writing 类型且不带
        raw meta；done 的任务由其候选/已采用条目呈现，不重复出一条。
        """
        from infrastructure.tasks.facade import list_novel_task_overview

        items: list[WorkspaceCreationProgressItem] = []
        overview = []
        for task_type in sorted(_WRITING_PROGRESS_TASK_TYPES):
            overview.extend(
                await list_novel_task_overview(
                    db,
                    novel_id=novel_id,
                    task_type=task_type,
                    active_limit=limit,
                    terminal_limit=limit,
                )
            )
        for row in overview:
            if row.task_type not in _WRITING_PROGRESS_TASK_TYPES:
                continue
            item = _task_progress_item(row)
            if item is not None:
                items.append(item)
        items.extend(
            await writing_facade.list_creation_progress(db, novel_id, limit=limit)
        )
        return sorted(items, key=_progress_sort_key)


def _task_progress_item(row: object) -> WorkspaceCreationProgressItem | None:
    status = str(getattr(row, "status", "") or "")
    if status == "done":
        return None
    meta = getattr(row, "meta", None)
    meta = meta if isinstance(meta, dict) else {}
    chapter = meta.get("chapter_index")
    label = _WRITING_TASK_LABELS.get(str(row.task_type), "后台任务")
    title = f"第 {chapter} 章 · {label}" if chapter else label
    stop_reason = {
        "pending": "等待执行",
        "running": "正在处理",
        "failed": "任务失败，可回写作页重试",
        "cancelled": "已取消；已保存的阶段结果仍保留",
    }.get(status, status)
    actions = ["view_task"]
    if bool(getattr(row, "recovery_required", False)):
        actions.insert(0, "resume")
    return WorkspaceCreationProgressItem(
        key=f"task:{row.task_id}",
        kind="task",
        title=title,
        execution_status=status,
        coverage=f"第 {chapter} 章" if chapter else None,
        source_freshness="unknown",
        applicability="stale" if bool(getattr(row, "stale", False)) else "applicable",
        adoption_status=None,
        stop_reason=stop_reason,
        actions=tuple(actions),
        task_id=str(row.task_id),
        task_type=str(row.task_type),
        updated_at=_parse_progress_time(
            getattr(row, "heartbeat_at", None)
            or getattr(row, "finished_at", None)
            or getattr(row, "created_at", None)
        ),
    )


def _parse_progress_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _progress_rank(item: WorkspaceCreationProgressItem) -> int:
    if item.kind == "task":
        return (
            _PROGRESS_RANK["task_running"]
            if item.execution_status in {"pending", "running"}
            else _PROGRESS_RANK["task_closed"]
        )
    return _PROGRESS_RANK.get(item.kind, _PROGRESS_RANK["adopted"])


def _progress_sort_key(item: WorkspaceCreationProgressItem) -> tuple[int, float]:
    moment = item.updated_at
    if moment is None:
        return _progress_rank(item), 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return _progress_rank(item), -moment.timestamp()
