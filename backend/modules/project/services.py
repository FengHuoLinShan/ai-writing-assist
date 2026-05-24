"""
Project 业务逻辑层

调用 repository 完成业务操作。
服务层可包含业务规则，但不直接操作数据库。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    ProjectContext,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class ProjectService:
    """项目业务服务"""

    def __init__(self) -> None:
        self._repo = ProjectRepository()

    async def create_project(
        self,
        db: AsyncSession,
        data: ProjectCreate,
    ) -> ProjectResponse:
        """创建新项目"""
        project = await self._repo.create(db, data)
        return ProjectResponse.model_validate(project)

    async def get_project(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> ProjectResponse:
        """获取项目详情"""
        pid = self._parse_uuid(project_id)
        project = await self._repo.get(db, pid)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return ProjectResponse.model_validate(project)

    async def list_projects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[ProjectResponse], int]:
        """获取项目列表"""
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.get_multi(db, skip=skip, limit=limit)
        return [ProjectResponse.model_validate(p) for p in items], total

    async def update_project(
        self,
        db: AsyncSession,
        project_id: str,
        data: ProjectUpdate,
    ) -> ProjectResponse:
        """更新项目"""
        pid = self._parse_uuid(project_id)
        project = await self._repo.update(db, pid, data)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return ProjectResponse.model_validate(project)

    async def delete_project(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> None:
        """删除项目"""
        pid = self._parse_uuid(project_id)
        deleted = await self._repo.delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )

    async def get_project_context(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> ProjectContext | None:
        """获取项目上下文（供其他模块使用，不存在返回 None）"""
        pid = self._parse_uuid(novel_id)
        project = await self._repo.get(db, pid)
        if project is None:
            return None
        return ProjectContext(
            novel_id=str(project.id),
            title=project.title,
            genre=project.genre,
            tone=project.tone,
            language=project.language,
            target_length=project.target_length,
            current_stage=project.current_stage,
            default_reveal_policy=project.default_reveal_policy,
        )

    # ============================================================
    # 内部工具
    # ============================================================

    @staticmethod
    def _parse_uuid(project_id: str) -> uuid.UUID:
        """将字符串 ID 解析为 UUID，格式错误时抛出 422"""
        try:
            return uuid.UUID(hex=project_id)
        except ValueError:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid project ID: {project_id}",
            )
