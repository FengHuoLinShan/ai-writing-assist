"""Unit tests for entity_facade functions

Covers the thin facade layer that delegates to internal services.
All external dependencies are mocked to keep tests fast and isolated.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from pydantic import ValidationError

from modules.world.facade import (
    backfill_entity_embeddings,
    create_relation,
    get_entity_relations,
    merge_candidate_into_entity,
    upsert_relation,
    upsert_relationship,
)
from modules.world.schemas import EntityRelationResponse

pytestmark = [pytest.mark.asyncio]

TEST_NOVEL_ID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _relation_response(**overrides) -> EntityRelationResponse:
    """Build a valid EntityRelationResponse with sensible defaults."""
    defaults = {
        "id": str(uuid.uuid4()),
        "novel_id": TEST_NOVEL_ID,
        "source_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "relation_type": "friend",
        "description": None,
        "strength": 0.5,
        "source_chapter_id": None,
        "caused_by_event_id": None,
        "quote": None,
        "status": "canonical",
    }
    defaults.update(overrides)
    return EntityRelationResponse(**defaults)


# ===========================================================================
# create_relation
# ===========================================================================


@mock.patch("modules.world.entity_facade._relation_service")
async def test_create_relation_happy_path_returns_response(mock_relation_service):
    """Valid dict is converted to EntityRelationCreate and forwarded to service."""
    # Arrange
    expected = _relation_response(relation_type="enemy")
    mock_relation_service.create = mock.AsyncMock(return_value=expected)
    db = mock.AsyncMock()
    data = {
        "source_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "relation_type": "enemy",
        "strength": 0.9,
    }

    # Act
    result = await create_relation(db, TEST_NOVEL_ID, data)

    # Assert
    assert result == expected
    mock_relation_service.create.assert_awaited_once()
    call_args = mock_relation_service.create.call_args
    assert call_args[0][0] is db
    assert call_args[0][1] == TEST_NOVEL_ID
    rel_create = call_args[0][2]
    assert rel_create.source_id == data["source_id"]
    assert rel_create.target_id == data["target_id"]
    assert rel_create.relation_type == "enemy"
    assert rel_create.strength == 0.9


@mock.patch("modules.world.entity_facade._relation_service")
async def test_create_relation_missing_required_field_raises_validation_error(
    mock_relation_service,
):
    """Missing required fields cause Pydantic ValidationError before service call."""
    # Arrange
    db = mock.AsyncMock()
    data = {"target_id": str(uuid.uuid4()), "relation_type": "enemy"}  # missing source_id

    # Act & Assert
    with pytest.raises(ValidationError):
        await create_relation(db, TEST_NOVEL_ID, data)

    mock_relation_service.create.assert_not_called()


# ===========================================================================
# get_entity_relations
# ===========================================================================


@mock.patch("modules.world.entity_facade._relation_service")
async def test_get_entity_relations_happy_path_returns_list_and_total(
    mock_relation_service,
):
    """Default skip/limit are forwarded; tuple (items, total) is returned."""
    # Arrange
    items = [_relation_response(), _relation_response()]
    mock_relation_service.list = mock.AsyncMock(return_value=(items, 42))
    db = mock.AsyncMock()

    # Act
    result = await get_entity_relations(db, TEST_NOVEL_ID)

    # Assert
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[0] == items
    assert result[1] == 42
    mock_relation_service.list.assert_awaited_once_with(
        db, TEST_NOVEL_ID, skip=0, limit=100
    )


@mock.patch("modules.world.entity_facade._relation_service")
async def test_get_entity_relations_custom_pagination_respects_skip_limit(
    mock_relation_service,
):
    """Custom skip and limit values are passed through to the service."""
    # Arrange
    mock_relation_service.list = mock.AsyncMock(return_value=([], 0))
    db = mock.AsyncMock()

    # Act
    result = await get_entity_relations(db, TEST_NOVEL_ID, skip=10, limit=5)

    # Assert
    mock_relation_service.list.assert_awaited_once_with(
        db, TEST_NOVEL_ID, skip=10, limit=5
    )
    assert result == ([], 0)


@mock.patch("modules.world.entity_facade._relation_service")
async def test_get_entity_relations_service_exception_propagates(mock_relation_service):
    """Exceptions from the underlying service bubble up unchanged."""
    # Arrange
    mock_relation_service.list = mock.AsyncMock(side_effect=RuntimeError("db down"))
    db = mock.AsyncMock()

    # Act & Assert
    with pytest.raises(RuntimeError, match="db down"):
        await get_entity_relations(db, TEST_NOVEL_ID)


# ===========================================================================
# upsert_relation
# ===========================================================================


@mock.patch("modules.world.entity_facade._relation_service")
async def test_upsert_relation_happy_path_returns_response(mock_relation_service):
    """All positional args and description are forwarded to service.upsert."""
    # Arrange
    expected = _relation_response(description="old rivals")
    mock_relation_service.upsert = mock.AsyncMock(return_value=expected)
    db = mock.AsyncMock()
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    # Act
    result = await upsert_relation(
        db,
        TEST_NOVEL_ID,
        source_id,
        target_id,
        "rival",
        description="old rivals",
    )

    # Assert
    assert result == expected
    mock_relation_service.upsert.assert_awaited_once_with(
        db, TEST_NOVEL_ID, source_id, target_id, "rival", description="old rivals"
    )


@mock.patch("modules.world.entity_facade._relation_service")
async def test_upsert_relation_with_none_description_forwards_none(
    mock_relation_service,
):
    """Description defaults to None and is still forwarded explicitly."""
    # Arrange
    expected = _relation_response()
    mock_relation_service.upsert = mock.AsyncMock(return_value=expected)
    db = mock.AsyncMock()
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    # Act
    result = await upsert_relation(
        db, TEST_NOVEL_ID, source_id, target_id, "ally"
    )

    # Assert
    assert result == expected
    mock_relation_service.upsert.assert_awaited_once_with(
        db, TEST_NOVEL_ID, source_id, target_id, "ally", description=None
    )


@mock.patch("modules.world.entity_facade._relation_service")
async def test_upsert_relation_service_exception_propagates(mock_relation_service):
    """Exceptions from the underlying service bubble up unchanged."""
    # Arrange
    mock_relation_service.upsert = mock.AsyncMock(side_effect=ConnectionError("lost"))
    db = mock.AsyncMock()

    # Act & Assert
    with pytest.raises(ConnectionError, match="lost"):
        await upsert_relation(
            db, TEST_NOVEL_ID, "s1", "t1", "friend"
        )


# ===========================================================================
# upsert_relationship
# ===========================================================================


@mock.patch("modules.world.entity_facade._relation_service")
async def test_upsert_relationship_happy_path_delegates_and_ignores_source_target_types(
    mock_relation_service,
):
    """Compatible wrapper delegates to upsert and drops source_type / target_type."""
    # Arrange
    mock_relation_service.upsert = mock.AsyncMock(return_value=None)
    db = mock.AsyncMock()
    source_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    # Act
    result = await upsert_relationship(
        db,
        TEST_NOVEL_ID,
        source_id,
        target_id,
        source_type="character",
        target_type="item",
        relation_type="owns",
        description="possession",
    )

    # Assert
    assert result is None
    mock_relation_service.upsert.assert_awaited_once_with(
        db,
        TEST_NOVEL_ID,
        source_id=source_id,
        target_id=target_id,
        relation_type="owns",
        description="possession",
    )


@mock.patch("modules.world.entity_facade._relation_service")
async def test_upsert_relationship_with_defaults_uses_empty_relation_type(
    mock_relation_service,
):
    """Default empty strings are accepted and forwarded as relation_type=''."""
    # Arrange
    mock_relation_service.upsert = mock.AsyncMock(return_value=None)
    db = mock.AsyncMock()

    # Act
    result = await upsert_relationship(db, TEST_NOVEL_ID, "s1", "t1")

    # Assert
    assert result is None
    mock_relation_service.upsert.assert_awaited_once_with(
        db,
        TEST_NOVEL_ID,
        source_id="s1",
        target_id="t1",
        relation_type="",
        description=None,
    )


# ===========================================================================
# merge_candidate_into_entity
# ===========================================================================


@mock.patch("modules.world.entity_facade._dedup_service")
async def test_merge_candidate_into_entity_happy_path_returns_merge_result(
    mock_dedup_service,
):
    """Delegates to dedup service and returns its result transparently."""
    # Arrange
    expected = {"merged": True, "fields_updated": 3}
    mock_dedup_service.merge_candidate_into_entity = mock.AsyncMock(
        return_value=expected
    )
    db = mock.AsyncMock()
    candidate_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())

    # Act
    result = await merge_candidate_into_entity(
        db, TEST_NOVEL_ID, candidate_id, target_id
    )

    # Assert
    assert result == expected
    mock_dedup_service.merge_candidate_into_entity.assert_awaited_once_with(
        db, TEST_NOVEL_ID, candidate_id, target_id
    )


@mock.patch("modules.world.entity_facade._dedup_service")
async def test_merge_candidate_into_entity_service_exception_propagates(
    mock_dedup_service,
):
    """Exceptions from the underlying service bubble up unchanged."""
    # Arrange
    mock_dedup_service.merge_candidate_into_entity = mock.AsyncMock(
        side_effect=ValueError("candidate not found")
    )
    db = mock.AsyncMock()

    # Act & Assert
    with pytest.raises(ValueError, match="candidate not found"):
        await merge_candidate_into_entity(db, TEST_NOVEL_ID, "c1", "t1")


# ===========================================================================
# backfill_entity_embeddings
# ===========================================================================


@mock.patch("modules.world.entity_facade._entity_service")
async def test_backfill_entity_embeddings_happy_path_returns_count(mock_entity_service):
    """Delegates to entity_service.backfill_embeddings with default batch_size."""
    # Arrange
    mock_entity_service.backfill_embeddings = mock.AsyncMock(return_value=7)
    db = mock.AsyncMock()

    # Act
    result = await backfill_entity_embeddings(db, TEST_NOVEL_ID)

    # Assert
    assert result == 7
    mock_entity_service.backfill_embeddings.assert_awaited_once_with(
        db, TEST_NOVEL_ID, batch_size=64
    )


@mock.patch("modules.world.entity_facade._entity_service")
async def test_backfill_entity_embeddings_custom_batch_size_forwards_value(
    mock_entity_service,
):
    """Custom batch_size is passed through to the service."""
    # Arrange
    mock_entity_service.backfill_embeddings = mock.AsyncMock(return_value=0)
    db = mock.AsyncMock()

    # Act
    result = await backfill_entity_embeddings(db, TEST_NOVEL_ID, batch_size=128)

    # Assert
    assert result == 0
    mock_entity_service.backfill_embeddings.assert_awaited_once_with(
        db, TEST_NOVEL_ID, batch_size=128
    )


@mock.patch("modules.world.entity_facade._entity_service")
async def test_backfill_entity_embeddings_service_exception_propagates(
    mock_entity_service,
):
    """Exceptions from the underlying service bubble up unchanged."""
    # Arrange
    mock_entity_service.backfill_embeddings = mock.AsyncMock(
        side_effect=TimeoutError("embedder timeout")
    )
    db = mock.AsyncMock()

    # Act & Assert
    with pytest.raises(TimeoutError, match="embedder timeout"):
        await backfill_entity_embeddings(db, TEST_NOVEL_ID)
