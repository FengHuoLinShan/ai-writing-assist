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

from sqlalchemy import text
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


def get_manager() -> DatabaseManager:
    """获取全局 DatabaseManager 单例"""
    global _manager
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
    _manager = None
