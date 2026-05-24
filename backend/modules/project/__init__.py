# modules/project — 小说项目管理模块
# 提供小说项目基础元信息的 CRUD 和上下文读取
# 作为其他所有模块的根，提供 novel_id 和项目级默认策略

from __future__ import annotations

from modules.project.contracts import ProjectContract
from modules.project.facade import get_project_context
from modules.project.models import Project
from modules.project.schemas import (
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)

__all__ = [
    "Project",
    "ProjectContract",
    "ProjectContext",
    "ProjectCreate",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdate",
    "get_project_context",
]
