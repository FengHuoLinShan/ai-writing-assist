"""EntityEmbeddingService 测试 — 使用 mocks，不依赖真实 BGE。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.services.core.entity_embedding_service import EntityEmbeddingService


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def embedding_service() -> EntityEmbeddingService:
    return EntityEmbeddingService()


def _make_entity(
    *,
    name: str = "Entity",
    status: str = "canonical",
    embedding: list[float] | None = None,
) -> CoreEntity:
    entity = MagicMock(spec=CoreEntity)
    entity.id = uuid.uuid4()
    entity.novel_id = uuid.uuid4()
    entity.name = name
    entity.status = status
    entity.embedding = embedding
    entity.embedding_text = None
    return entity


def _mock_db_execute(entities: list[CoreEntity]) -> AsyncMock:
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = entities
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = result_mock
    return db


@pytest.mark.asyncio
async def test_no_entities_returns_zero(
    novel_id: str,
    embedding_service: EntityEmbeddingService,
) -> None:
    db = _mock_db_execute([])

    count = await embedding_service.backfill_embeddings(db, novel_id)

    assert count == 0
    db.execute.assert_awaited_once()
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_bge_unavailable_returns_zero(
    novel_id: str,
    embedding_service: EntityEmbeddingService,
) -> None:
    entity = _make_entity(name="Arthur")
    db = _mock_db_execute([entity])

    with patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        side_effect=RuntimeError("BGE not found"),
        autospec=True,
    ):
        count = await embedding_service.backfill_embeddings(db, novel_id)

    assert count == 0
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_happy_path_backfills_in_batches(
    novel_id: str,
    embedding_service: EntityEmbeddingService,
) -> None:
    entities = [
        _make_entity(name="Arthur"),
        _make_entity(name="Bella"),
        _make_entity(name="Cora"),
        _make_entity(name="Derek"),
    ]
    db = _mock_db_execute(entities)

    bge_mock = AsyncMock()
    bge_mock.generate_embedding.return_value = [
        [0.1, 0.2],
        [0.3, 0.4],
        [0.5, 0.6],
        [0.7, 0.8],
    ]

    with patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        return_value=bge_mock,
        autospec=True,
    ):
        count = await embedding_service.backfill_embeddings(db, novel_id, batch_size=4)

    assert count == 4
    bge_mock.generate_embedding.assert_awaited_once_with(
        ["Arthur", "Bella", "Cora", "Derek"],
        is_query=False,
    )
    for entity in entities:
        assert entity.embedding is not None
        assert entity.embedding_text == entity.name
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_empty_name_entities(
    novel_id: str,
    embedding_service: EntityEmbeddingService,
) -> None:
    valid_entity = _make_entity(name="Arthur")
    empty_entity = _make_entity(name="  ")
    db = _mock_db_execute([valid_entity, empty_entity])

    bge_mock = AsyncMock()
    bge_mock.generate_embedding.return_value = [[0.1, 0.2]]

    with patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        return_value=bge_mock,
        autospec=True,
    ):
        count = await embedding_service.backfill_embeddings(db, novel_id)

    assert count == 1
    bge_mock.generate_embedding.assert_awaited_once_with(["Arthur"], is_query=False)
    assert valid_entity.embedding == [0.1, 0.2]
    assert valid_entity.embedding_text == "Arthur"
    assert empty_entity.embedding is None


@pytest.mark.asyncio
async def test_batch_failure_continues_to_next_batch(
    novel_id: str,
    embedding_service: EntityEmbeddingService,
) -> None:
    entities = [
        _make_entity(name="Arthur"),
        _make_entity(name="Bella"),
        _make_entity(name="Cora"),
        _make_entity(name="Derek"),
    ]
    db = _mock_db_execute(entities)

    bge_mock = AsyncMock()

    async def _generate(texts: list[str], *, is_query: bool = False):
        if "Arthur" in texts or "Bella" in texts:
            raise RuntimeError("batch 1 failed")
        return [[0.5, 0.6], [0.7, 0.8]]

    bge_mock.generate_embedding.side_effect = _generate

    with patch(
        "modules.world.services.core.entity_embedding_service.BgeEmbeddingClient.get_instance",
        return_value=bge_mock,
        autospec=True,
    ):
        count = await embedding_service.backfill_embeddings(db, novel_id, batch_size=2)

    assert count == 2
    assert entities[0].embedding is None
    assert entities[1].embedding is None
    assert entities[2].embedding == [0.5, 0.6]
    assert entities[3].embedding == [0.7, 0.8]
    assert db.flush.await_count == 1
