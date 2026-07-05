"""World 模块 repository 层集成测试。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.world.repositories import CoreEntityRepository


@pytest.fixture
def repo() -> CoreEntityRepository:
    return CoreEntityRepository()


@pytest.mark.asyncio
async def test_repo_count_entities(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = str(uuid.uuid4())
    db_session.add(
        Project(
            id=uuid.UUID(novel_id),
            title="t",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )

    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="A",
        status="canonical",
    )
    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="B",
        status="draft",
    )
    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="C",
        status="deprecated",
    )

    total = await repo.count_entities(db_session, uuid.UUID(novel_id))
    assert total == 3

    canonical_only = await repo.count_entities(
        db_session,
        uuid.UUID(novel_id),
        status_filter=["canonical"],
    )
    assert canonical_only == 1


@pytest.mark.asyncio
async def test_list_by_novel_uses_stable_pagination_for_tied_candidates(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = uuid.uuid4()
    db_session.add(
        Project(
            id=novel_id,
            title="stable pagination",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )

    for _ in range(4):
        entity = await repo.create_raw(
            db_session,
            novel_id=novel_id,
            entity_type="faction",
            name="塔罗会",
            status="candidate",
        )
        entity.importance = 0.85
        db_session.add(entity)
    await db_session.flush()

    page1 = await repo.list_by_novel(
        db_session,
        novel_id,
        status="candidate",
        skip=0,
        limit=2,
    )
    page2 = await repo.list_by_novel(
        db_session,
        novel_id,
        status="candidate",
        skip=2,
        limit=2,
    )

    page1_ids = {item.id for item in page1}
    page2_ids = {item.id for item in page2}
    assert len(page1_ids) == 2
    assert len(page2_ids) == 2
    assert page1_ids.isdisjoint(page2_ids)
