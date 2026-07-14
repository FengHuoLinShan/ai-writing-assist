"""
Project Facade — 对外入口

其他模块只能从 facade 或 contracts 导入。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from core.logging_context import bind_validated_novel_id
from modules.project.contracts import ProjectSummary
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
    """获取项目上下文（供其他模块使用）"""
    context = await _service.get_project_context(db, novel_id)
    if context is None:
        return None
    bind_validated_novel_id(novel_id)

    from modules.settings.facade import materialize_effective_project_settings

    settings = await materialize_effective_project_settings(db, context.settings)
    return context.model_copy(update={"settings": settings})


async def require_active_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Require an active project, hiding missing and recycled projects as 404."""
    await _service.require_active_project(db, novel_id)
    bind_validated_novel_id(novel_id)


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


async def get_project_by_id(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> Project | None:
    """根据 ID 获取未删除项目（供其他模块读取项目 settings 等）。"""
    pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
    return await _repo.get(db, pid)


async def list_active_projects(db: AsyncSession) -> list[Project]:
    """列出所有未软删项目，按 created_at desc / id desc 排序。

    仅供跨模块聚合（如 settings 默认继承统计）。返回 ORM 对象，调用方
    只应读取属性，不应在本模块之外修改。
    """
    items, _ = await _repo.list(db, skip=0, limit=100000)
    return items


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
    conditions = [Project.deleted_at.is_(None)]
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
