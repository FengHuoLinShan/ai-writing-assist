"""
Project API Router
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.project.schemas import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from modules.project.services import ProjectService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/projects", tags=["projects"])
_service = ProjectService()


@router.post("", response_model=ProjectResponse, status_code=201)
async def api_create_project(
    db: DbSession,
    data: ProjectCreate,
) -> ProjectResponse:
    """创建新小说项目"""
    return await _service.create_project(db, data)


@router.get("", response_model=ProjectListResponse)
async def api_list_projects(
    db: DbSession,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> ProjectListResponse:
    """获取项目列表"""
    return await _service.list_projects(db, skip=skip, limit=limit)


@router.get("/recycle-bin", response_model=ProjectListResponse)
async def api_list_deleted_projects(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> ProjectListResponse:
    """获取回收站中的项目列表"""
    return await _service.list_deleted_projects(db, skip=skip, limit=limit)


@router.get("/{project_id}", response_model=ProjectResponse)
async def api_get_project(
    db: DbSession,
    project_id: str,
) -> ProjectResponse:
    """获取项目详情"""
    return await _service.get_project(db, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def api_update_project(
    db: DbSession,
    project_id: str,
    data: ProjectUpdate,
) -> ProjectResponse:
    """更新项目信息"""
    return await _service.update_project(db, project_id, data)


@router.delete("/{project_id}", status_code=204)
async def api_delete_project(
    db: DbSession,
    project_id: str,
) -> None:
    """软删除项目（移至回收站）"""
    await _service.delete_project(db, project_id)


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def api_restore_project(
    db: DbSession,
    project_id: str,
) -> ProjectResponse:
    """从回收站恢复项目"""
    return await _service.restore_project(db, project_id)


@router.delete("/{project_id}/permanent", status_code=204)
async def api_permanent_delete_project(
    db: DbSession,
    project_id: str,
) -> None:
    """永久删除项目（级联删除所有关联数据，不可恢复）"""
    await _service.permanent_delete_project(db, project_id)
