"""
core/database.py 单元测试

测试 DatabaseManager 生命周期、session 管理、全局单例。
使用 SQLite 内存数据库，mock create_async_engine 去除 pool 参数。
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import Settings
from core.database import (
    DatabaseManager,
    get_manager,
    reset_manager,
)

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


def _create_sqlite_engine(url, **kwargs):
    """去除 SQLite 不支持的 pool_size/max_overflow 参数"""
    kwargs.pop("pool_size", None)
    kwargs.pop("max_overflow", None)
    kwargs.pop("pool_pre_ping", None)
    return create_async_engine(url, **kwargs)


@pytest.fixture
def db_settings():
    return Settings(database_url=SQLITE_URL)


@pytest.fixture
def manager(db_settings):
    return DatabaseManager(db_settings)


@pytest.fixture(autouse=True)
def _patch_engine():
    """所有测试自动使用 SQLite 兼容的 engine 创建"""
    with patch("core.database.create_async_engine", _create_sqlite_engine):
        yield


class TestDatabaseManagerInit:
    """DatabaseManager 初始化生命周期"""

    async def test_init_creates_engine(self, manager):
        manager.init()
        assert manager._engine is not None
        await manager.close()

    async def test_init_creates_session_factory(self, manager):
        manager.init()
        assert manager._session_factory is not None
        await manager.close()

    async def test_engine_property_raises_before_init(self, manager):
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = manager.engine

    async def test_session_factory_property_raises_before_init(self, manager):
        with pytest.raises(RuntimeError, match="not initialized"):
            _ = manager.session_factory

    async def test_double_init_is_noop(self, manager):
        manager.init()
        engine_after_first = manager._engine
        manager.init()
        assert manager._engine is engine_after_first
        await manager.close()

    async def test_close_disposes_engine(self, manager):
        manager.init()
        await manager.close()
        assert manager._engine is None
        assert manager._session_factory is None

    async def test_close_before_init_is_noop(self, manager):
        await manager.close()


class TestDatabaseManagerTables:
    """create_tables / drop_tables / check_vector_extension"""

    async def test_create_tables_does_not_raise(self, manager):
        manager.init()
        await manager.create_tables()
        await manager.close()

    async def test_drop_tables_does_not_raise(self, manager):
        manager.init()
        await manager.create_tables()
        await manager.drop_tables()
        await manager.close()

class TestDatabaseManagerSession:
    """session 创建与上下文管理器"""

    async def test_make_session_returns_async_session(self, manager):
        manager.init()
        session = manager.make_session()
        assert isinstance(session, AsyncSession)
        await session.close()
        await manager.close()

    async def test_session_context_manager_commits(self, manager):
        manager.init()
        await manager.create_tables()
        async with manager.session() as sess:
            result = await sess.execute(text("SELECT 1"))
            assert result.scalar() == 1
        await manager.close()

    async def test_session_context_manager_rollback_on_error(self, manager):
        manager.init()
        with pytest.raises(ValueError, match="test rollback"):
            async with manager.session():
                raise ValueError("test rollback")
        await manager.close()


class TestSessionProperties:
    """验证 session_factory 配置正确"""

    async def test_expire_on_commit_is_false(self, manager):
        manager.init()
        assert manager.session_factory.kw["expire_on_commit"] is False
        await manager.close()

    async def test_autoflush_is_false(self, manager):
        manager.init()
        session = manager.make_session()
        assert session.autoflush is False
        await session.close()
        await manager.close()


class TestGlobalManager:
    """get_manager / reset_manager 全局单例"""

    def setup_method(self):
        reset_manager()

    def teardown_method(self):
        reset_manager()

    def test_get_manager_returns_same_instance(self):
        assert get_manager() is get_manager()

    def test_reset_manager_creates_new_instance(self):
        m1 = get_manager()
        reset_manager()
        assert m1 is not get_manager()

    def test_reset_manager_sets_none(self):
        get_manager()
        reset_manager()
        from core.database import _manager
        assert _manager is None
