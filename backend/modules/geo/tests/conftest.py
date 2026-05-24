"""
Geo 模块测试配置

使用 SQLite 内存数据库进行测试。
导入 Project 模型以注册 projects 表，手动创建 world_entities 表供 FK 引用。
"""

from __future__ import annotations

from typing import AsyncGenerator

import pytest_asyncio
from sqlalchemy import MetaData, Table, Column, String, Text, Float, Integer, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import func

from core.base import Base

# 导入 Project 模型以注册 projects 表到 Base.metadata
from modules.project.models import Project

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供内存 SQLite 测试数据库 session"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    # 在 Base.metadata 中注册 world_entities 表（不依赖 World 模块模型）
    if "world_entities" not in Base.metadata.tables:
        Table(
            "world_entities",
            Base.metadata,
            Column("id", String(36), primary_key=True),
            Column("novel_id", String(36), nullable=False),
            Column("entity_type", String(32), nullable=False, default="location"),
            Column("name", String(255), nullable=False, default=""),
            Column("summary", Text, nullable=True),
            Column("public_info", Text, nullable=True),
            Column("hidden_truth", Text, nullable=True),
            Column("content_json", Text, default="{}"),
            Column("importance", Float, default=0.5),
            Column("importance_level", String(16), default="normal"),
            Column("reveal_level", String(32), default="author_only"),
            Column("status", String(32), default="draft"),
            Column("embedding_text", Text, nullable=True),
            Column("embedding", Text, nullable=True),
            Column("created_by", String(255), nullable=True),
            Column("approved_by", String(255), nullable=True),
            Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
            Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
            extend_existing=True,
        )

    # 创建所有注册的表（含 geo 模块的 3 张表）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
