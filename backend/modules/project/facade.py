"""
Project Facade — 对外入口

其他模块只能从 facade 或 contracts 导入。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.schemas import ProjectContext
from modules.project.services import ProjectService

_service = ProjectService()


async def get_project_context(
    db: AsyncSession,
    novel_id: str,
) -> ProjectContext | None:
    """获取项目上下文（供其他模块使用）"""
    return await _service.get_project_context(db, novel_id)
