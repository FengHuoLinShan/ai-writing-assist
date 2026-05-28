"""
Project 数据访问层

封装 projects 表的所有数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.project.schemas import ProjectCreate, ProjectUpdate
from shared.constants import DEFAULT_PAGE_SIZE


class ProjectRepository:
    """项目数据访问"""

    async def create(
        self,
        db: AsyncSession,
        data: ProjectCreate,
    ) -> Project:
        """创建新项目"""
        project = Project(
            title=data.title,
            genre=data.genre,
            tone=data.tone,
            language=data.language or "zh",
            target_length=data.target_length,
            current_stage=data.current_stage,
            default_reveal_policy=data.default_reveal_policy or "author_safe",
        )
        db.add(project)
        await db.flush()
        return project

    async def get(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
    ) -> Project | None:
        """根据 ID 获取项目"""
        stmt = select(Project).where(Project.id == project_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Project], int]:
        """获取项目列表（分页），返回 (items, total)"""
        # 获取总数
        count_stmt = select(func.count(Project.id))
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0

        # 获取分页数据
        stmt = (
            select(Project)
            .offset(skip)
            .limit(limit)
            .order_by(Project.created_at.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[Project] = result.scalars().all()
        return list(items), total

    async def update(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
        data: ProjectUpdate,
    ) -> Project | None:
        """更新项目，返回更新后的对象（不存在返回 None）"""
        # 先检查是否存在
        project = await self.get(db, project_id)
        if project is None:
            return None

        # 构建更新字典（只更新非 None 字段）
        update_values: dict[str, object] = {}
        for field in (
            "title",
            "genre",
            "tone",
            "language",
            "target_length",
            "current_stage",
            "default_reveal_policy",
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
            # 重新查询以获取更新后的对象
            project = await self.get(db, project_id)

        return project

    async def delete(
        self,
        db: AsyncSession,
        project_id: uuid.UUID,
    ) -> bool:
        """删除项目，返回是否成功删除"""
        stmt = delete(Project).where(Project.id == project_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0
