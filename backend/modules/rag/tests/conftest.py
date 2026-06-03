"""RAG 模块测试配置 — 使用根 conftest 的 db_session"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.project import Project


@pytest.fixture
def sample_novel_id() -> uuid.UUID:
    """返回测试用的小说项目 ID"""
    return uuid.uuid4()


@pytest_asyncio.fixture
async def db_with_project(
    db_session: AsyncSession,
    sample_novel_id: uuid.UUID,
) -> AsyncSession:
    """创建包含 projects 记录的测试数据库"""
    project = Project(
        id=sample_novel_id,
        title="测试小说项目",
        genre="玄幻",
        language="zh",
    )
    db_session.add(project)
    await db_session.flush()
    return db_session
