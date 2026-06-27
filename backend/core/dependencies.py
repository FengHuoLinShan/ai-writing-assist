"""
FastAPI 依赖注入

提供：
- get_db: 注入 AsyncSession
- get_settings: 注入全局配置
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from core.database import get_db as _get_db

# 重新导出，让模块用户可以 from core.dependencies import get_db
get_db = _get_db

# --- Type alias for FastAPI Depends ---
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


# --- 可选：项目上下文依赖 ---
# 当需要从请求路径中提取 novel_id 并验证项目存在时使用
# 具体逻辑由 modules/project 提供，此处只定义接口骨架


class CurrentProject:
    """当前请求关联的项目上下文（由 Project 模块填充）"""

    def __init__(self, novel_id: str) -> None:
        self.novel_id = novel_id


# 注意：CurrentProject 的完整实现依赖 project 模块，
# 此处仅定义类型契约，后续由 project 模块的依赖注入函数补全。
