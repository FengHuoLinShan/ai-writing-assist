"""
数据库连接管理

提供：
- DatabaseManager: engine 生命周期管理
- get_db(): FastAPI 兼容的 async generator 依赖
- create_tables(): 测试/迁移用建表函数
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import ip_address

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.base import Base
from core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """管理 SQLAlchemy AsyncEngine 和 session 工厂的生命周期"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings: Settings = settings or get_settings()
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("DatabaseManager not initialized. Call .init() first.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("DatabaseManager not initialized. Call .init() first.")
        return self._session_factory

    def init(self) -> None:
        """初始化 engine 和 session 工厂"""
        if self._engine is not None:
            logger.warning("DatabaseManager already initialized, skipping.")
            return

        self._engine = create_async_engine(
            self._settings.database_url,
            pool_size=self._settings.pool_size,
            max_overflow=self._settings.max_overflow,
            echo=self._settings.echo_sql,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
        logger.info(
            "DatabaseManager initialized — pool_size=%s, max_overflow=%s",
            self._settings.pool_size,
            self._settings.max_overflow,
        )

    async def close(self) -> None:
        """关闭 engine，释放所有连接"""
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("DatabaseManager closed.")

    async def create_tables(self) -> None:
        """创建所有注册的 ORM 表（测试/迁移用）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_tables(self) -> None:
        """删除所有表（测试用）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def check_vector_extension(self) -> bool:
        """检查 pgvector 扩展是否可用"""
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            row = result.scalar_one_or_none()
            return row == "vector"

    def make_session(self) -> AsyncSession:
        """创建新的独立 session"""
        return self.session_factory()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """上下文管理器方式获取 session"""
        async with self.session_factory() as sess:
            try:
                yield sess
                await sess.commit()
            except Exception:
                await sess.rollback()
                raise


# 全局单例
_manager: DatabaseManager | None = None
_isolated_test_manager: DatabaseManager | None = None


def get_manager() -> DatabaseManager:
    """获取全局 DatabaseManager 单例"""
    global _manager
    if _isolated_test_manager is not None:
        if _manager is not _isolated_test_manager:
            raise RuntimeError(
                "Global DatabaseManager changed during an isolated test scope"
            )
        return _isolated_test_manager
    if _manager is None:
        _manager = DatabaseManager()
        _manager.init()
    return _manager


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入 — 获取 AsyncSession（自动提交/回滚）"""
    manager = get_manager()
    async with manager.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def reset_manager() -> None:
    """重置全局单例（测试用）"""
    global _manager
    if _isolated_test_manager is not None:
        raise RuntimeError("Cannot reset DatabaseManager during an isolated test scope")
    _manager = None


def assert_database_target_for_testing(
    expected_url: str | URL,
    actual_url: str | URL,
) -> None:
    """Fail closed when two test URLs target different databases.

    Only the normalized backend, host, port, and database name are compared.
    Credentials are deliberately excluded from diagnostics.
    """

    try:
        expected = _database_target_for_testing(expected_url)
    except (ArgumentError, AttributeError, TypeError, ValueError):
        raise RuntimeError("Expected test database URL is invalid") from None
    try:
        actual = _database_target_for_testing(actual_url)
    except (ArgumentError, AttributeError, TypeError, ValueError):
        raise RuntimeError("Actual test database URL is invalid") from None
    if actual != expected:
        raise RuntimeError(
            "Test database target mismatch: "
            f"expected={_format_database_target(expected)}, "
            f"actual={_format_database_target(actual)}"
        )


@asynccontextmanager
async def isolated_database_manager_for_testing(
    settings: Settings,
) -> AsyncIterator[DatabaseManager]:
    """Install and close one explicit global manager for a test event loop.

    This narrow test-only seam exists because ``reset_manager()`` cannot await
    engine disposal, while mutating ``DATABASE_URL`` cannot replace an already
    cached ``Settings`` instance safely. It must never replace an existing
    manager: that instance may own connections bound to another event loop or
    database, so the fixture fails closed instead.
    """

    global _isolated_test_manager, _manager
    if _manager is not None or _isolated_test_manager is not None:
        raise RuntimeError(
            "Cannot install isolated test DatabaseManager while a global "
            "manager already exists"
        )

    manager = DatabaseManager(settings)
    manager.init()
    _manager = manager
    _isolated_test_manager = manager
    try:
        yield manager
    finally:
        installed_manager = _manager
        _manager = None
        try:
            if installed_manager is not None and installed_manager is not manager:
                await installed_manager.close()
        finally:
            try:
                await manager.close()
            finally:
                _isolated_test_manager = None


def _database_target_for_testing(
    database_url: str | URL,
) -> tuple[str, str, int | None, str]:
    url = make_url(database_url) if isinstance(database_url, str) else database_url
    backend = url.get_backend_name().strip().lower()
    host = (url.host or "").strip().lower().rstrip(".")
    if host:
        try:
            host = ip_address(host).compressed.lower()
        except ValueError:
            pass
    port = url.port
    if port is None and backend == "postgresql":
        port = 5432
    # ``URL.database`` is already the driver-facing name. Do not strip a
    # leading slash or whitespace: PostgreSQL can treat those as distinct,
    # quoted database names, and an isolation check must fail closed.
    database = url.database or ""
    return backend, host, port, database


def _format_database_target(target: tuple[str, str, int | None, str]) -> str:
    backend, host, port, database = target
    return (
        f"backend={_safe_database_target_component(backend)},"
        f"host={_safe_database_target_component(host) if host else '<local>'},"
        f"port={port if port is not None else '<default>'},"
        "database="
        f"{_safe_database_target_component(database) if database else '<none>'}"
    )


def _safe_database_target_component(value: str) -> str:
    """Keep mismatch diagnostics useful without echoing malformed URL payloads."""

    if len(value) > 128 or any(
        not (character.isascii() and (character.isalnum() or character in ".:_-/%"))
        for character in value
    ):
        return "<redacted>"
    return value
