"""
共享测试配置

提供 SQLite 内存数据库 session fixture，所有模块测试共用。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import infrastructure.tasks.models  # noqa: F401
import modules.character.models  # noqa: F401
import modules.geo.models  # noqa: F401
import modules.imports.models  # noqa: F401
import modules.memory.models  # noqa: F401
import modules.outline.models  # noqa: F401

# 导入所有 ORM 模型注册到 Base.metadata
import modules.project.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.review.models  # noqa: F401
import modules.timeline.models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.writing.models  # noqa: F401
from core.base import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供内存 SQLite 测试数据库 session

    所有 ORM 表已注册到 Base.metadata。
    每个测试独立使用，完成后自动回滚。
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()
