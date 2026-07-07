"""World 模块 repository 层集成测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.world.models import Character, CoreEntity
from modules.world.repositories import CharacterRepository, CoreEntityRepository


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


@pytest.mark.asyncio
async def test_find_characters_by_location_filters_in_database(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    location_id = uuid.uuid4()
    other_location_id = uuid.uuid4()
    target_character_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(
                id=novel_id,
                title="location query",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            Project(
                id=other_novel_id,
                title="other novel",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            Character(
                entity_id=target_character_id,
                novel_id=novel_id,
                name="目标人物",
                status="canonical",
                current_state="在目标地点",
                meta={"location_id": str(location_id)},
            ),
            Character(
                entity_id=uuid.uuid4(),
                novel_id=novel_id,
                name="其他地点人物",
                status="canonical",
                current_state="在其他地点",
                meta={"location_id": str(other_location_id)},
            ),
            Character(
                entity_id=uuid.uuid4(),
                novel_id=other_novel_id,
                name="其他小说人物",
                status="canonical",
                current_state="跨 novel 泄漏候选",
                meta={"location_id": str(location_id)},
            ),
            Character(
                entity_id=uuid.uuid4(),
                novel_id=novel_id,
                name="废弃人物",
                status="deprecated",
                current_state="不应返回",
                meta={"location_id": str(location_id)},
            ),
        ]
    )
    await db_session.flush()

    result = await CharacterRepository().find_characters_by_location(
        db_session,
        novel_id,
        location_id,
    )

    assert result == [
        {
            "id": str(target_character_id),
            "name": "目标人物",
            "current_state": "在目标地点",
        }
    ]


@pytest.mark.asyncio
async def test_get_recent_auto_ingested_filters_json_bool_and_keeps_order_limit(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    base_time = datetime(2026, 7, 7, tzinfo=UTC)
    db_session.add_all(
        [
            Project(
                id=novel_id,
                title="auto ingest",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            Project(
                id=other_novel_id,
                title="other auto ingest",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="较早真值",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time,
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="较新真值",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=1),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="最新真值",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=2),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="布尔 false",
                status="canonical",
                content_json={"_meta": {"auto_ingested": False}},
                created_at=base_time + timedelta(minutes=3),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="字符串 true",
                status="canonical",
                content_json={"_meta": {"auto_ingested": "true"}},
                created_at=base_time + timedelta(minutes=4),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="非 canonical",
                status="draft",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=5),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=other_novel_id,
                entity_type="location",
                name="其他 novel",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=6),
            ),
        ]
    )
    await db_session.flush()

    result = await repo.get_recent_auto_ingested(db_session, novel_id, limit=2)

    assert [entity.name for entity in result] == ["最新真值", "较新真值"]
