"""Memory 模块测试配置 — 继承根 conftest 的 db_session 和 test_project_id"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.models import MemoryEvent
from modules.memory.repositories import EventRepository, SnapshotRepository
from modules.memory.services import MemoryService
from modules.project.models import Project


@pytest.fixture
def event_repo() -> EventRepository:
    return EventRepository()


@pytest.fixture
def snapshot_repo() -> SnapshotRepository:
    return SnapshotRepository()


@pytest.fixture
def memory_service() -> MemoryService:
    return MemoryService()


@pytest_asyncio.fixture
async def db_with_project(db_session: AsyncSession) -> AsyncSession:
    """注入一个 Project 行确保 FK 约束通过"""
    project = Project(
        id=uuid.uuid4(),
        title="测试项目",
        genre="奇幻",
    )
    db_session.add(project)
    await db_session.flush()
    return db_session


@pytest_asyncio.fixture
async def sample_novel_id(db_with_project: AsyncSession) -> uuid.UUID:
    """返回已注入 Project 的 ID"""
    from sqlalchemy import select
    result = await db_with_project.execute(select(Project.id).limit(1))
    return result.scalar_one()


def make_mock_event(**overrides) -> MemoryEvent:
    """工厂函数：创建一个 mock MemoryEvent 对象用于测试"""
    import uuid as _uuid
    defaults = {
        "id": _uuid.uuid4(),
        "novel_id": _uuid.uuid4(),
        "chapter_index": 1,
        "sequence": 1,
        "event_type": "entity_created",
        "entity_id": _uuid.uuid4(),
        "entity_type": "character",
        "snapshot_before": None,
        "snapshot_after": {"name": "test"},
        "source": "ai_extraction",
    }
    defaults.update(overrides)
    return MemoryEvent(**defaults)
