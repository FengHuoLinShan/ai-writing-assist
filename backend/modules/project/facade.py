"""
Project Facade — 对外入口

其他模块只能从 facade 或 contracts 导入。
"""

from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging_context import bind_validated_novel_id
from modules.project.contracts import InteractionProjectContract, ProjectSummary
from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.schemas import ProjectContext
from modules.project.services import ProjectService

_service = ProjectService()
_repo = ProjectRepository()


# Imported after service/repository setup so callers get one stable project seam
# without exposing llm_runtime implementation details.
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
    exclude_project_ids: Collection[uuid.UUID] | None = None,
) -> tuple[list[ProjectSummary], int]:
    """List active project summaries with project-owned filtering and sorting.

    Cross-module callers may pass plain project IDs, but never a caller-owned
    SQLAlchemy expression.
    """
    from modules.account.facade import current_owner_id_or_system_none

    conditions = [
        Project.deleted_at.is_(None),
        Project.project_kind == "author",
    ]
    owner_id = current_owner_id_or_system_none()
    if owner_id is not None:
        conditions.append(Project.owner_id == owner_id)
    excluded_ids = tuple(exclude_project_ids or ())
    if excluded_ids:
        conditions.append(Project.id.not_in(excluded_ids))

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


async def purge_projects_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> int:
    """Permanently remove every owner project after account purge becomes due."""
    from infrastructure.tasks.facade import delete_tasks_for_novels

    project_ids = await list_project_ids_for_owner(db, owner_id)
    if project_ids:
        await delete_tasks_for_novels(
            db,
            novel_ids=[str(project_id) for project_id in project_ids],
        )
    result = await db.execute(delete(Project).where(Project.owner_id == owner_id))
    await db.flush()
    return result.rowcount or 0
