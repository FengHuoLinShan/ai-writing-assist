"""
Project Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
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
    """获取项目上下文

    供其他模块（world、character、outline 等）获取项目基础信息。

    Args:
        db: 数据库 session
        novel_id: 项目 ID (UUID hex string)

    Returns:
        ProjectContext | None — 项目不存在时返回 None
    """
    return await _service.get_project_context(db, novel_id)
