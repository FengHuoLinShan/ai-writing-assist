"""
Writing 模块测试配置

使用 SQLite 内存数据库进行测试，无需连接真实 PostgreSQL。
需要导入 outline 模块的模型以确保 chapter_cards 表被创建（FK 引用）。
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.base import Base

# 导入依赖模块以确保 projects / chapter_cards 表被注册到 Base.metadata
# WritingDraft 引用了 projects.id 和 chapter_cards.id 的外键
import modules.project.models  # noqa: F401 — 确保 projects 表存在
import modules.outline.models  # noqa: F401 — 确保 chapter_cards 表存在

# 使用 aiosqlite 进行内存测试
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供内存 SQLite 测试数据库 session

    每个测试函数独立使用。
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
