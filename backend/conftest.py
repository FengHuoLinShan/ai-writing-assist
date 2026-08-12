"""
共享测试配置

提供 SQLite 内存数据库 session fixture，所有模块测试共用。
"""

from __future__ import annotations

# 必须在所有项目 import 之前设置，防止 lru_cache 缓存 bge_onnx 默认值
import os
import uuid
from datetime import UTC, datetime

os.environ.setdefault("EMBEDDING_PROVIDER", "openai")
os.environ.setdefault("LLM_HEALTH_REQUIRED", "false")
os.environ.setdefault(
    "LLM_SETTINGS_ENCRYPTION_KEY",
    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
)

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

import infrastructure.tasks.models  # noqa: F401
import modules.account.models  # noqa: F401
import modules.context.models  # noqa: F401
import modules.imports.models  # noqa: F401

# character/geo/review/timeline 已从 minimal-core 移除
import modules.memory.models  # noqa: F401
import modules.outline.models  # noqa: F401

# 导入所有 ORM 模型注册到 Base.metadata
import modules.project.models  # noqa: F401
import modules.rag.models  # noqa: F401
import modules.settings.models  # noqa: F401
import modules.world.map_atlas_models  # noqa: F401
import modules.world.models  # noqa: F401
import modules.writing.models  # noqa: F401
from app.bootstrap import register_container_services
from app.main import app
from core.base import Base
from core.container import reset as reset_container
from core.dependencies import get_db
from infrastructure.llm.secret_store import fingerprint_secret
from tests.support.http import XhrAsyncClient

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@compiles(PG_UUID, "sqlite")
def _compile_postgres_uuid_as_text_for_sqlite(_type, _compiler, **_kwargs) -> str:
    """Keep UUID hex values in SQLite text affinity instead of NUMERIC affinity."""
    return "CHAR(32)"


@pytest.fixture(autouse=True)
def _reset_application_state() -> AsyncGenerator[None, None]:
    """Keep global DI and FastAPI overrides isolated between every test."""
    app.dependency_overrides.clear()
    reset_container()
    register_container_services()
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        reset_container()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine() -> AsyncGenerator[object, None]:
    """Create the complete SQLite schema once for the test session."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    # sqlite3 otherwise defers BEGIN until the first write.  In that mode a
    # savepoint may become the outer transaction and ``commit()`` leaks data.
    @event.listens_for(engine.sync_engine, "connect")
    def _disable_sqlite_implicit_transactions(dbapi_connection, _connection_record):  # noqa: ANN001
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _start_sqlite_transaction(connection):  # noqa: ANN001
        connection.exec_driver_sql("BEGIN")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Return an isolated session while reusing the session-wide SQLite schema.

    Each test owns an outer transaction. ``join_transaction_mode`` turns an
    application-level ``commit()`` into a savepoint release, so the outer
    rollback always removes test data before the next test starts.
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


@pytest_asyncio.fixture
async def project_factory(db_session: AsyncSession):  # noqa: ANN201
    """Persist Project rows with the shared session and return their UUIDs."""
    from types import SimpleNamespace

    from modules.project.models import Project

    async def create_project(title: str = "T", **overrides) -> uuid.UUID:  # noqa: ANN003
        payload = {
            "title": title,
            "language": "zh",
            "default_reveal_policy": "author_safe",
            "settings": {},
            **overrides,
        }
        project = Project(**payload)
        db_session.add(project)
        await db_session.flush()
        return project.id

    return SimpleNamespace(create_project=create_project)


@pytest_asyncio.fixture
async def test_project_id(project_factory) -> str:  # noqa: ANN001
    """Create a Project row for tests that need a valid novel_id."""
    project_id = await project_factory.create_project(
        title="测试小说",
        genre="奇幻悬疑",
        tone="黑暗",
        current_stage="世界构建中",
    )
    return str(project_id)


@pytest_asyncio.fixture
async def account_llm_connection(db_session: AsyncSession):  # noqa: ANN201
    """Seed the default owner's verified DeepSeek connection without network I/O.

    Tests that exercise a business LLM entry point request this fixture
    explicitly. Negative tests intentionally omit it so the account-level
    "not connected" boundary remains covered.
    """
    from infrastructure.llm.secret_store import encrypt_secret
    from modules.settings.constants import (
        ACCOUNT_LLM_PROVIDER_TEMPLATES,
        LOCAL_OWNER_ID,
    )
    from modules.settings.repositories import (
        AccountLLMCredentialRepository,
        GlobalLLMDefaultsRepository,
    )

    api_key = "unit-test-account-key"
    await AccountLLMCredentialRepository().upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            "provider_id": "deepseek",
            "encrypted_api_key": encrypt_secret(api_key),
            "key_fingerprint": fingerprint_secret(
                api_key,
                purpose="account-llm-api-key",
            ),
            "verified_at": datetime.now(UTC),
        },
    )
    await GlobalLLMDefaultsRepository().upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
        },
    )
    return {
        "owner_id": LOCAL_OWNER_ID,
        "provider_id": "deepseek",
        "api_key": api_key,
        **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
    }


@pytest_asyncio.fixture
async def test_entity_id(db_session: AsyncSession, test_project_id: str) -> str:
    """Create a canonical entity owned by ``test_project_id``."""
    from modules.world.models import CoreEntity

    entity_id = uuid.uuid4()
    db_session.add(
        CoreEntity(
            id=entity_id,
            novel_id=uuid.UUID(hex=test_project_id),
            entity_type="item",
            name="测试物品",
            summary="一个测试物品",
            status="canonical",
        )
    )
    await db_session.flush()
    return str(entity_id)


@pytest_asyncio.fixture
async def test_character_id(db_session: AsyncSession, test_project_id: str) -> str:
    """Create a canonical character entity owned by ``test_project_id``."""
    from modules.world.models import CoreEntity

    character_id = uuid.uuid4()
    db_session.add(
        CoreEntity(
            id=character_id,
            novel_id=uuid.UUID(hex=test_project_id),
            entity_type="character",
            name="测试主角",
            summary="测试角色",
            status="canonical",
        )
    )
    await db_session.flush()
    return str(character_id)


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client with SQLite db override."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def raw_async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """FastAPI test client without automatic write-request guard headers."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
