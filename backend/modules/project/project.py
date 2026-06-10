"""
Project 模块 — 向后兼容重导出

项目已拆分为标准 6 层结构：
  models.py → schemas.py → repositories.py → services.py → facade.py → api.py

本文件保留重导出，避免破坏现有导入站点。
新代码请直接从子模块导入。
"""

from __future__ import annotations

# Model & Schemas
from modules.project.models import Project  # noqa: F401
from modules.project.schemas import (  # noqa: F401
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

# Repository
from modules.project.repositories import ProjectRepository  # noqa: F401

# Service
from modules.project.services import ProjectService  # noqa: F401

# Facade functions
from modules.project.facade import get_project_context  # noqa: F401

# API Router
from modules.project.api import router  # noqa: F401

# Legacy CRUD function aliases (保留旧名称兼容性)
from modules.project.repositories import ProjectRepository as _ProjectRepository
from modules.project.services import ProjectService as _ProjectService

_repo = _ProjectRepository()
_svc = _ProjectService()


async def create_project(db, data):
    """向后兼容：请使用 ProjectRepository.create 或 ProjectService.create_project"""
    return await _repo.create(db, data)


async def get_project_by_id(db, project_id):
    """向后兼容：请使用 ProjectRepository.get"""
    return await _repo.get(db, project_id)


async def list_projects(db, skip=0, limit=20):
    """向后兼容：请使用 ProjectRepository.list 或 ProjectService.list_projects"""
    return await _repo.list(db, skip=skip, limit=limit)


async def update_project(db, project_id, data):
    """向后兼容：请使用 ProjectRepository.update 或 ProjectService.update_project"""
    return await _repo.update(db, project_id, data)


async def delete_project(db, project_id):
    """向后兼容：请使用 ProjectRepository.delete 或 ProjectService.delete_project"""
    return await _repo.delete(db, project_id)
