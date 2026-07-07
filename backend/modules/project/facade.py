"""
Project Facade — 对外入口

其他模块只能从 facade 或 contracts 导入。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.schemas import ProjectContext
from modules.project.services import ProjectService

_service = ProjectService()
_repo = ProjectRepository()


async def get_project_context(
    db: AsyncSession,
    novel_id: str,
) -> ProjectContext | None:
    """获取项目上下文（供其他模块使用）"""
    return await _service.get_project_context(db, novel_id)


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
