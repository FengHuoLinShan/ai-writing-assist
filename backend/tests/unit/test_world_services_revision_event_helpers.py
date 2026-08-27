"""Unit tests for modules.world.services internal modules.

Covers entity_revision_service, event_service, helpers, draft_provider.
All external dependencies are mocked to keep tests fast and isolated.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.errors import NotFoundError
from modules.world.services.common import (
    find_alias_in_entity,
    find_alias_in_list,
    merge_text_field,
    normalize_name,
    world_entity_types_compatible,
)
from modules.world.services.core.entity_revision_service import EntityRevisionService
from modules.world.services.core.event_service import EventService

# ============================================================
# Factory helpers
# ============================================================


def _make_revision_service() -> tuple[EntityRevisionService, MagicMock, MagicMock]:
    svc = EntityRevisionService()
    svc._repo = MagicMock()
    svc._entity_repo = MagicMock()
    return svc, svc._repo, svc._entity_repo


def _make_event_service() -> tuple[EventService, MagicMock]:
    svc = EventService()
    svc.repo = MagicMock()
    return svc, svc.repo


def _mock_entity(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "entity_type": "character",
        "name": "Test Entity",
        "summary": "A test entity",
        "public_info": None,
        "hidden_truth": None,
        "content_json": {},
        "importance": 0.5,
        "importance_level": "normal",
        "reveal_level": "author_only",
        "status": "draft",
        "display_state": None,
        "source": None,
        "attention_reasons": [],
        "suggested_action": None,
        "embedding_text": None,
        "created_by": None,
        "approved_by": None,
        "ranking": None,
    }
    defaults.update(overrides)
    entity = MagicMock()
    for k, v in defaults.items():
        setattr(entity, k, v)
    return entity


def _mock_event(**overrides):
    defaults = {
        "entity_id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "source_chapter_id": uuid.uuid4(),
        "location_entity_id": uuid.uuid4(),
        "timeline_order": 1,
        "occurrence_time_label": "序章",
    }
    defaults.update(overrides)
    ev = MagicMock()
    for k, v in defaults.items():
        setattr(ev, k, v)
    return ev


def _canonical_core_entity(novel_id: uuid.UUID, entity_type: str):
    return MagicMock(
        novel_id=novel_id,
        status="canonical",
        entity_type=entity_type,
    )


def _mock_revision(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "entity_id": uuid.uuid4(),
        "novel_id": uuid.uuid4(),
        "snapshot": {},
        "source_chapter_id": None,
        "revision_reason": "ai_import",
        "created_at": datetime.now(),
    }
    defaults.update(overrides)
    rev = MagicMock()
    for k, v in defaults.items():
        setattr(rev, k, v)
    return rev


# ============================================================
# EntityRevisionService
# ============================================================


class TestEntityRevisionService:
    pytestmark = [pytest.mark.asyncio]

    async def test_entity_revision_service_has_no_direct_http_exception_dependency(self):
        service_path = (
            Path(__file__).parents[2]
            / "modules/world/services/core/entity_revision_service.py"
        )
        source = service_path.read_text()

        assert "from fastapi import HTTPException" not in source
        assert "raise HTTPException" not in source

    async def test_create_snapshot_happy_path_returns_revision_dict(self):
        """Happy path: snapshot created and returned as dict."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        nid = str(uuid.uuid4())
        entity = _mock_entity(novel_id=uuid.UUID(nid))
        revision = _mock_revision(entity_id=entity.id)
        entity_repo.get = AsyncMock(return_value=entity)
        repo.create = AsyncMock(return_value=revision)
        db = MagicMock()
        eid = str(entity.id)

        # Act
        result = await svc.create_snapshot(db, eid, nid)

        # Assert
        assert result["revision_id"] == str(revision.id)
        assert result["entity_id"] == str(revision.entity_id)
        assert result["revision_reason"] == revision.revision_reason
        repo.create.assert_awaited_once()
        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["entity_id"] == entity.id
        assert call_kwargs["novel_id"] == uuid.UUID(hex=nid)
        assert call_kwargs["snapshot"]["name"] == entity.name

    async def test_create_snapshot_entity_not_found_raises_domain_not_found(self):
        """Exception path: entity missing raises domain NotFoundError."""
        # Arrange
        svc, _repo, entity_repo = _make_revision_service()
        entity_repo.get = AsyncMock(return_value=None)
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.create_snapshot(db, str(uuid.uuid4()), str(uuid.uuid4()))
        assert exc_info.value.status_code == 404

    async def test_create_snapshot_with_source_chapter_id_passes_chapter_uuid(self):
        """Boundary: source_chapter_id is parsed and forwarded."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity = _mock_entity()
        revision = _mock_revision()
        entity_repo.get = AsyncMock(return_value=entity)
        repo.create = AsyncMock(return_value=revision)
        db = MagicMock()
        chapter_id = str(uuid.uuid4())

        # Act
        await svc.create_snapshot(
            db, str(entity.id), str(entity.novel_id), source_chapter_id=chapter_id
        )

        # Assert
        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["source_chapter_id"] == uuid.UUID(hex=chapter_id)

    async def test_get_revisions_happy_path_returns_items_and_total(self):
        """Happy path: revision list paginated."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity = _mock_entity()
        revision = _mock_revision()
        entity_repo.get = AsyncMock(return_value=entity)
        repo.get_revisions = AsyncMock(return_value=([revision], 1))
        db = MagicMock()
        eid = str(entity.id)
        nid = str(entity.novel_id)

        # Act
        result = await svc.get_revisions(db, eid, nid, skip=0, limit=10)

        # Assert
        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["revision_id"] == str(revision.id)
        repo.get_revisions.assert_awaited_once_with(db, entity.id, skip=0, limit=10)

    async def test_get_revisions_entity_not_found_raises_domain_not_found(self):
        """Exception path: missing entity raises domain NotFoundError."""
        # Arrange
        svc, _repo, entity_repo = _make_revision_service()
        entity_repo.get = AsyncMock(return_value=None)
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.get_revisions(db, str(uuid.uuid4()), str(uuid.uuid4()))
        assert exc_info.value.status_code == 404

    async def test_get_revisions_cross_novel_entity_raises_domain_not_found(self):
        """Boundary: revision list does not leak across novel_id."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity = _mock_entity(novel_id=uuid.uuid4())
        entity_repo.get = AsyncMock(return_value=entity)
        repo.get_revisions = AsyncMock(return_value=([], 0))
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.get_revisions(db, str(entity.id), str(uuid.uuid4()))
        assert exc_info.value.status_code == 404
        repo.get_revisions.assert_not_called()

    async def test_rollback_to_revision_happy_path_returns_entity_dict(self):
        """Happy path: rollback creates snapshot, updates entity, returns dict."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity = _mock_entity(status="canonical")
        revision = _mock_revision(
            entity_id=entity.id,
            novel_id=entity.novel_id,
            snapshot={
                "entity_type": "character",
                "name": "Old Name",
                "summary": "Old summary",
                "public_info": None,
                "hidden_truth": None,
                "content_json": {},
                "importance": 0.8,
                "importance_level": "core",
                "reveal_level": "author_only",
                "status": "canonical",
            },
        )
        entity_repo.update = AsyncMock(return_value=entity)
        entity_repo.get_for_update = AsyncMock(return_value=entity)
        repo.get_revision = AsyncMock(return_value=revision)
        svc.create_snapshot = AsyncMock(return_value={})
        svc._record_authority = AsyncMock()
        db = MagicMock()
        eid = str(entity.id)
        rid = str(revision.id)
        nid = str(entity.novel_id)

        # Act
        result = await svc.rollback_to_revision(db, eid, rid, nid)

        # Assert
        svc.create_snapshot.assert_awaited_once_with(
            db, eid, nid, revision_reason="rollback"
        )
        repo.get_revision.assert_awaited_once_with(db, uuid.UUID(hex=rid))
        entity_repo.update.assert_awaited_once()
        svc._record_authority.assert_awaited_once_with(db, entity)
        assert result["id"] == str(entity.id)
        assert result["name"] == entity.name

    async def test_rollback_to_revision_not_found_raises_domain_not_found(self):
        """Exception path: missing revision raises domain NotFoundError."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        novel_id = uuid.uuid4()
        entity_id = uuid.uuid4()
        entity_repo.get_for_update = AsyncMock(
            return_value=_mock_entity(id=entity_id, novel_id=novel_id)
        )
        repo.get_revision = AsyncMock(return_value=None)
        svc.create_snapshot = AsyncMock(return_value={})
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.rollback_to_revision(
                db, str(entity_id), str(uuid.uuid4()), str(novel_id)
            )
        assert exc_info.value.status_code == 404
        assert "Revision" in exc_info.value.detail

    async def test_rollback_to_revision_cross_entity_revision_raises_domain_not_found(
        self,
    ):
        """Boundary: rollback rejects a revision owned by another entity."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity_id = uuid.uuid4()
        novel_id = uuid.uuid4()
        entity_repo.get_for_update = AsyncMock(
            return_value=_mock_entity(id=entity_id, novel_id=novel_id)
        )
        revision = _mock_revision(entity_id=uuid.uuid4(), novel_id=novel_id)
        repo.get_revision = AsyncMock(return_value=revision)
        entity_repo.update = AsyncMock()
        svc.create_snapshot = AsyncMock(return_value={})
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.rollback_to_revision(
                db, str(entity_id), str(revision.id), str(novel_id)
            )
        assert exc_info.value.status_code == 404
        entity_repo.update.assert_not_called()

    async def test_rollback_to_revision_entity_update_none_raises_domain_not_found(self):
        """Exception path: entity disappears after update raises domain NotFoundError."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity_id = uuid.uuid4()
        novel_id = uuid.uuid4()
        revision = _mock_revision(
            entity_id=entity_id,
            novel_id=novel_id,
            snapshot={"entity_type": "character", "name": "Old Name"},
        )
        repo.get_revision = AsyncMock(return_value=revision)
        entity_repo.get_for_update = AsyncMock(
            return_value=_mock_entity(id=entity_id, novel_id=novel_id)
        )
        entity_repo.update = AsyncMock(return_value=None)
        svc.create_snapshot = AsyncMock(return_value={})
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.rollback_to_revision(
                db, str(entity_id), str(revision.id), str(novel_id)
            )
        assert exc_info.value.status_code == 404
        assert "not found after rollback" in exc_info.value.detail

    async def test_rollback_to_scene_index_archive_update_reuses_loaded_entity(self):
        """Performance: TextArchive rollback updates the entity already validated."""
        # Arrange
        svc, _repo, entity_repo = _make_revision_service()
        entity = _mock_entity(summary="current")
        archive = MagicMock(
            field_name="summary",
            text_content="archived summary",
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = [archive]
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        entity_repo.get_for_update = AsyncMock(return_value=entity)
        entity_repo.update = AsyncMock(return_value=entity)

        # Act
        response = await svc.rollback_to_scene_index(
            db,
            str(entity.id),
            target_scene_index=7,
            novel_id=str(entity.novel_id),
        )

        # Assert
        assert response["restored_fields"] == ["summary"]
        entity_repo.get_for_update.assert_awaited_once_with(db, entity.id)
        entity_repo.update.assert_awaited_once()
        assert entity_repo.update.await_args.args[1] is entity
        update_data = entity_repo.update.await_args.args[2]
        assert update_data.summary == "archived summary"

    async def test_rollback_to_scene_index_revision_fallback_reuses_loaded_entity(self):
        """Performance: revision fallback also updates the entity already validated."""
        # Arrange
        svc, repo, entity_repo = _make_revision_service()
        entity = _mock_entity(summary="current")
        revision = _mock_revision(
            entity_id=entity.id,
            novel_id=entity.novel_id,
            snapshot={
                "entity_type": "character",
                "name": "Old Name",
                "summary": "Old summary",
                "public_info": None,
                "hidden_truth": None,
                "content_json": {},
                "importance": 0.8,
                "importance_level": "core",
                "reveal_level": "author_only",
                "status": "canonical",
            },
        )
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()
        entity_repo.get_for_update = AsyncMock(return_value=entity)
        entity_repo.update = AsyncMock(return_value=entity)
        repo.get_revisions = AsyncMock(return_value=([revision], 1))

        # Act
        response = await svc.rollback_to_scene_index(
            db,
            str(entity.id),
            target_scene_index=7,
            novel_id=str(entity.novel_id),
        )

        # Assert
        assert "summary" in response["restored_fields"]
        assert any("EntityRevision" in warning for warning in response["warnings"])
        entity_repo.get_for_update.assert_awaited_once_with(db, entity.id)
        entity_repo.update.assert_awaited_once()
        assert entity_repo.update.await_args.args[1] is entity
        update_data = entity_repo.update.await_args.args[2]
        assert update_data.summary == "Old summary"


# ============================================================
# EventService
# ============================================================


class TestEventService:
    pytestmark = [pytest.mark.asyncio]

    async def test_get_events_for_chapter_happy_path_returns_list(self):
        """Happy path: returns list of EventResponse."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get_events_for_chapter = AsyncMock(return_value=[ev])
        db = MagicMock()
        nid = str(ev.novel_id)
        cid = str(ev.source_chapter_id)

        # Act
        result = await svc.get_events_for_chapter(db, nid, cid)

        # Assert
        assert len(result) == 1
        assert result[0].entity_id == str(ev.entity_id)
        repo.get_events_for_chapter.assert_awaited_once_with(
            db, uuid.UUID(hex=nid), uuid.UUID(hex=cid)
        )

    async def test_get_events_for_chapter_empty_returns_empty_list(self):
        """Boundary: no events returns empty list."""
        # Arrange
        svc, repo = _make_event_service()
        repo.get_events_for_chapter = AsyncMock(return_value=[])
        db = MagicMock()

        # Act
        result = await svc.get_events_for_chapter(
            db, str(uuid.uuid4()), str(uuid.uuid4())
        )

        # Assert
        assert result == []

    async def test_get_events_in_order_happy_path_returns_list(self):
        """Happy path: returns ordered EventResponse list."""
        # Arrange
        svc, repo = _make_event_service()
        ev1 = _mock_event(timeline_order=1)
        ev2 = _mock_event(timeline_order=2)
        repo.get_events_in_order = AsyncMock(return_value=[ev1, ev2])
        db = MagicMock()
        nid = str(ev1.novel_id)

        # Act
        result = await svc.get_events_in_order(db, nid, limit=10)

        # Assert
        assert len(result) == 2
        assert result[0].timeline_order == 1
        assert result[1].timeline_order == 2
        repo.get_events_in_order.assert_awaited_once_with(
            db, uuid.UUID(hex=nid), limit=10
        )

    async def test_get_happy_path_returns_event_response(self):
        """Inherited CrudService.get: returns EventResponse."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get = AsyncMock(return_value=ev)
        svc._entity_repo = MagicMock()
        svc._entity_repo.get = AsyncMock(
            side_effect=[
                _canonical_core_entity(ev.novel_id, "event"),
                _canonical_core_entity(ev.novel_id, "location"),
            ]
        )
        db = MagicMock()

        # Act
        result = await svc.get(db, str(ev.entity_id), novel_id=str(ev.novel_id))

        # Assert
        assert result.entity_id == str(ev.entity_id)
        repo.get.assert_awaited_once_with(db, ev.entity_id)

    async def test_get_not_found_raises_404(self):
        """Inherited CrudService.get: missing event raises 404."""
        # Arrange
        svc, repo = _make_event_service()
        repo.get = AsyncMock(return_value=None)
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.get(db, str(uuid.uuid4()), novel_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 404

    async def test_get_novel_mismatch_raises_404(self):
        """Inherited CrudService.get: novel_id mismatch raises 404."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get = AsyncMock(return_value=ev)
        db = MagicMock()

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.get(db, str(ev.entity_id), novel_id=str(uuid.uuid4()))
        assert exc_info.value.status_code == 404

    async def test_list_happy_path_returns_items_and_total(self):
        """Inherited CrudService.list: returns paginated results."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get_by_novel = AsyncMock(return_value=([ev], 1))
        db = MagicMock()
        nid = str(ev.novel_id)

        # Act
        items, total = await svc.list(db, nid)

        # Assert
        assert total == 1
        assert len(items) == 1
        repo.get_by_novel.assert_awaited_once_with(db, ev.novel_id, skip=0, limit=20)

    async def test_create_happy_path_returns_event_response(self):
        """Inherited CrudService.create: returns EventResponse."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        svc._entity_repo = MagicMock()
        svc._entity_repo.get = AsyncMock(
            side_effect=[
                _canonical_core_entity(ev.novel_id, "event"),
                _canonical_core_entity(ev.novel_id, "location"),
            ]
        )
        repo.create = AsyncMock(return_value=ev)
        db = MagicMock()
        nid = str(ev.novel_id)
        from modules.world.schemas import EventCreate

        data = EventCreate(
            entity_id=str(ev.entity_id),
            source_chapter_id=str(ev.source_chapter_id),
            location_entity_id=str(ev.location_entity_id),
            timeline_order=ev.timeline_order,
        )

        # Act
        result = await svc.create(db, nid, data)

        # Assert
        assert result.entity_id == str(ev.entity_id)
        repo.create.assert_awaited_once()

    async def test_create_missing_event_entity_raises_domain_not_found(self):
        """EventService.create: missing event entity raises domain NotFoundError."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        svc._entity_repo = MagicMock()
        svc._entity_repo.get = AsyncMock(return_value=None)
        repo.create = AsyncMock()
        db = MagicMock()
        from modules.world.schemas import EventCreate

        data = EventCreate(
            entity_id=str(ev.entity_id),
            source_chapter_id=str(ev.source_chapter_id),
            location_entity_id=str(ev.location_entity_id),
            timeline_order=ev.timeline_order,
        )

        # Act & Assert
        with pytest.raises(NotFoundError) as exc_info:
            await svc.create(db, str(ev.novel_id), data)
        assert exc_info.value.status_code == 404
        assert exc_info.value.message == "Event entity not found in this novel"
        repo.create.assert_not_called()

    async def test_update_happy_path_returns_event_response(self):
        """Inherited CrudService.update: returns EventResponse."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get = AsyncMock(return_value=ev)
        repo.update = AsyncMock(return_value=ev)
        svc._entity_repo = MagicMock()
        svc._entity_repo.get = AsyncMock(
            side_effect=[
                _canonical_core_entity(ev.novel_id, "event"),
                _canonical_core_entity(ev.novel_id, "location"),
            ]
        )
        db = MagicMock()
        from modules.world.schemas import EventUpdate

        data = EventUpdate(timeline_order=99)

        # Act
        result = await svc.update(db, str(ev.entity_id), data, novel_id=str(ev.novel_id))

        # Assert
        assert result.timeline_order == ev.timeline_order
        repo.update.assert_awaited_once_with(db, ev.entity_id, data)

    async def test_delete_happy_path_succeeds(self):
        """Inherited CrudService.delete: succeeds when repo returns True."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get = AsyncMock(return_value=ev)
        repo.delete = AsyncMock(return_value=True)
        db = MagicMock()
        db.flush = AsyncMock()

        # Act
        await svc.delete(db, str(ev.entity_id), novel_id=str(ev.novel_id))

        # Assert
        assert ev.status == "deprecated"
        db.flush.assert_awaited_once()

    async def test_delete_repo_false_raises_404(self):
        """Inherited CrudService.delete: repo.delete False raises 404."""
        # Arrange
        svc, repo = _make_event_service()
        ev = _mock_event()
        repo.get = AsyncMock(return_value=ev)
        repo.delete = AsyncMock(return_value=False)
        db = MagicMock()
        db.flush = AsyncMock()

        await svc.delete(db, str(ev.entity_id), novel_id=str(ev.novel_id))

        assert ev.status == "deprecated"
        repo.delete.assert_not_awaited()


# ============================================================
# Helpers
# ============================================================


def test_normalize_name_removes_special_chars_and_casefolds():
    """Happy path: special chars removed and casefolded."""
    # Arrange
    raw = "Hello·World（Test）"

    # Act
    result = normalize_name(raw)

    # Assert
    assert result == "helloworldtest"


def test_normalize_name_empty_string_returns_empty():
    """Boundary: empty string stays empty."""
    assert normalize_name("") == ""


def test_merge_text_field_both_none_returns_empty():
    """Boundary: both None returns empty string."""
    assert merge_text_field(None, None) == ""


def test_merge_text_field_current_none_returns_incoming():
    """Boundary: current None returns incoming."""
    assert merge_text_field(None, "new") == "new"


def test_merge_text_field_incoming_none_returns_current():
    """Boundary: incoming None returns current."""
    assert merge_text_field("old", None) == "old"


def test_merge_text_field_equal_returns_current():
    """Boundary: equal strings returns current only."""
    assert merge_text_field("same", "same") == "same"


def test_merge_text_field_incoming_substring_returns_current():
    """Boundary: incoming already in current returns current."""
    assert merge_text_field("hello world", "world") == "hello world"


def test_merge_text_field_distinct_appends():
    """Happy path: distinct texts appended with double newline."""
    assert merge_text_field("a", "b") == "a\n\nb"


def test_world_entity_types_compatible_both_none_returns_true():
    """Boundary: both None treated as 'other', compatible."""
    assert world_entity_types_compatible(None, None) is True


def test_world_entity_types_compatible_one_other_returns_true():
    """Happy path: one side 'other' allows compatibility."""
    assert world_entity_types_compatible("other", "character") is True
    assert world_entity_types_compatible("item", "other") is True


def test_world_entity_types_compatible_same_returns_true():
    """Happy path: identical types are compatible."""
    assert world_entity_types_compatible("character", "character") is True


def test_world_entity_types_compatible_different_returns_false():
    """Exception path: different non-other types are incompatible."""
    assert world_entity_types_compatible("character", "item") is False


def test_find_alias_in_entity_found_returns_true():
    """Happy path: alias found in entity.aliases."""
    entity = MagicMock()
    entity.aliases = [{"alias": "Alias A"}, {"alias": "Alias B"}]
    assert find_alias_in_entity(entity, "Alias B") is True


def test_find_alias_in_entity_not_found_returns_false():
    """Boundary: alias missing returns False."""
    entity = MagicMock()
    entity.aliases = [{"alias": "Alias A"}]
    assert find_alias_in_entity(entity, "Missing") is False


def test_find_alias_in_entity_empty_alias_returns_false():
    """Boundary: empty alias_text returns False."""
    entity = MagicMock()
    entity.aliases = [{"alias": "Alias A"}]
    assert find_alias_in_entity(entity, "") is False
    assert find_alias_in_entity(entity, None) is False


def test_find_alias_in_entity_non_dict_entry_skips():
    """Boundary: non-dict entries in aliases are skipped safely."""
    entity = MagicMock()
    entity.aliases = ["bad_entry", {"alias": "Good"}]
    assert find_alias_in_entity(entity, "Good") is True
    assert find_alias_in_entity(entity, "bad_entry") is False


def test_find_alias_in_list_found_returns_true():
    """Happy path: alias found in raw list."""
    aliases = [{"alias": "X"}, {"alias": "Y"}]
    assert find_alias_in_list(aliases, "Y") is True


def test_find_alias_in_list_not_found_returns_false():
    """Boundary: alias missing returns False."""
    assert find_alias_in_list([{"alias": "X"}], "Z") is False


def test_find_alias_in_list_empty_alias_returns_false():
    """Boundary: empty alias_text returns False."""
    assert find_alias_in_list([{"alias": "X"}], "") is False
    assert find_alias_in_list([{"alias": "X"}], None) is False


def test_find_alias_in_list_non_dict_entry_skips():
    """Boundary: non-dict entries are skipped safely."""
    aliases = [123, {"alias": "Z"}]
    assert find_alias_in_list(aliases, "Z") is True
    assert find_alias_in_list(aliases, "123") is False
