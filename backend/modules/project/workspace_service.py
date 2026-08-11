"""Task-oriented author workspace summary owned by the Project module."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.facade import count_scenes_by_novel
from modules.project.schemas import (
    ProjectResponse,
    ProjectWorkspaceSummaryResponse,
    WorkspaceAttentionSummaryResponse,
    WorkspaceContinuationResponse,
    WorkspaceWritingSummaryResponse,
)
from modules.world.contracts import WorldAttentionSummaryContract
from modules.world.facade import get_author_attention_summary
from modules.writing.contracts import (
    WritingDraftContract,
    WritingProjectStatsContract,
)
from modules.writing.facade import (
    get_project_writing_stats,
    list_chapter_indices,
    list_latest_drafts_for_chapters,
)

ProjectReader = Callable[[AsyncSession, str], Awaitable[ProjectResponse]]
WritingStatsReader = Callable[[AsyncSession, str], Awaitable[WritingProjectStatsContract]]
ChapterIndexReader = Callable[[AsyncSession, str], Awaitable[list[int]]]
LatestDraftsReader = Callable[..., Awaitable[list[WritingDraftContract]]]
WorldAttentionReader = Callable[
    [AsyncSession, str], Awaitable[WorldAttentionSummaryContract]
]
OutlineAttentionReader = Callable[..., Awaitable[int]]


def _draft_sort_key(draft: WritingDraftContract) -> tuple[datetime, int]:
    timestamp = draft.updated_at or draft.created_at or datetime.min.replace(tzinfo=UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp, int(draft.chapter_index)


class ProjectWorkspaceSummaryService:
    """Compose stable module projections after the Project owner gate succeeds."""

    def __init__(
        self,
        *,
        project_reader: ProjectReader,
        writing_stats_reader: WritingStatsReader = get_project_writing_stats,
        chapter_index_reader: ChapterIndexReader = list_chapter_indices,
        latest_drafts_reader: LatestDraftsReader = list_latest_drafts_for_chapters,
        world_attention_reader: WorldAttentionReader = get_author_attention_summary,
        outline_attention_reader: OutlineAttentionReader = count_scenes_by_novel,
    ) -> None:
        self._project_reader = project_reader
        self._writing_stats_reader = writing_stats_reader
        self._chapter_index_reader = chapter_index_reader
        self._latest_drafts_reader = latest_drafts_reader
        self._world_attention_reader = world_attention_reader
        self._outline_attention_reader = outline_attention_reader

    async def get_summary(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> ProjectWorkspaceSummaryResponse:
        project = await self._project_reader(db, project_id)
        novel_id = project.id

        writing = await self._writing_stats_reader(db, novel_id)
        chapter_indices = await self._chapter_index_reader(db, novel_id)
        drafts = (
            await self._latest_drafts_reader(
                db,
                novel_id,
                chapter_indices,
                content_limit=1,
            )
            if chapter_indices
            else []
        )
        latest = max(drafts, key=_draft_sort_key) if drafts else None
        world_attention = await self._world_attention_reader(db, novel_id)
        outline_scenes = await self._outline_attention_reader(
            db,
            novel_id,
            status_filter=["candidate", "proposal"],
        )

        continuation = None
        if latest is not None:
            continuation = WorkspaceContinuationResponse(
                chapter_index=latest.chapter_index,
                title=latest.title or f"第 {latest.chapter_index} 章",
                updated_at=latest.updated_at or latest.created_at,
                has_unpublished_changes=latest.status == "draft",
            )

        attention_total = world_attention.total + int(outline_scenes or 0)
        return ProjectWorkspaceSummaryResponse(
            project_id=novel_id,
            continuation=continuation,
            writing=WorkspaceWritingSummaryResponse(
                chapter_count=writing.chapter_count,
                word_count=writing.word_count,
            ),
            attention=WorkspaceAttentionSummaryResponse(
                world_objects=world_attention.world_objects,
                world_aliases=world_attention.world_aliases,
                world_relations=world_attention.world_relations,
                outline_scenes=int(outline_scenes or 0),
                map_items=world_attention.map_items,
                total=attention_total,
            ),
        )
