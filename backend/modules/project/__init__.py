# modules/project — 小说项目管理模块

from __future__ import annotations

from modules.project.api import router  # noqa: F401
from modules.project.facade import get_project_context  # noqa: F401
from modules.project.models import Project  # noqa: F401
from modules.project.repositories import ProjectRepository  # noqa: F401
from modules.project.schemas import (  # noqa: F401
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from modules.project.services import ProjectService  # noqa: F401

__all__ = [
    "Project",
    "ProjectContext",
    "ProjectCreate",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdate",
    "ProjectRepository",
    "ProjectService",
    "router",
    "get_project_context",
]
