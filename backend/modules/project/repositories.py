"""
Project Repository
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.project.schemas import ProjectCreate, ProjectUpdate


class ProjectRepository:
    """项目数据访问层"""

    async def get(self, db: AsyncSession, project_id: uuid.UUID) -> Project | None:
        stmt = select(Project).where(Project.id == project_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Project], int]:
        count_stmt = select(func.count(Project.id))
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        stmt = (
            select(Project)
            .offset(skip)
            .limit(limit)
            .order_by(Project.created_at.desc())
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def create(self, db: AsyncSession, data: ProjectCreate) -> Project:
        project = Project(
            title=data.title,
            genre=data.genre,
            tone=data.tone,
            language=data.language or "zh",
            target_length=data.target_length,
            current_stage=data.current_stage,
            default_reveal_policy=data.default_reveal_policy or "author_safe",
            settings=data.settings or {},
        )
        db.add(project)
        await db.flush()
        return project

    async def update(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        data: ProjectUpdate,
    ) -> Project | None:
        project = await self.get(db, project_id)
        if project is None:
            return None
        update_values: dict[str, object] = {}
        for field in (
            "title", "genre", "tone", "language",
            "target_length", "current_stage", "default_reveal_policy", "settings",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value
        if update_values:
            stmt = (
                update(Project)
                .where(Project.id == project_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            project = await self.get(db, project_id)
        return project

    async def delete(self, db: AsyncSession, project_id: uuid.UUID) -> bool:
        stmt = delete(Project).where(Project.id == project_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
