"""EntityStatsService 测试 — 纯单元测试，不依赖真实 DB。"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.world.services.core.entity_stats_service import EntityStatsService


@pytest.fixture
def stats_service() -> EntityStatsService:
    return EntityStatsService(repo=MagicMock())


@pytest.mark.asyncio
async def test_stats_count_entities_delegates_to_repo(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    stats_service._repo.count_entities = AsyncMock(return_value=7)

    result = await stats_service.count_entities(db, novel_id, status_filter=["canonical"])

    assert result == 7
    stats_service._repo.count_entities.assert_awaited_once_with(
        db,
        uuid.UUID(novel_id),
        status_filter=["canonical"],
    )


def _mock_entity(**overrides: Any) -> MagicMock:
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "name": "Entity",
        "status": "canonical",
        "content_json": {},
    }
    defaults.update(overrides)
    entity = MagicMock()
    for key, value in defaults.items():
        setattr(entity, key, value)
    return entity


@pytest.mark.asyncio
async def test_list_auto_ingested_filters_by_meta_and_status(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    auto = _mock_entity(
        name="Auto",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 5}},
    )
    manual = _mock_entity(
        name="Manual",
        content_json={"_meta": {"auto_ingested": False}},
    )
    deprecated = _mock_entity(
        name="Deprecated",
        status="deprecated",
        content_json={"_meta": {"auto_ingested": True}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[auto, manual, deprecated])
    stats_service._repo.get_by_novel = AsyncMock()

    result = await stats_service.list_auto_ingested_entities(db, novel_id)

    assert len(result) == 1
    assert result[0]["name"] == "Auto"
    assert result[0]["status"] == "canonical"
    stats_service._repo.get_by_novel.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_auto_ingested_filters_by_chapter_range(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    inside = _mock_entity(
        name="Inside",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 3}},
    )
    outside = _mock_entity(
        name="Outside",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 10}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[inside, outside])

    result = await stats_service.list_auto_ingested_entities(
        db, novel_id, start_chapter=1, end_chapter=5
    )

    assert len(result) == 1
    assert result[0]["name"] == "Inside"


@pytest.mark.asyncio
async def test_list_auto_ingested_returns_empty_when_none(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    manual = _mock_entity(
        name="Manual",
        content_json={"_meta": {"auto_ingested": False}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[manual])

    result = await stats_service.list_auto_ingested_entities(db, novel_id)

    assert result == []


@pytest.mark.asyncio
async def test_list_auto_ingested_includes_exact_range_boundaries(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    start = _mock_entity(
        name="Start",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 2}},
    )
    end = _mock_entity(
        name="End",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 4}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[start, end])

    result = await stats_service.list_auto_ingested_entities(
        db, novel_id, start_chapter=2, end_chapter=4
    )

    assert len(result) == 2
    assert {entity["name"] for entity in result} == {"Start", "End"}


@pytest.mark.asyncio
async def test_list_auto_ingested_excludes_none_source_with_range(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    no_source = _mock_entity(
        name="NoSource",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": None}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[no_source])

    result = await stats_service.list_auto_ingested_entities(
        db, novel_id, start_chapter=1, end_chapter=5
    )

    assert result == []


@pytest.mark.asyncio
async def test_list_auto_ingested_handles_none_content_json(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    none_content = _mock_entity(
        name="NoneContent",
        content_json=None,
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[none_content])

    result = await stats_service.list_auto_ingested_entities(db, novel_id)

    assert result == []


@pytest.mark.asyncio
async def test_list_auto_ingested_includes_draft_status(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    draft = _mock_entity(
        name="Draft",
        status="draft",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 1}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[draft])

    result = await stats_service.list_auto_ingested_entities(db, novel_id)

    assert len(result) == 1
    assert result[0]["name"] == "Draft"
    assert result[0]["status"] == "draft"


@pytest.mark.asyncio
async def test_list_auto_ingested_includes_candidate_when_explicitly_requested(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    candidate = _mock_entity(
        name="Candidate",
        status="candidate",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 1}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[candidate])

    assert await stats_service.list_auto_ingested_entities(db, novel_id) == []
    result = await stats_service.list_auto_ingested_entities(
        db,
        novel_id,
        status_filter=["candidate", "draft", "canonical"],
    )

    assert [item["name"] for item in result] == ["Candidate"]


@pytest.mark.asyncio
async def test_list_auto_ingested_skips_malformed_source_chapter_index(
    stats_service: EntityStatsService,
) -> None:
    db = MagicMock()
    novel_id = str(uuid.uuid4())
    malformed = _mock_entity(
        name="Malformed",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": "abc"}},
    )
    valid = _mock_entity(
        name="Valid",
        content_json={"_meta": {"auto_ingested": True, "source_chapter_index": 3}},
    )

    stats_service._repo.list_by_novel = AsyncMock(return_value=[malformed, valid])

    result = await stats_service.list_auto_ingested_entities(
        db, novel_id, start_chapter=1, end_chapter=5
    )

    assert len(result) == 1
    assert result[0]["name"] == "Valid"
