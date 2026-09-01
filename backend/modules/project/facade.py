"""
Project Facade — 对外入口

其他模块只能从 facade 或 contracts 导入。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from core.errors import NotFoundError
from core.logging_context import bind_validated_novel_id
from modules.project.contracts import InteractionProjectContract, ProjectSummary
from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.schemas import ProjectContext, ProjectCreate
from modules.project.services import ProjectService
from modules.project.settings_schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    FieldResetResponse,
    ProjectAuthorPrefsResponse,
    ProjectsUsingDefaultsResponse,
)
from modules.project.settings_service import ProjectSettingsService

_service = ProjectService()
_repo = ProjectRepository()
_settings_service = ProjectSettingsService()


# Imported after service/repository setup so callers get one stable project seam
# without exposing llm_runtime implementation details.
from modules.project.image_runtime import (  # noqa: E402,F401
    build_project_image_execution_snapshot,
    open_project_image_client,
    restore_project_image_runtime_profile,
)
from modules.project.llm_runtime import (  # noqa: E402,F401
    build_project_llm_execution_snapshot,
    create_project_snapshot_llm_client,
    open_project_llm_client,
    restore_project_llm_execution_settings,
)


async def get_project_context(
    db: AsyncSession,
    novel_id: str,
) -> ProjectContext | None:
    """Return a secret-free project context for cross-module consumers."""
    context = await _service.get_project_context(db, novel_id)
    if context is None:
        return None
    bind_validated_novel_id(novel_id)
    return context


async def get_any_project_context(
    db: AsyncSession,
    novel_id: str,
) -> ProjectContext | None:
    """Task composition-root lookup for either internal project kind."""
    context = await _service.get_project_context(
        db,
        novel_id,
        project_kind=None,
    )
    if context is not None:
        bind_validated_novel_id(novel_id)
    return context


async def get_effective_llm_settings(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveLLMSettingsResponse:
    await require_active_project(db, str(project_id))
    context = await get_project_context(db, str(project_id))
    if context is None:
        raise NotFoundError(f"Project {project_id} not found")
    owner_id = uuid.UUID(context.owner_id) if context.owner_id else None
    return await _settings_service.get_effective_llm_settings(
        db,
        context.settings,
        owner_id=owner_id,
    )


async def get_effective_author_prefs(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveAuthorPrefsResponse:
    await require_active_project(db, str(project_id))
    context = await get_project_context(db, str(project_id))
    owner_id = uuid.UUID(context.owner_id) if context and context.owner_id else None
    return await _settings_service.get_effective_author_prefs(
        db,
        project_id,
        owner_id=owner_id,
    )


async def resolve_effective_llm_settings_for_project_settings(
    db: AsyncSession,
    project_settings: dict | None,
    owner_id: uuid.UUID | None = None,
) -> EffectiveLLMSettingsResponse:
    return await _settings_service.get_effective_llm_settings(
        db,
        project_settings,
        owner_id=owner_id,
    )


async def get_project_author_preferences(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> ProjectAuthorPrefsResponse:
    await require_active_project(db, str(project_id))
    return await _settings_service.get_project_author_prefs(db, project_id)


async def upsert_project_author_preferences(
    db: AsyncSession,
    project_id: uuid.UUID | str,
    payload: dict,
) -> ProjectAuthorPrefsResponse:
    await require_active_project(db, str(project_id))
    return await _settings_service.upsert_project_author_prefs(
        db,
        project_id,
        payload,
    )


async def reset_project_author_preferences_field(
    db: AsyncSession,
    project_id: uuid.UUID | str,
    field_name: str,
) -> FieldResetResponse:
    await require_active_project(db, str(project_id))
    return await _settings_service.reset_project_author_prefs_field(
        db,
        project_id,
        field_name,
    )


async def list_projects_using_defaults(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> ProjectsUsingDefaultsResponse:
    projects, total = await list_active_project_summaries(
        db,
        limit=limit,
        offset=offset,
        exclude_project_ids=_settings_service.fully_overridden_project_ids_subquery(),
    )
    return _settings_service.build_projects_using_defaults_response(projects, total)


async def require_active_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Require an active project, hiding missing and recycled projects as 404."""
    await _service.require_active_project(db, novel_id)
    bind_validated_novel_id(novel_id)


