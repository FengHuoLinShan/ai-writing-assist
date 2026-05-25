"""
集成测试 / API 测试共享 conftest

提供 SQLite 内存数据库 + FastAPI overridden dependency -> httpx AsyncClient。
所有 ORM 模型均被导入以注册到 Base.metadata，确保建表完整。
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.main import app
from core.base import Base
from core.dependencies import get_db


# ============================================================
# 导入所有 ORM 模型注册到 Base.metadata
# ============================================================
import modules.imports.models  # noqa: F401
import modules.project.models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.character.models  # noqa: F401
import modules.geo.models  # noqa: F401
import modules.memory.models  # noqa: F401
import modules.timeline.models  # noqa: F401
import modules.outline.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.review.models  # noqa: F401
import modules.writing.models  # noqa: F401
import infrastructure.tasks.models  # noqa: F401

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """SQLite 内存 session（所有表已创建）"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with SQLite db override"""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ============================================================
# 共享 fixtures — 常用的测试数据工厂
# ============================================================

@pytest_asyncio.fixture
async def test_project_id(db_session: AsyncSession) -> str:
    """创建一个测试项目并返回其 ID"""
    from modules.project.models import Project
    import uuid

    pid = uuid.uuid4()
    p = Project(
        id=pid,
        title="测试小说",
        genre="奇幻悬疑",
        tone="黑暗",
        language="zh",
        current_stage="世界构建中",
    )
    db_session.add(p)
    await db_session.flush()
    return str(pid)


@pytest_asyncio.fixture
async def test_entity_id(db_session: AsyncSession, test_project_id: str) -> str:
    """创建一个测试世界对象并返回其 ID"""
    from modules.world.models import WorldEntity
    import uuid

    eid = uuid.uuid4()
    e = WorldEntity(
        id=eid,
        novel_id=uuid.UUID(hex=test_project_id),
        entity_type="item",
        name="测试物品",
        summary="一个测试物品",
        status="canonical",
    )
    db_session.add(e)
    await db_session.flush()
    return str(eid)


@pytest_asyncio.fixture
async def test_character_id(db_session: AsyncSession, test_project_id: str) -> str:
    """创建一个测试人物并返回其 ID"""
    from modules.character.models import Character
    import uuid

    cid = uuid.uuid4()
    c = Character(
        id=cid,
        novel_id=uuid.UUID(hex=test_project_id),
        name="测试主角",
        role="主角",
    )
    db_session.add(c)
    await db_session.flush()
    return str(cid)
