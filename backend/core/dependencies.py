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

from core.database import get_db as _get_db

# 重新导出，让模块用户可以 from core.dependencies import get_db
get_db = _get_db

# --- Type alias for FastAPI Depends ---
# Function scope makes get_db commit or roll back before FastAPI starts sending
# a response. A successful non-streaming HTTP response therefore never races
# an immediately following independent read.
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
