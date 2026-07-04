"""
集成测试 / API 测试共享 conftest

复用 backend/conftest.py 的 SQLite 数据库和 API client，并提供额外测试数据。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import _register_container_services
from core.container import reset as reset_container


@pytest.fixture(autouse=True)
def _reset_and_register_di_container() -> None:
    """每个测试前重置 DI 容器并重新注册服务，消除全局状态污染。"""
    reset_container()
    _register_container_services()


# ============================================================
# 共享 fixtures — 常用的测试数据工厂
# ============================================================


@pytest_asyncio.fixture
async def test_project_id(db_session: AsyncSession) -> str:
    """创建一个测试项目并返回其 ID"""
    import uuid

    from modules.project.models import Project

    pid = uuid.uuid4()
    p = Project(
        id=pid,
        title="测试小说",
        genre="奇幻悬疑",
        tone="黑暗",
        language="zh",
        current_stage="世界构建中",
    )
    db_session.add(p)
    await db_session.flush()
    return str(pid)


@pytest_asyncio.fixture
async def test_entity_id(db_session: AsyncSession, test_project_id: str) -> str:
    """创建一个测试世界对象并返回其 ID"""
    import uuid

    from modules.world.models import CoreEntity

    eid = uuid.uuid4()
    e = CoreEntity(
        id=eid,
        novel_id=uuid.UUID(hex=test_project_id),
        entity_type="item",
        name="测试物品",
        summary="一个测试物品",
        status="canonical",
    )
    db_session.add(e)
    await db_session.flush()
    return str(eid)


@pytest_asyncio.fixture
async def test_character_id(db_session: AsyncSession, test_project_id: str) -> str:
    """创建一个测试人物并返回其 entity_id (v3: 通过 CoreEntity)"""
    import uuid

    from modules.world.models import CoreEntity

    cid = uuid.uuid4()
    e = CoreEntity(
        id=cid,
        novel_id=uuid.UUID(hex=test_project_id),
        entity_type="character",
        name="测试主角",
        summary="测试角色",
        status="canonical",
    )
    db_session.add(e)
    await db_session.flush()
    return str(cid)
