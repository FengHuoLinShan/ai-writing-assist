"""EntityContextService 测试"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from modules.project.schemas import ProjectContext
from modules.world.models import CoreEntity
from modules.world.services.entity_context_service import EntityContextService


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def entity_service() -> EntityContextService:
    return EntityContextService()


def _make_entity(
    *,
    entity_id: str | None = None,
    name: str = "Entity",
    entity_type: str = "character",
    status: str = "canonical",
    hidden_truth: str | None = None,
    content_json: dict | None = None,
) -> CoreEntity:
    return CoreEntity(
        id=uuid.UUID(entity_id) if entity_id else uuid.uuid4(),
        novel_id=uuid.uuid4(),
        name=name,
        entity_type=entity_type,
        summary="A summary",
        public_info="Public",
        hidden_truth=hidden_truth,
        content_json=content_json or {},
        importance=0.8,
        importance_level="important",
        reveal_level="author_only",
        status=status,
    )


@pytest.mark.asyncio
async def test_get_entity_context_with_entity_ids(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity = _make_entity(name="Hero")
    entity_service._repo.get_by_ids = AsyncMock(return_value=[entity])
    db = AsyncMock()

    bundle = await entity_service.get_entity_context(
        db,
        novel_id,
        entity_ids=[str(entity.id)],
    )

    assert bundle.total_count == 1
    assert bundle.reveal_mode == "author_safe"
    assert len(bundle.entities) == 1
    assert bundle.entities[0].entity_id == str(entity.id)
    entity_service._repo.get_by_ids.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_entity_context_without_entity_ids_uses_get_by_novel(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity = _make_entity(name="Hero")
    entity_service._repo.get_by_novel = AsyncMock(return_value=([entity], 1))
    entity_service._repo.get_by_ids = AsyncMock(return_value=[])
    db = AsyncMock()

    bundle = await entity_service.get_entity_context(db, novel_id)

    assert bundle.total_count == 1
    entity_service._repo.get_by_novel.assert_awaited_once()
    entity_service._repo.get_by_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_author_only_reveal_mode_includes_hidden_truth(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity = _make_entity(name="Hero", hidden_truth="secret past")
    entity_service._repo.get_by_ids = AsyncMock(return_value=[entity])
    db = AsyncMock()

    bundle = await entity_service.get_entity_context(
        db,
        novel_id,
        entity_ids=[str(entity.id)],
        reveal_mode="author_only",
    )

    assert bundle.entities[0].hidden_truth == "secret past"


@pytest.mark.asyncio
async def test_author_safe_reveal_mode_excludes_hidden_truth(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity = _make_entity(name="Hero", hidden_truth="secret past")
    entity_service._repo.get_by_ids = AsyncMock(return_value=[entity])
    db = AsyncMock()

    bundle = await entity_service.get_entity_context(
        db,
        novel_id,
        entity_ids=[str(entity.id)],
        reveal_mode="author_safe",
    )

    assert bundle.entities[0].hidden_truth is None


@pytest.mark.asyncio
async def test_expired_temp_entity_filtered_out(
    novel_id: str,
    entity_service: EntityContextService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_entity = _make_entity(
        name="Temp",
        content_json={
            "_meta": {
                "temporary": True,
                "source_chapter_index": 1,
            }
        },
    )
    entity_service._repo.get_by_novel = AsyncMock(
        return_value=([temp_entity], 1)
    )
    monkeypatch.setattr(
        "modules.project.facade.get_project_context",
        AsyncMock(
            return_value=ProjectContext(
                novel_id=novel_id,
                title="Test",
                settings={"temporary_entity_expiry_chapters": 30},
            )
        ),
    )
    db = AsyncMock()

    bundle = await entity_service.get_entity_context(
        db, novel_id, current_chapter=50
    )

    assert bundle.total_count == 0


@pytest.mark.asyncio
async def test_non_temp_entity_always_included(
    novel_id: str,
    entity_service: EntityContextService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal_entity = _make_entity(
        name="Hero",
        content_json={"_meta": {"temporary": False}},
    )
    entity_service._repo.get_by_novel = AsyncMock(
        return_value=([normal_entity], 1)
    )
    monkeypatch.setattr(
        "modules.project.facade.get_project_context",
        AsyncMock(
            return_value=ProjectContext(
                novel_id=novel_id,
                title="Test",
                settings={},
            )
        ),
    )
    db = AsyncMock()

    bundle = await entity_service.get_entity_context(
        db, novel_id, current_chapter=100
    )

    assert bundle.total_count == 1
    assert bundle.entities[0].entity_id == str(normal_entity.id)


@pytest.mark.asyncio
async def test_list_entity_summaries_returns_id_name_type(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity = _make_entity(name="Hero", entity_type="character")
    entity_service._repo.get_by_type_and_status = AsyncMock(
        return_value=[entity]
    )
    db = AsyncMock()

    summaries = await entity_service.list_entity_summaries(
        db, novel_id, entity_type="character"
    )

    assert summaries == [
        {"id": entity.id, "name": "Hero", "entity_type": "character"}
    ]
    entity_service._repo.get_by_type_and_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_entity_terms_only_canonical_and_draft(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    canonical = _make_entity(name="Canon", status="canonical")
    draft = _make_entity(name="Draft", status="draft")
    pending = _make_entity(name="Pending", status="pending")
    entity_service._repo.get_by_novel = AsyncMock(
        return_value=([canonical, draft, pending], 3)
    )
    db = AsyncMock()

    terms = await entity_service.list_entity_terms(db, novel_id)

    names = {t["name"] for t in terms}
    assert names == {"Canon", "Draft"}
    assert "Pending" not in names


@pytest.mark.asyncio
async def test_list_entity_terms_extracts_aliases(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity = _make_entity(
        name="Arthur",
        content_json={
            "aliases": [
                "Art",
                {"alias": "King", "type": "title"},
            ]
        },
    )
    entity_service._repo.get_by_novel = AsyncMock(return_value=([entity], 1))
    db = AsyncMock()

    terms = await entity_service.list_entity_terms(db, novel_id)

    assert len(terms) == 1
    assert terms[0]["terms"] == ["Arthur", "Art", "King"]


@pytest.mark.asyncio
async def test_find_by_name_found_returns_id(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity_id = str(uuid.uuid4())
    entity_service._repo.find_entity_by_name = AsyncMock(return_value=entity_id)
    db = AsyncMock()

    result = await entity_service.find_by_name(
        db, novel_id, "Hero", entity_type="character"
    )

    assert result == entity_id
    entity_service._repo.find_entity_by_name.assert_awaited_once()


@pytest.mark.asyncio
async def test_find_by_name_not_found_returns_none(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    entity_service._repo.find_entity_by_name = AsyncMock(return_value=None)
    db = AsyncMock()

    result = await entity_service.find_by_name(db, novel_id, "Missing")

    assert result is None


@pytest.mark.asyncio
async def test_list_entity_batches_delegates_to_repo(
    novel_id: str,
    entity_service: EntityContextService,
) -> None:
    batches = [
        {
            "batch_id": "batch-1",
            "ingested_at": "2026-06-13T10:00:00",
            "entity_count": 2,
            "entities": [
                {"id": str(uuid.uuid4()), "name": "A", "entity_type": "character"},
                {"id": str(uuid.uuid4()), "name": "B", "entity_type": "location"},
            ],
        }
    ]
    entity_service._repo.get_entity_batches = AsyncMock(return_value=batches)
    db = AsyncMock()

    result = await entity_service.list_entity_batches(db, novel_id, limit=5)

    assert result == batches
    entity_service._repo.get_entity_batches.assert_awaited_once_with(
        db, uuid.UUID(novel_id), limit=5
    )
