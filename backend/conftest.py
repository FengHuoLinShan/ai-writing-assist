"""
共享测试配置

提供 SQLite 内存数据库 session fixture，所有模块测试共用。
"""

from __future__ import annotations

# 必须在所有项目 import 之前设置，防止 lru_cache 缓存 bge_onnx 默认值
import os

os.environ.setdefault("EMBEDDING_PROVIDER", "openai")
os.environ.setdefault("LLM_HEALTH_REQUIRED", "false")
os.environ.setdefault(
    "LLM_SETTINGS_ENCRYPTION_KEY",
    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
)

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import infrastructure.tasks.models  # noqa: F401
import modules.context.models  # noqa: F401
import modules.imports.models  # noqa: F401

# character/geo/review/timeline 已从 minimal-core 移除
import modules.memory.models  # noqa: F401
import modules.outline.models  # noqa: F401

# 导入所有 ORM 模型注册到 Base.metadata
import modules.project.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.settings.models  # noqa: F401
import modules.world.map_models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.writing.models  # noqa: F401
from app.main import app
from core.base import Base
from core.dependencies import get_db

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


class XhrAsyncClient(AsyncClient):
    """Test client that mirrors the frontend write-request CSRF marker."""

    async def request(self, method: str, url, **kwargs):  # noqa: ANN001, ANN201
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("X-Requested-With", "XMLHttpRequest")
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)


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


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with SQLite db override."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def raw_async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client without automatic write-request guard headers."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
