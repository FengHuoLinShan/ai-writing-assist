# modules/project — 小说项目管理模块

from __future__ import annotations

from modules.project.api import router  # noqa: F401
from modules.project.facade import get_project_context  # noqa: F401
from modules.project.schemas import (  # noqa: F401
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

__all__ = [
    "ProjectContext",
    "ProjectCreate",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdate",
    "router",
    "get_project_context",
]