async def require_interaction_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Require the current owner's active hidden interaction project."""
    await _service.require_active_project(
        db,
        novel_id,
        project_kind="interaction",
    )
    bind_validated_novel_id(novel_id)


async def require_any_active_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Infrastructure-only guard for either project kind."""
    await _service.require_active_project(
        db,
        novel_id,
        project_kind=None,
    )
    bind_validated_novel_id(novel_id)


async def create_interaction_project(
    db: AsyncSession,
    *,
    title: str,
) -> InteractionProjectContract:
    return await _service.create_interaction_project(db, title=title)


async def create_author_project(
    db: AsyncSession,
    *,
    title: str,
) -> ProjectSummary:
    """Create a normal author project for a cross-module user workflow."""
    project = await _service.create_project(db, ProjectCreate(title=title))
    return ProjectSummary(project_id=uuid.UUID(str(project.id)), title=project.title)


async def archive_interaction_project(db: AsyncSession, novel_id: str) -> None:
    await _service.archive_interaction_project(db, novel_id)


async def restore_interaction_project(db: AsyncSession, novel_id: str) -> None:
    await _service.restore_interaction_project(db, novel_id)


async def permanently_delete_interaction_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    await _service.permanently_delete_interaction_project(db, novel_id)


async def require_active_project_exclusive(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Exclusively fence a short DB-only finalizer for one active project.

    Normal business operations must keep using ``require_active_project``.
    This seam must never be held across LLM/provider I/O.
    """
    await _service.require_active_project_exclusive(db, novel_id)
    bind_validated_novel_id(novel_id)


async def list_active_project_summaries(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    exclude_project_ids: Select[tuple[Any, ...]] | None = None,
) -> tuple[list[ProjectSummary], int]:
    """List active project summaries with project-owned filtering and sorting.

    ``exclude_project_ids`` lets caller-owned modules provide a DB-side project-id
    subquery without importing project internals.
    """
    from modules.account.facade import current_owner_id_or_system_none

    conditions = [
        Project.deleted_at.is_(None),
        Project.project_kind == "author",
    ]
    owner_id = current_owner_id_or_system_none()
    if owner_id is not None:
        conditions.append(Project.owner_id == owner_id)
    if exclude_project_ids is not None:
        conditions.append(Project.id.not_in(exclude_project_ids))

    count_stmt = select(func.count(Project.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Project.id, Project.title)
        .where(*conditions)
        .order_by(Project.created_at.desc(), Project.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = [ProjectSummary(project_id=row.id, title=row.title) for row in result.all()]
    return items, total


async def list_project_ids_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Return only project IDs for account lifecycle task fencing."""
    result = await db.execute(select(Project.id).where(Project.owner_id == owner_id))
    return list(result.scalars().all())


async def lock_project_ids_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Serialize account-wide asset quota checks and return every project ID.

    The advisory lock avoids upgrading several project ``FOR SHARE`` locks to
    ``FOR UPDATE`` in opposite orders when one account uploads concurrently to
    different projects.
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(owner_id.bytes[:8], byteorder="big", signed=True)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
    result = await db.execute(
        select(Project.id).where(Project.owner_id == owner_id).order_by(Project.id)
    )
    return list(result.scalars().all())


async def purge_projects_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> int:
    """Permanently remove every owner project after account purge becomes due."""
    from core.container import get
    from infrastructure.tasks.facade import (
        cancel_unfinished_tasks_for_novel,
        delete_tasks_for_novels,
    )

    project_ids = list(
        (
            await db.execute(
                select(Project.id).where(Project.owner_id == owner_id).with_for_update()
            )
        ).scalars()
    )
    if project_ids:
        for project_id in project_ids:
            await cancel_unfinished_tasks_for_novel(
                db,
                novel_id=str(project_id),
                transition_reason="account_permanent_delete",
            )
        await get("world.enqueue_map_atlas_cleanup")(
            db,
            [str(project_id) for project_id in project_ids],
        )
        await delete_tasks_for_novels(
            db,
            novel_ids=[str(project_id) for project_id in project_ids],
        )
    result = await db.execute(delete(Project).where(Project.owner_id == owner_id))
    await db.flush()
    return result.rowcount or 0
