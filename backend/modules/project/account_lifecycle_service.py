"""Owner-scoped project SQL for account lifecycle and cross-module listings.

AO-4/AO-8: this orchestration used to live in ``project/facade.py``; the
facade now only adapts arguments and delegates here. SQL semantics, lock
ordering, transaction boundaries and owner filters are moved unchanged.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from infrastructure.tasks.facade import (
    cancel_unfinished_tasks_for_novel,
    delete_tasks_for_novels,
)
from modules.account.facade import current_owner_id_or_system_none
from modules.project.contracts import ProjectSummary
from modules.project.models import Project


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
