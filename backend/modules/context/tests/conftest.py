"""Context 模块集成测试配置 — 复用根 conftest 的 db_session 并提供 API client。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import _register_container_services, app
from core.container import reset as reset_container
from core.dependencies import get_db


@pytest.fixture(autouse=True)
def _reset_di_container() -> None:
    """每个测试前重置 DI 容器并重新注册服务，消除全局状态污染。"""
    reset_container()
    _register_container_services()


@pytest_asyncio.fixture
async def async_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with SQLite db override"""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
