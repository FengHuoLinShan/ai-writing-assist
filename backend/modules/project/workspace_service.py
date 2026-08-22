"""Task-oriented author workspace summary owned by the Project module."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.project.schemas import (
    ProjectResponse,
    ProjectWorkspaceSummaryResponse,
    WorkspaceAttentionItemResponse,
    WorkspaceAttentionMoreTargetResponse,
    WorkspaceAttentionSummaryResponse,
    WorkspaceAttentionTargetResponse,
    WorkspaceContinuationResponse,
    WorkspaceWritingSummaryResponse,
)
from modules.story.facade import (
    count_scenes_by_novel,
    get_scene_contract,
)
from modules.story.facade import (
    get_author_attention_items as get_outline_author_attention_items,
)
from modules.world.contracts import WorldAttentionSummaryContract
from modules.world.facade import get_author_attention_summary
from modules.writing.contracts import (
    WritingDraftContract,
    WritingProjectStatsContract,
)
from modules.writing.facade import (
    get_author_attention_items as get_writing_author_attention_items,
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
AuthorAttentionReader = Callable[
    [AsyncSession, str], Awaitable[Sequence[object]]
]
SceneReader = Callable[..., Awaitable[object | None]]

_ATTENTION_LIMIT = 6
_RELEVANCE_RANK = {
    "exact_scene": 0,
    "current_chapter": 1,
    "project_general": 2,
}
_ACTION_RANK = {"needs_decision": 0, "can_improve": 1}
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _draft_sort_key(draft: WritingDraftContract) -> tuple[datetime, int]:
    timestamp = draft.updated_at or draft.created_at or datetime.min.replace(tzinfo=UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp, int(draft.chapter_index)


def _contract_value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _sortable_timestamp(value: object) -> float:
    if not isinstance(value, datetime):
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _project_attention_item(
    item: object,
    *,
    focus_chapter_index: int | None,
    focus_scene_id: str | None,
    source_kind: str | None = None,
    target_kind: str | None = None,
) -> WorkspaceAttentionItemResponse:
    scene_id = _contract_value(item, "scene_id")
    scene_ids = {
        str(value) for value in (_contract_value(item, "scene_ids", ()) or ()) if value
    }
    if scene_id:
        scene_ids.add(str(scene_id))
    chapter_index = _contract_value(item, "chapter_index")
    exact_scene = bool(focus_scene_id and focus_scene_id in scene_ids)
    if exact_scene:
        relevance = "exact_scene"
    elif focus_chapter_index is not None and chapter_index == focus_chapter_index:
        relevance = "current_chapter"
    else:
        relevance = "project_general"

    return WorkspaceAttentionItemResponse(
        key=str(_contract_value(item, "key")),
        source_kind=source_kind or _contract_value(item, "source_kind"),
        title=str(_contract_value(item, "title")),
        summary=str(_contract_value(item, "summary")),
        author_action=_contract_value(item, "author_action"),
        relevance=relevance,
        severity=_contract_value(item, "severity"),
        target=WorkspaceAttentionTargetResponse(
            kind=target_kind or _contract_value(item, "target_kind"),
            item_id=_contract_value(item, "item_id"),
            chapter_index=(
                focus_chapter_index
                if exact_scene and focus_chapter_index is not None
                else chapter_index
            ),
            scene_id=focus_scene_id if exact_scene else scene_id,
            page_id=_contract_value(item, "page_id"),
            suggestion_id=_contract_value(item, "suggestion_id"),
        ),
        updated_at=_contract_value(item, "updated_at"),
    )


def _attention_sort_key(item: WorkspaceAttentionItemResponse) -> tuple:
    return (
        _RELEVANCE_RANK[item.relevance],
        _ACTION_RANK[item.author_action],
        _SEVERITY_RANK[item.severity],
        -_sortable_timestamp(item.updated_at),
        item.key,
    )


def _scene_chapter_indices(scene: object) -> set[int]:
    values = list(_contract_value(scene, "chapter_ids", []) or [])
    values.extend(
        _contract_value(chunk, "chapter_index", _contract_value(chunk, "chapter_id"))
        for chunk in (_contract_value(scene, "scene_chunks", []) or [])
        if isinstance(chunk, dict)
    )
    return {int(value) for value in values if str(value).isdigit()}


def _more_target(
    item: WorkspaceAttentionItemResponse,
) -> WorkspaceAttentionTargetResponse:
    target = item.target
    if target.kind == "world_adoption":
        return target
    return target.model_copy(
        update={
            "item_id": None,
            "chapter_index": None,
            "scene_id": None,
            "page_id": None,
            "suggestion_id": None,
        }
    )


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
        outline_item_reader: AuthorAttentionReader = get_outline_author_attention_items,
        writing_attention_reader: AuthorAttentionReader = (
            get_writing_author_attention_items
        ),
        scene_reader: SceneReader = get_scene_contract,
    ) -> None:
        self._project_reader = project_reader
        self._writing_stats_reader = writing_stats_reader
        self._chapter_index_reader = chapter_index_reader
        self._latest_drafts_reader = latest_drafts_reader
        self._world_attention_reader = world_attention_reader
        self._outline_attention_reader = outline_attention_reader
        self._outline_item_reader = outline_item_reader
        self._writing_attention_reader = writing_attention_reader
        self._scene_reader = scene_reader

    async def get_summary(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        focus_chapter_index: int | None = None,
        focus_scene_id: str | None = None,
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
        outline_items = await self._outline_item_reader(db, novel_id)
        writing_items = await self._writing_attention_reader(db, novel_id)

        continuation = None
        if latest is not None:
            continuation = WorkspaceContinuationResponse(
                chapter_index=latest.chapter_index,
                title=latest.title or f"第 {latest.chapter_index} 章",
                updated_at=latest.updated_at or latest.created_at,
                has_unpublished_changes=latest.status == "draft",
            )

        effective_chapter = (
            focus_chapter_index
            if focus_chapter_index is not None
            else continuation.chapter_index
            if continuation is not None
            else None
        )
        validated_scene_id = None
        if focus_scene_id:
            try:
                scene = await self._scene_reader(db, novel_id, focus_scene_id)
            except ValidationError:
                scene = None
            scene_chapters = _scene_chapter_indices(scene)
            if scene is not None and (
                effective_chapter is None or effective_chapter in scene_chapters
            ):
                validated_scene_id = str(_contract_value(scene, "id"))
                if effective_chapter is None and scene_chapters:
                    effective_chapter = min(scene_chapters)

        projected_by_key: dict[str, WorkspaceAttentionItemResponse] = {}
        for item in writing_items:
            projected = _project_attention_item(
                item,
                focus_chapter_index=effective_chapter,
                focus_scene_id=validated_scene_id,
                source_kind="writing_conflict",
                target_kind="writing_conflict",
            )
            projected_by_key.setdefault(projected.key, projected)
        for item in [*world_attention.items, *outline_items]:
            projected = _project_attention_item(
                item,
                focus_chapter_index=effective_chapter,
                focus_scene_id=validated_scene_id,
            )
            projected_by_key.setdefault(projected.key, projected)
        attention_items = sorted(projected_by_key.values(), key=_attention_sort_key)
        actionable_total = len(attention_items)
        more_targets: list[WorkspaceAttentionMoreTargetResponse] = []
        seen_more_targets: set[tuple[str, str]] = set()
        for item in attention_items[_ATTENTION_LIMIT:]:
            target = _more_target(item)
            group = (item.source_kind, target.model_dump_json(exclude_none=True))
            if group in seen_more_targets:
                continue
            seen_more_targets.add(group)
            more_targets.append(
                WorkspaceAttentionMoreTargetResponse(
                    source_kind=item.source_kind,
                    target=target,
                )
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
                total=attention_total,
                items=attention_items[:_ATTENTION_LIMIT],
                actionable_total=actionable_total,
                has_more=actionable_total > _ATTENTION_LIMIT,
                more_targets=more_targets,
            ),
        )
