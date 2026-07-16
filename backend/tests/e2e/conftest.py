"""
E2E 测试 conftest — 真实 PostgreSQL 连接

与 SQLite 单元测试不同，本 conftest 连接到 Docker 运行的 PostgreSQL + pgvector。
每个测试函数使用独立连接，测试结束时回滚所有变更。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

from core.config import Settings
from core.database import (
    assert_database_target_for_testing,
    isolated_database_manager_for_testing,
)
from tests.e2e.config import DATABASE_URL, require_e2e_database_url
from tests.e2e.seed_data import create_base_scene, create_full_scene
from tests.support.http import XhrAsyncClient

logging.basicConfig(level=logging.WARNING)

_BACKEND_DIR = Path(__file__).resolve().parents[2]


# ============================================================
# 显式 E2E 前置条件：数据库与迁移必须可用，不能以 skip 伪装通过
# ============================================================


_E2E_DIR = Path(__file__).resolve().parent


async def _validate_e2e_database() -> None:
    database_url = require_e2e_database_url(DATABASE_URL)
    engine = create_async_engine(database_url, echo=False, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            migration_config = Config(str(_BACKEND_DIR / "alembic.ini"))
            migration_script = ScriptDirectory.from_config(migration_config)
            expected_heads = set(migration_script.get_heads())
            statement = text("SELECT version_num FROM alembic_version")
            current_heads = set((await connection.execute(statement)).scalars())
    except Exception as exc:
        raise RuntimeError(
            "PostgreSQL E2E 前置条件不满足：请启动测试数据库并执行 "
            "`make db && make migrate`，或设置 E2E_DATABASE_URL。"
        ) from exc
    finally:
        await engine.dispose()

    if current_heads != expected_heads:
        raise RuntimeError(
            "PostgreSQL E2E schema 不是当前 Alembic head："
            f"数据库={sorted(current_heads) or ['<none>']}，"
            f"期望={sorted(expected_heads)}。请先执行 `make migrate`。"
        )


def pytest_configure(config) -> None:  # noqa: ANN001
    if os.getenv("RUN_E2E_TESTS") != "1":
        pytest.exit(
            "E2E 测试必须显式运行：使用 `make test-e2e`；"
            "真实模型验收使用 `make test-manual`。"
        )
    try:
        asyncio.run(_validate_e2e_database())
    except RuntimeError as exc:
        pytest.exit(str(exc))


def pytest_collection_modifyitems(config, items) -> None:  # noqa: ANN001
    """Keep directory-level E2E classification correct for newly added files."""
    for item in items:
        item_path = Path(str(item.fspath)).resolve()
        if item_path.is_relative_to(_E2E_DIR):
            item.add_marker(pytest.mark.e2e)


@pytest_asyncio.fixture(autouse=True)
async def isolated_global_database_manager() -> AsyncGenerator[None, None]:
    """Bind every global DB path to the explicit E2E database and event loop."""

    database_url = require_e2e_database_url(DATABASE_URL)
    settings = Settings(
        database_url=database_url,
        pool_size=1,
        max_overflow=0,
    )
    async with isolated_database_manager_for_testing(settings) as manager:
        assert_database_target_for_testing(database_url, manager.engine.url)
        yield


# ============================================================
# Per-test database session（独立连接，事务回滚）
# ============================================================


@pytest_asyncio.fixture
async def db_session(
    isolated_global_database_manager: None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    每个测试函数使用独立 engine + 连接，连接级别事务回滚隔离。
    """
    database_url = require_e2e_database_url(DATABASE_URL)
    engine = create_async_engine(database_url, echo=False, pool_size=1, max_overflow=0)
    conn = await engine.connect()
    try:
        await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if conn.in_transaction():
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
    try:
        async with XhrAsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def base_scene(db_session: AsyncSession) -> dict:
    """Create the common project/world seed and expose its semantic metadata."""
    metadata = await create_base_scene(db_session)
    await db_session.flush()
    return metadata


@pytest_asyncio.fixture
async def full_scene(db_session: AsyncSession) -> dict:
    """Create the complete Scene/writing seed and expose its semantic metadata."""
    metadata = await create_full_scene(db_session)
    await db_session.flush()
    return metadata


@pytest_asyncio.fixture
async def project_client(
    async_client: AsyncClient,
    base_scene: dict,
) -> tuple[AsyncClient, str]:
    """Pair the HTTP client with a seeded active project id."""
    return async_client, base_scene["project_id"]


@pytest_asyncio.fixture
async def full_project_client(
    async_client: AsyncClient,
    full_scene: dict,
) -> tuple[AsyncClient, str]:
    """Pair the HTTP client with a fully seeded active project id."""
    return async_client, full_scene["project_id"]


@pytest_asyncio.fixture
async def base_scene_client(
    async_client: AsyncClient,
    base_scene: dict,
) -> tuple[AsyncClient, str, dict[str, str]]:
    """Pair the HTTP client with common project and entity identifiers."""
    return async_client, base_scene["project_id"], base_scene["entity_ids"]
