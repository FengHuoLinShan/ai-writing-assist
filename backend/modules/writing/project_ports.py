"""Project-facing workspace stats port owned by Writing (AO-4).

project 是 L1 隔离根，不得顶层 import writing 聚合统计；组合根把这里的
adapter 注册为 ``project.workspace.writing_stats``，adapter 经本模块
facade 委托，属 writing 内部合法调用。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.contracts import (
    WorkspaceAttentionItem,
    WorkspaceChapterDraft,
    WorkspaceWritingStats,
)
from modules.writing import facade as writing_facade


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
