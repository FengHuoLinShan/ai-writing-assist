"""
E2E 测试 conftest — 真实 PostgreSQL 连接

与 SQLite 单元测试不同，本 conftest 连接到 Docker 运行的 PostgreSQL + pgvector。
每个测试函数使用独立连接，测试结束时回滚所有变更。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

logging.basicConfig(level=logging.WARNING)

# 真实 PG 数据库 — 与 Docker Compose / .env 配置一致
DATABASE_URL = (
    "postgresql+asyncpg://novelist:novel_dev_pass@localhost:5432/ai_novel_engine"
)


# ============================================================
# 环境可用性检查：无 PostgreSQL 时跳过全部 E2E 测试
# ============================================================


def _pg_available() -> bool:
    try:
        import asyncpg

        async def _check() -> bool:
            try:
                conn = await asyncpg.connect(DATABASE_URL, timeout=3, command_timeout=3)
                await conn.close()
                return True
            except Exception:
                return False

        return asyncio.run(_check())
    except Exception:
        return False


_PG_IS_AVAILABLE: bool = _pg_available()


def pytest_collection_modifyitems(config, items):
    """如果 PostgreSQL 不可用，跳过全部 e2e 测试。"""
    if not _PG_IS_AVAILABLE:
        skip_marker = pytest.mark.skip(
            reason="PostgreSQL 不可用（需要 Docker 运行 postgresql+pgvector）"
        )
        for item in items:
            item.add_marker(skip_marker)


# ============================================================
# 预启动 BGE Embedding Worker（避免 pytest 中 multiprocessing 初始化问题）
# ============================================================


def pytest_sessionstart(session):
    """在测试会话开始前预启动 BGE embedding worker。"""
    if not _PG_IS_AVAILABLE:
        return
    try:
        from infrastructure.embedding.client import BgeEmbeddingClient

        async def _init():
            client = await BgeEmbeddingClient.get_instance()
            if client.healthy:
                print("[BGE] Worker pre-started successfully")
            else:
                print("[BGE] Worker pre-start returned but not healthy")

        asyncio.run(_init())
    except Exception as exc:
        print(f"[BGE] Worker pre-start failed (will retry per-test): {exc}")


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
