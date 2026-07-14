"""
core/database.py 单元测试

测试 DatabaseManager 生命周期、session 管理、全局单例。
使用 SQLite 内存数据库，mock create_async_engine 去除 pool 参数。
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core import database as database_module
from core.config import Settings
from core.database import (
    DatabaseManager,
    assert_database_target_for_testing,
    get_manager,
    isolated_database_manager_for_testing,
    reset_manager,
)
from tests.e2e.config import require_e2e_database_url

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
    with patch(
        "core.database.create_async_engine",
        autospec=True,
        side_effect=_create_sqlite_engine,
    ):
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

    def test_database_target_accepts_normalized_host_default_port_and_credentials(self):
        assert_database_target_for_testing(
            "postgresql+asyncpg://alice:first-secret@DB.EXAMPLE/story",
            "postgresql+asyncpg://bob:second-secret@db.example:5432/story",
        )

    def test_database_target_normalizes_equivalent_ipv6_hosts(self):
        assert_database_target_for_testing(
            "postgresql+asyncpg://alice:first-secret@[2001:db8::1]/story",
            "postgresql+asyncpg://bob:second-secret@[2001:0DB8:0:0:0:0:0:1]:5432/story",
        )

    def test_database_target_keeps_distinct_database_names_fail_closed(self):
        with pytest.raises(RuntimeError, match="target mismatch"):
            assert_database_target_for_testing(
                "postgresql+asyncpg://user:secret@db.example/story",
                "postgresql+asyncpg://user:secret@db.example//story",
            )

    def test_database_target_rejects_cross_backend_match(self):
        with pytest.raises(RuntimeError, match="target mismatch"):
            assert_database_target_for_testing(
                "postgresql+asyncpg://user:secret@db.example:5432/story",
                "mysql+aiomysql://user:secret@db.example:5432/story",
            )

    def test_database_target_keeps_non_postgresql_default_port_fail_closed(self):
        with pytest.raises(RuntimeError, match="target mismatch"):
            assert_database_target_for_testing(
                "mysql+aiomysql://user:secret@db.example/story",
                "mysql+aiomysql://user:secret@db.example:3306/story",
            )

    def test_database_target_supports_identical_sqlite_targets(self):
        assert_database_target_for_testing(SQLITE_URL, SQLITE_URL)

    def test_database_target_mismatch_fails_closed_without_credentials(self):
        with pytest.raises(RuntimeError) as exc_info:
            assert_database_target_for_testing(
                "postgresql+asyncpg://alice:first-secret@db.example:5432/e2e_story",
                "postgresql+asyncpg://bob:second-secret@db.example:5433/dev_story",
            )

        message = str(exc_info.value)
        assert "host=db.example" in message
        assert "port=5432" in message
        assert "database=e2e_story" in message
        assert "port=5433" in message
        assert "database=dev_story" in message
        assert "alice" not in message
        assert "bob" not in message
        assert "first-secret" not in message
        assert "second-secret" not in message

    def test_database_target_invalid_url_error_does_not_echo_credentials(self):
        with pytest.raises(RuntimeError) as exc_info:
            assert_database_target_for_testing(
                "postgresql+asyncpg://alice:first-secret@db.example:not-a-port/story",
                "postgresql+asyncpg://bob:second-secret@db.example/story",
            )

        message = str(exc_info.value)
        assert message == "Expected test database URL is invalid"
        assert "alice" not in message
        assert "first-secret" not in message

    def test_database_target_redacts_unsafe_mismatch_components(self):
        with pytest.raises(RuntimeError) as exc_info:
            assert_database_target_for_testing(
                "postgresql+asyncpg://alice:first-secret@db.example/story",
                "postgresql+asyncpg://bob:second-secret@unsafe@host/story%0Asecret",
            )

        message = str(exc_info.value)
        assert "<redacted>" in message
        assert "unsafe@host" not in message
        assert "second-secret" not in message

    async def test_isolated_test_manager_closes_before_loop_teardown(self):
        settings = Settings(database_url=SQLITE_URL)

        async with isolated_database_manager_for_testing(settings) as installed:
            assert get_manager() is installed
            assert installed._engine is not None

        from core.database import _manager

        assert _manager is None
        assert database_module._isolated_test_manager is None
        assert installed._engine is None
        assert installed._session_factory is None

    async def test_isolated_test_manager_refuses_to_replace_existing_manager(self):
        async with isolated_database_manager_for_testing(
            Settings(database_url=SQLITE_URL)
        ) as existing:
            with pytest.raises(RuntimeError, match="already exists"):
                async with isolated_database_manager_for_testing(
                    Settings(database_url=SQLITE_URL)
                ):
                    pytest.fail("existing manager must fail before yielding")
            assert get_manager() is existing

    async def test_isolated_test_manager_refuses_reset_and_default_fallback(self):
        async with isolated_database_manager_for_testing(
            Settings(database_url=SQLITE_URL)
        ) as installed:
            with pytest.raises(RuntimeError, match="Cannot reset"):
                reset_manager()
            assert get_manager() is installed

    async def test_isolated_test_manager_cleans_up_after_body_error(self):
        installed = None
        with pytest.raises(ValueError, match="body failed"):
            async with isolated_database_manager_for_testing(
                Settings(database_url=SQLITE_URL)
            ) as installed:
                raise ValueError("body failed")

        assert installed is not None
        assert database_module._manager is None
        assert database_module._isolated_test_manager is None
        assert installed._engine is None
        assert installed._session_factory is None

    async def test_isolated_test_manager_cleans_unexpected_replacement_first(self):
        original_close = DatabaseManager.close
        close_order: list[
            tuple[DatabaseManager, DatabaseManager | None, DatabaseManager | None]
        ] = []

        async def _record_close(instance: DatabaseManager) -> None:
            close_order.append(
                (
                    instance,
                    database_module._manager,
                    database_module._isolated_test_manager,
                )
            )
            await original_close(instance)

        replacement = DatabaseManager(Settings(database_url=SQLITE_URL))
        replacement.init()
        with patch.object(
            DatabaseManager,
            "close",
            autospec=True,
            side_effect=_record_close,
        ):
            async with isolated_database_manager_for_testing(
                Settings(database_url=SQLITE_URL)
            ) as installed:
                database_module._manager = replacement
                with pytest.raises(RuntimeError, match="changed"):
                    get_manager()

        assert [item[0] for item in close_order] == [replacement, installed]
        assert all(global_manager is None for _, global_manager, _ in close_order)
        assert all(active_manager is installed for _, _, active_manager in close_order)
        assert database_module._manager is None
        assert database_module._isolated_test_manager is None
        assert replacement._engine is None
        assert installed._engine is None


class TestE2EDatabaseConfiguration:
    def test_requires_explicit_url(self):
        with pytest.raises(RuntimeError, match="must be set explicitly"):
            require_e2e_database_url("")

    def test_rejects_developer_database(self):
        with pytest.raises(RuntimeError, match="dedicated database"):
            require_e2e_database_url(
                "postgresql+asyncpg://user:secret@localhost/ai_novel_engine"
            )

    def test_rejects_non_postgresql_url(self):
        with pytest.raises(RuntimeError, match="must use PostgreSQL"):
            require_e2e_database_url("sqlite+aiosqlite:///e2e_test.db")

    def test_rejects_marker_substrings(self):
        with pytest.raises(RuntimeError, match="dedicated database"):
            require_e2e_database_url(
                "postgresql+asyncpg://user:secret@localhost/ai_novel_engine_e2evil"
            )

    def test_accepts_explicit_dedicated_postgresql_url(self):
        value = "postgresql+asyncpg://user:secret@localhost/ai_novel_engine_e2e"

        assert require_e2e_database_url(value) == value

    def test_accepts_explicit_dedicated_audit_database(self):
        value = (
            "postgresql+asyncpg://user:secret@localhost/"
            "ai_novel_engine_codex_audit_019f6032"
        )

        assert require_e2e_database_url(value) == value

    def test_invalid_url_error_does_not_echo_credentials(self):
        value = "postgresql+asyncpg://alice:first-secret@localhost:not-a-port/e2e"

        with pytest.raises(RuntimeError) as exc_info:
            require_e2e_database_url(value)

        assert str(exc_info.value) == "E2E_DATABASE_URL is not a valid database URL"
        assert "alice" not in str(exc_info.value)
        assert "first-secret" not in str(exc_info.value)
