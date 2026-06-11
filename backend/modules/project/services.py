"""
Project Service
"""

from __future__ import annotations

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid


class ProjectService:
    """业务服务层 — project 为根聚合，只做 response 转换与 404 抛错"""

    def __init__(self) -> None:
        self._repo = ProjectRepository()

    async def create_project(
        self, db: AsyncSession, data: ProjectCreate
    ) -> ProjectResponse:
        project = await self._repo.create(db, data)
        return ProjectResponse.model_validate(project)

    async def get_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        pid = parse_uuid(project_id, "project_id")
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
    ) -> ProjectListResponse:
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.list(db, skip=skip, limit=limit)
        return ProjectListResponse(
            items=[ProjectResponse.model_validate(p) for p in items],
            total=total,
        )

    async def update_project(
        self,
        db: AsyncSession,
        project_id: str,
        data: ProjectUpdate,
    ) -> ProjectResponse:
        pid = parse_uuid(project_id, "project_id")
        project = await self._repo.update(db, pid, data)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return ProjectResponse.model_validate(project)

    async def delete_project(self, db: AsyncSession, project_id: str) -> None:
        """软删除：标记项目为已删除（移至回收站）"""
        pid = parse_uuid(project_id, "project_id")
        deleted = await self._repo.soft_delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found or already deleted",
            )

    async def restore_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        """从回收站恢复项目"""
        pid = parse_uuid(project_id, "project_id")
        restored = await self._repo.restore(db, pid)
        if not restored:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found in recycle bin",
            )
        project = await self._repo.get(db, pid)
        return ProjectResponse.model_validate(project)

    async def permanent_delete_project(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> None:
        """永久删除项目（级联删除所有关联数据，不可恢复）"""
        pid = parse_uuid(project_id, "project_id")
        deleted = await self._repo.permanent_delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found in recycle bin",
            )

    async def list_deleted_projects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ProjectListResponse:
        """列出回收站中的项目"""
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.list_deleted(db, skip=skip, limit=limit)
        return ProjectListResponse(
            items=[ProjectResponse.model_validate(p) for p in items],
            total=total,
        )

    async def get_project_context(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> ProjectContext | None:
        pid = parse_uuid(novel_id, "novel_id")
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
            settings=project.settings,
        )
