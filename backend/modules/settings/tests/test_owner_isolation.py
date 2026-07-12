"""Owner isolation regression tests (D24).

未来账户系统接入时这测试不需改，只需加 authorizer 单测。
Demo 阶段所有全局表都靠 owner_id 唯一约束隔离；本测试断言两虚拟 owner
互不可见，且 UNIQUE(owner_id) 保证不出现重复行。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from modules.settings.models import GlobalLLMDefaults
from modules.settings.repositories import (
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
)


@pytest.mark.asyncio
async def test_owner_a_cannot_see_owner_b_global_llm(db_session):
    repo = GlobalLLMDefaultsRepository()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    await repo.upsert(db_session, {"owner_id": owner_a, "provider_id": "a"})
    await repo.upsert(db_session, {"owner_id": owner_b, "provider_id": "b"})
    a = await repo.get(db_session, owner_a)
    b = await repo.get(db_session, owner_b)
    assert a is not None
    assert b is not None
    assert a.provider_id == "a"
    assert b.provider_id == "b"
    assert a.owner_id != b.owner_id
    assert a.id != b.id


@pytest.mark.asyncio
async def test_owner_isolation_through_unique_constraint(db_session):
    """UNIQUE(owner_id) 保证两 owner 行不会冲突或互相覆盖。"""
    repo = GlobalLLMDefaultsRepository()
    owner_a = uuid.uuid4()
    for _ in range(3):
        await repo.upsert(db_session, {"owner_id": owner_a, "provider_id": "a"})
    a = await repo.get(db_session, owner_a)
    assert a is not None
    count = (
        await db_session.execute(
            select(func.count()).where(GlobalLLMDefaults.owner_id == owner_a)
        )
    ).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_owner_isolation_global_author_prefs(db_session):
    """全局作者偏好同样受 owner_id UNIQUE 约束保护。"""
    repo = GlobalAuthorPrefsRepository()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    await repo.upsert(
        db_session,
        {"owner_id": owner_a, "daily_goal": 1000, "editor_font": "serif"},
    )
    await repo.upsert(
        db_session,
        {"owner_id": owner_b, "daily_goal": 2000, "editor_font": "mono"},
    )
    a = await repo.get(db_session, owner_a)
    b = await repo.get(db_session, owner_b)
    assert a is not None
    assert b is not None
    assert a.daily_goal == 1000
    assert b.daily_goal == 2000
    assert a.editor_font == "serif"
    assert b.editor_font == "mono"
    assert a.id != b.id
