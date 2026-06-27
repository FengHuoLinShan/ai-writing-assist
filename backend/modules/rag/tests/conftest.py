"""RAG 模块测试配置 — 使用根 conftest 的 db_session"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as container_get
from core.container import register
from modules.project.models import Project
from modules.world.facade import list_characters, list_entity_terms


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
    try:
        container_get("world.list_characters")
    except KeyError:
        register("world.list_characters", list_characters)
    try:
        container_get("world.list_entity_terms")
    except KeyError:
        register("world.list_entity_terms", list_entity_terms)
    project = Project(
        id=sample_novel_id,
        title="测试小说项目",
        genre="玄幻",
        language="zh",
    )
    db_session.add(project)
    await db_session.flush()
    yield db_session


@pytest.fixture(autouse=True)
def _mock_llm_embedding():
    """默认 mock LLM embedding，避免测试调用真实网络服务。"""
    from unittest.mock import AsyncMock, patch

    with patch(
        "infrastructure.llm.client.LLMClient.generate_embedding",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = [0.1] * 768
        yield mock
