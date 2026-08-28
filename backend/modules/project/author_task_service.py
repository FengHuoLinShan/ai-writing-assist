"""Project-owned lightweight author tasks and source resolution."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.project.models import ProjectAuthorTask
from modules.project.schemas import (
    AuthorTaskCountsResponse,
    AuthorTaskCreateRequest,
    AuthorTaskListResponse,
    AuthorTaskPatchRequest,
    AuthorTaskResponse,
    AuthorTaskSourceInput,
    AuthorTaskSourceResponse,
    WorkspaceAuthorTaskPreviewResponse,
    WorkspaceAuthorTasksSummaryResponse,
)
from modules.project.services import ProjectService
from shared.utils import parse_uuid

_SOURCE_LABELS = {
    "world_page": "世界资料已失效",
    "world_entity": "世界对象已失效",
    "writing_chapter": "章节已失效",
    "outline_scene": "Scene 已失效",
}


def _chapter_source_index(value: str) -> int | None:
    """Return one canonical, positive PostgreSQL integer chapter index."""
    if not value.isascii() or not value.isdecimal():
        return None
    index = int(value)
    if index < 1 or index > 2_147_483_647 or str(index) != value:
        return None
    return index


def _is_uuid_source_id(value: str) -> bool:
    try:
        parse_uuid(value, "source_id")
    except ValidationError:
        return False
    return True


def _same_moment(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    if left.tzinfo is None:
        left = left.replace(tzinfo=UTC)
    if right.tzinfo is None:
        right = right.replace(tzinfo=UTC)
    return left.astimezone(UTC) == right.astimezone(UTC)


class AuthorTaskService:
    """Persist author tasks without sharing worker-task or domain-decision state."""

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self._project_service = project_service or ProjectService()

    async def list_tasks(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        scope: str,
        on_date: date,
        skip: int,
        limit: int,
    ) -> AuthorTaskListResponse:
        await self._project_service.require_active_project(db, project_id)
        models, total = await self._list_models(
            db,
            project_id,
            scope=scope,
            on_date=on_date,
            skip=skip,
            limit=limit,
        )
        counts = await self._counts(db, project_id, on_date)
        return AuthorTaskListResponse(
            items=await self._responses(db, project_id, models),
            total=total,
            counts=counts,
        )

    async def create_task(
        self,
        db: AsyncSession,
        project_id: str,
        data: AuthorTaskCreateRequest,
    ) -> AuthorTaskResponse:
        await self._project_service.require_active_project(db, project_id)
        if data.source is not None:
            await self._require_source(db, project_id, data.source)
        task = ProjectAuthorTask(
            novel_id=parse_uuid(project_id, "project_id"),
            title=data.title,
            note=data.note,
            status="open",
            due_date=data.due_date,
            source_kind=data.source.kind if data.source else None,
            source_id=data.source.id if data.source else None,
        )
        db.add(task)
        await db.flush()
        return (await self._responses(db, project_id, [task]))[0]

    async def patch_task(
        self,
        db: AsyncSession,
        project_id: str,
        task_id: str,
        data: AuthorTaskPatchRequest,
    ) -> AuthorTaskResponse:
        await self._project_service.require_active_project(db, project_id)
        task_uuid = parse_uuid(task_id, "task_id")
        task = await db.scalar(
            select(ProjectAuthorTask)
            .where(
                ProjectAuthorTask.id == task_uuid,
                ProjectAuthorTask.novel_id == parse_uuid(project_id, "project_id"),
            )
            .with_for_update()
        )
        if task is None:
            raise NotFoundError("作者任务不存在")
        changed_fields = data.model_fields_set - {"expected_updated_at"}
        if changed_fields == {"status"} and data.status == task.status:
            return (await self._responses(db, project_id, [task]))[0]
        if data.expected_updated_at is None:
            raise ValidationError("更新任务时必须提供当前版本")
        if not _same_moment(data.expected_updated_at, task.updated_at):
            raise ConflictError(
                "任务已在其他位置更新，请刷新后重试",
                code="author_task_changed",
            )

        fields = data.model_fields_set
        changed = False
        if "title" in fields:
            if data.title is None:
                raise ValidationError("任务标题不能为空")
            if task.title != data.title:
                task.title = data.title
                changed = True
        if "note" in fields:
            if task.note != data.note:
                task.note = data.note
                changed = True
        if "due_date" in fields:
            if task.due_date != data.due_date:
                task.due_date = data.due_date
                changed = True
        if "source" in fields:
            if data.source is None:
                if task.source_kind is not None or task.source_id is not None:
                    task.source_kind = None
                    task.source_id = None
                    changed = True
            else:
                await self._require_source(db, project_id, data.source)
                if (
                    task.source_kind != data.source.kind
                    or task.source_id != data.source.id
                ):
                    task.source_kind = data.source.kind
                    task.source_id = data.source.id
                    changed = True
        if "status" in fields:
            if data.status is None:
                raise ValidationError("任务状态不能为空")
            if task.status != data.status:
                task.status = data.status
                task.completed_at = (
                    datetime.now(UTC) if data.status == "completed" else None
                )
                changed = True
        if changed:
            task.updated_at = datetime.now(UTC)
            await db.flush()
        return (await self._responses(db, project_id, [task]))[0]

    async def get_workspace_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        on_date: date,
    ) -> WorkspaceAuthorTasksSummaryResponse:
        counts = await self._counts(db, novel_id, on_date)
        models, _ = await self._list_models(
            db,
            novel_id,
            scope="today",
            on_date=on_date,
            skip=0,
            limit=3,
        )
        items = await self._responses(db, novel_id, models)
        return WorkspaceAuthorTasksSummaryResponse(
            today_count=counts.today,
            inbox_count=counts.inbox,
            later_count=counts.later,
            preview=[
                WorkspaceAuthorTaskPreviewResponse(
                    id=item.id,
                    title=item.title,
                    due_date=item.due_date,
                    source=item.source,
                    updated_at=item.updated_at,
                )
                for item in items
            ],
        )

    async def _list_models(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scope: str,
        on_date: date,
        skip: int,
        limit: int,
    ) -> tuple[list[ProjectAuthorTask], int]:
        nid = parse_uuid(novel_id, "project_id")
        conditions = [ProjectAuthorTask.novel_id == nid]
        if scope == "today":
            conditions.extend(
                [
                    ProjectAuthorTask.status == "open",
                    ProjectAuthorTask.due_date.is_not(None),
                    ProjectAuthorTask.due_date <= on_date,
                ]
            )
        elif scope == "inbox":
            conditions.extend(
                [
                    ProjectAuthorTask.status == "open",
                    ProjectAuthorTask.due_date.is_(None),
                ]
            )
        elif scope == "later":
            conditions.extend(
                [
                    ProjectAuthorTask.status == "open",
                    ProjectAuthorTask.due_date > on_date,
                ]
            )
        elif scope == "completed":
            conditions.append(ProjectAuthorTask.status == "completed")
        elif scope == "archived":
            conditions.append(ProjectAuthorTask.status == "archived")
        else:
            raise ValidationError("未知任务视图")

        total = int(
            await db.scalar(select(func.count(ProjectAuthorTask.id)).where(*conditions))
            or 0
        )
        order = (
            (ProjectAuthorTask.completed_at.desc(), ProjectAuthorTask.updated_at.desc())
            if scope == "completed"
            else (ProjectAuthorTask.due_date.asc(), ProjectAuthorTask.created_at.asc())
        )
        rows = await db.scalars(
            select(ProjectAuthorTask)
            .where(*conditions)
            .order_by(*order, ProjectAuthorTask.id.asc())
            .offset(skip)
            .limit(limit)
        )
        return list(rows.all()), total

    async def _counts(
        self,
        db: AsyncSession,
        novel_id: str,
        on_date: date,
    ) -> AuthorTaskCountsResponse:
        nid = parse_uuid(novel_id, "project_id")
        row = (
            await db.execute(
                select(
                    func.sum(
                        case(
                            (
                                (ProjectAuthorTask.status == "open")
                                & ProjectAuthorTask.due_date.is_not(None)
                                & (ProjectAuthorTask.due_date <= on_date),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                (ProjectAuthorTask.status == "open")
                                & ProjectAuthorTask.due_date.is_(None),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (
                                (ProjectAuthorTask.status == "open")
                                & (ProjectAuthorTask.due_date > on_date),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (ProjectAuthorTask.status == "completed", 1),
                            else_=0,
                        )
                    ),
                ).where(ProjectAuthorTask.novel_id == nid)
            )
        ).one()
        return AuthorTaskCountsResponse(
            today=int(row[0] or 0),
            inbox=int(row[1] or 0),
            later=int(row[2] or 0),
            completed=int(row[3] or 0),
        )

    async def _require_source(
        self,
        db: AsyncSession,
        novel_id: str,
        source: AuthorTaskSourceInput,
    ) -> None:
        resolved = await self._resolve_sources(
            db,
            novel_id,
            {(source.kind, source.id)},
        )
        if not resolved[(source.kind, source.id)].available:
            raise NotFoundError("任务来源不存在")

    async def _responses(
        self,
        db: AsyncSession,
        novel_id: str,
        models: list[ProjectAuthorTask],
    ) -> list[AuthorTaskResponse]:
        keys = {
            (str(item.source_kind), str(item.source_id))
            for item in models
            if item.source_kind and item.source_id
        }
        sources = await self._resolve_sources(db, novel_id, keys)
        return [
            AuthorTaskResponse(
                id=str(item.id),
                title=item.title,
                note=item.note,
                status=item.status,
                due_date=item.due_date,
                source=(
                    sources[(str(item.source_kind), str(item.source_id))]
                    if item.source_kind and item.source_id
                    else None
                ),
                created_at=item.created_at,
                updated_at=item.updated_at,
                completed_at=item.completed_at,
            )
            for item in models
        ]

    async def _resolve_sources(
        self,
        db: AsyncSession,
        novel_id: str,
        keys: set[tuple[str, str]],
    ) -> dict[tuple[str, str], AuthorTaskSourceResponse]:
        resolved = {
            key: AuthorTaskSourceResponse(
                kind=key[0],
                id=key[1],
                label=_SOURCE_LABELS[key[0]],
                available=False,
            )
            for key in keys
        }
        if not keys:
            return resolved

        world_keys = [
            key
            for key in keys
            if key[0].startswith("world_") and _is_uuid_source_id(key[1])
        ]
        if world_keys:
            from modules.world.facade import get_world_bible_projection_candidates

            try:
                world = await get_world_bible_projection_candidates(
                    db,
                    novel_id,
                    [
                        {
                            "target_type": (
                                "world_bible_page"
                                if kind == "world_page"
                                else "core_entity"
                            ),
                            "target_id": source_id,
                        }
                        for kind, source_id in world_keys
                    ],
                    reveal_mode="author_full",
                )
            except (NotFoundError, ValidationError):
                world = None
            for item in world.items if world is not None else ():
                target_type = item.target.get("target_type")
                kind = (
                    "world_page" if target_type == "world_bible_page" else "world_entity"
                )
                key = (kind, item.target.get("target_id", ""))
                if key in resolved:
                    resolved[key] = AuthorTaskSourceResponse(
                        kind=kind,
                        id=key[1],
                        label=item.label,
                        available=True,
                    )

        chapter_keys = [key for key in keys if key[0] == "writing_chapter"]
        if chapter_keys:
            from modules.writing.facade import list_latest_drafts_for_chapters

            chapter_indices = sorted(
                index
                for _, value in chapter_keys
                if (index := _chapter_source_index(value)) is not None
            )
            try:
                drafts = (
                    await list_latest_drafts_for_chapters(
                        db,
                        novel_id,
                        chapter_indices,
                        content_limit=0,
                    )
                    if chapter_indices
                    else []
                )
            except (NotFoundError, ValidationError):
                drafts = []
            for draft in drafts:
                key = ("writing_chapter", str(draft.chapter_index))
                if key in resolved:
                    resolved[key] = AuthorTaskSourceResponse(
                        kind="writing_chapter",
                        id=key[1],
                        label=draft.title or f"第 {draft.chapter_index} 章",
                        available=True,
                    )

        for key in [
            key
            for key in keys
            if key[0] == "outline_scene" and _is_uuid_source_id(key[1])
        ]:
            from modules.story.facade import get_scene_contract

            try:
                scene = await get_scene_contract(db, novel_id, key[1])
            except (NotFoundError, ValidationError):
                scene = None
            if scene is not None:
                resolved[key] = AuthorTaskSourceResponse(
                    kind="outline_scene",
                    id=key[1],
                    label=scene.title or f"Scene {scene.scene_index}",
                    available=True,
                )
        return resolved
