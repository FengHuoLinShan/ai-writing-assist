"""
E2E 测试 conftest — 真实 PostgreSQL 连接

与 SQLite 单元测试不同，本 conftest 连接到 Docker 运行的 PostgreSQL + pgvector。
每个测试函数使用独立连接，测试结束时回滚所有变更。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

logging.basicConfig(level=logging.WARNING)


def get_e2e_database_url() -> str:
    """Return the real PG URL from runtime config, including .env overrides."""
    from core.config import get_settings

    get_settings.cache_clear()
    return get_settings().database_url


# 真实 PG 数据库 — 与 Docker Compose / .env 配置一致，可由 DATABASE_URL 覆盖。
DATABASE_URL = get_e2e_database_url()


# ============================================================
# Per-test database session（独立连接，事务回滚）
# ============================================================


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    每个测试函数使用独立 engine + 连接，连接级别事务回滚隔离。
    """
    engine = create_async_engine(DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
    conn = await engine.connect()
    try:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await conn.rollback()
    finally:
        await conn.close()
        await engine.dispose()


# ============================================================
# FastAPI test client（真实 PG 注入）
# ============================================================


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx AsyncClient over ASGITransport — 不启动真实 uvicorn。
    依赖 get_db 被 override 为返回当前测试的 db_session（真实 PG）。
    """
    from app.main import app
    from core.dependencies import get_db

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
