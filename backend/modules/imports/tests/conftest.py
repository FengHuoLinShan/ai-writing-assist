"""
Import 模块测试配置

使用 SQLite 内存数据库进行测试，无需连接真实 PostgreSQL。
需要导入所有 ORM 模型注册到 Base.metadata 以确保建表完整。
"""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.base import Base

# 导入所有涉及的 ORM 模型注册到 Base.metadata
import modules.imports.models  # noqa: F401
import modules.outline.models  # noqa: F401
import modules.project.models  # noqa: F401
import modules.writing.models  # noqa: F401

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供内存 SQLite 测试数据库 session"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

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


@pytest.fixture
def repo():
    from modules.imports.repositories import ImportRecordRepository
    return ImportRecordRepository()


@pytest.fixture
def service():
    from modules.imports.services import ImportService
    return ImportService()


@pytest.fixture
def sample_txt_content() -> bytes:
    return (
        "序章\n"
        "这是一个序章的内容。\n\n"
        "第一章\n"
        "这是第一章的内容，主角出现了。\n\n"
        "第二章 新的旅程\n"
        "这是第二章，主角踏上了旅程。\n\n"
        "第3章\n"
        "这是第三章。\n"
    ).encode("utf-8")


@pytest.fixture
def sample_txt_no_chapters() -> bytes:
    return "这是一篇没有分章的纯文本内容。只有一段话。".encode("utf-8")


@pytest.fixture
def test_project_id() -> str:
    return str(uuid.uuid4())
