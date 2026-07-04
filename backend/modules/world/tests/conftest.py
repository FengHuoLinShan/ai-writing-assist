"""World 模块 API 测试配置"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapConfig
from modules.world.tests.helpers import (
    _create_default_map,
    _create_location_entity,
    _create_map_config,
    _create_organization,
    _create_project,
)

# ============================================================
# Shared fixtures
# ============================================================


@pytest.fixture
def novel_id() -> str:
    """生成一个 novel_id（不创建 project）。"""
    return uuid.uuid4().hex


@pytest.fixture
def other_novel_id() -> str:
    """生成另一个 novel_id（不创建 project）。"""
    return uuid.uuid4().hex


@pytest_asyncio.fixture
async def project_novel_id(db_session: AsyncSession) -> str:
    """生成 novel_id 并创建对应 project。"""
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    return nid


@pytest_asyncio.fixture
async def two_projects(db_session: AsyncSession) -> tuple[str, str]:
    """创建两个 project，返回 (novel_id1, novel_id2)。"""
    nid1 = uuid.uuid4().hex
    nid2 = uuid.uuid4().hex
    await _create_project(db_session, nid1)
    await _create_project(db_session, nid2)
    return nid1, nid2


@pytest_asyncio.fixture
async def world_map_config(db_session: AsyncSession, project_novel_id: str) -> MapConfig:
    """直接创建 10x10 world MapConfig（不生成 tiles）。"""
    return await _create_map_config(db_session, project_novel_id)


@pytest_asyncio.fixture
async def world_map(db_session: AsyncSession, project_novel_id: str):
    """通过 MapConfigService 创建 10x10 world map（生成 tiles）。"""
    return await _create_default_map(db_session, project_novel_id)


@pytest_asyncio.fixture
async def location_entity_id(db_session: AsyncSession, project_novel_id: str) -> str:
    """创建一个 location 实体，返回 id。"""
    return await _create_location_entity(db_session, project_novel_id)


@pytest_asyncio.fixture
async def organization_entity_id(db_session: AsyncSession, project_novel_id: str) -> str:
    """创建一个 organization 实体，返回 id。"""
    return await _create_organization(db_session, project_novel_id)
