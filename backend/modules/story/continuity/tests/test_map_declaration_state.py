from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.errors import ValidationError
from core.service_keys import WORLD_REQUIRE_MAP_DECLARATION_STATE
from modules.story.continuity.field_provenance import (
    STATE_FIELD_REGISTRY,
    FieldProvenance,
    MapDeclarationIdentityRef,
)
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MemoryService
from modules.world.map_declaration_state import map_declaration_subject_id


class _EventRepository:
    def __init__(self) -> None:
        self.row = None

    async def append_confirmed_scene_event(
        self,
        _db,
        *,
        novel_id,
        scene_id,
        scene_index,
        chapter_index,
        row,
        idempotency_key,
    ):
        self.row = row
        return (
            {
                "id": str(uuid4()),
                "novel_id": str(novel_id),
                "scene_id": str(scene_id),
                "scene_index": scene_index,
                "scene_sequence": 1,
                "chapter_index": chapter_index,
                "sequence": 1,
                **row,
            },
            True,
        )


class _CheckpointRepository:
    def __init__(self) -> None:
        self.superseded = []

    async def supersede_system_from(
        self, _db, novel_id, scene_index, dimensions, *, include_start
    ):
        self.superseded.append((novel_id, scene_index, dimensions, include_start))


class _SnapshotRepository:
    def __init__(self) -> None:
        self.superseded = []

    async def supersede_from(self, _db, novel_id, scene_index, *, include_start):
        self.superseded.append((novel_id, scene_index, include_start))


@pytest.mark.asyncio
async def test_map_declaration_confirmation_revalidates_world_and_records_typed_identity(
    monkeypatch,
):
    novel_id, scene_id, node_id, revision_id = (
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
    )
    subject_id = map_declaration_subject_id(
        novel_id, node_id, "feature", "feature:harbor"
    )
    calls = []
    event_repo = _EventRepository()
    checkpoint_repo = _CheckpointRepository()
    snapshot_repo = _SnapshotRepository()
    scene = SimpleNamespace(
        novel_id=novel_id,
        scene_index=7,
        status="canonical",
        chapter_ids=["4"],
    )

    async def require_map(_db, received_novel_id, **kwargs):
        calls.append((received_novel_id, kwargs))
        return {
            "novel_id": novel_id,
            "node_id": node_id,
            "revision_id": revision_id,
            "declaration_kind": "feature",
            "declaration_id": "feature:harbor",
            "field_key": "effective_status",
            "subject_id": subject_id,
            "label": "地图结构状态",
        }

    def service_get(key):
        if key == WORLD_REQUIRE_MAP_DECLARATION_STATE:
            return require_map
        if key == "story.get_scene_contract":
            return lambda _db, _novel_id, _scene_id: _async_value(scene)
        raise AssertionError(f"unexpected DI key: {key}")

    monkeypatch.setattr("modules.story.continuity.services.get", service_get)
    service = MemoryService(
        event_repo=event_repo,
        scene_checkpoint_repo=checkpoint_repo,
        scene_snapshot_repo=snapshot_repo,
    )
    result = await service.confirm_map_declaration_state(
        object(),
        novel_id,
        scene_id=scene_id,
        node_id=node_id,
        revision_id=revision_id,
        declaration_kind="feature",
        declaration_id="feature:harbor",
        status="inactive",
        idempotency_key="map-state-event-1",
    )

    assert calls == [
        (
            novel_id,
            {
                "node_id": node_id,
                "revision_id": revision_id,
                "declaration_kind": "feature",
                "declaration_id": "feature:harbor",
            },
        )
    ]
    assert event_repo.row["entity_type"] == "map_declaration"
    assert str(event_repo.row["entity_id"]) == subject_id
    assert event_repo.row["source"] == "author_confirmation"
    assert event_repo.row["snapshot_after"]["effective_status"] == "inactive"
    identity = event_repo.row["snapshot_after"]["meta"]["map_declaration_state"]
    assert identity == {
        "contract_version": 1,
        "novel_id": novel_id,
        "node_id": node_id,
        "revision_id": revision_id,
        "subject_id": subject_id,
        "declaration_kind": "feature",
        "declaration_id": "feature:harbor",
        "field_key": "effective_status",
    }
    assert result["map_declaration"]["declaration_id"] == "feature:harbor"
    assert len(checkpoint_repo.superseded) == 1
    assert checkpoint_repo.superseded[0][1:] == (7, ["entities"], True)
    assert len(snapshot_repo.superseded) == 1
    assert snapshot_repo.superseded[0][1:] == (7, True)


@pytest.mark.asyncio
async def test_map_declaration_confirmation_rejects_cross_project_binding(monkeypatch):
    novel_id = str(uuid4())
    other_novel_id = str(uuid4())

    async def require_map(*_args, **_kwargs):
        return {
            "novel_id": other_novel_id,
            "node_id": str(uuid4()),
            "revision_id": str(uuid4()),
            "declaration_kind": "feature",
            "declaration_id": "feature:harbor",
            "field_key": "effective_status",
            "subject_id": str(uuid4()),
            "label": "地图结构状态",
        }

    monkeypatch.setattr(
        "modules.story.continuity.services.get",
        lambda key: require_map,
    )
    service = MemoryService(event_repo=_EventRepository())
    with pytest.raises(ValidationError, match="binding does not match"):
        await service.confirm_map_declaration_state(
            object(),
            novel_id,
            scene_id=str(uuid4()),
            node_id=str(uuid4()),
            revision_id=str(uuid4()),
            declaration_kind="feature",
            declaration_id="feature:harbor",
            status="active",
            idempotency_key="map-state-event-2",
        )


def test_map_declaration_field_keeps_identity_provenance_and_existing_view_gates():
    novel_id, node_id, revision_id, subject_id = [str(uuid4()) for _ in range(4)]
    assert ("map_declaration", "effective_status") in STATE_FIELD_REGISTRY
    assert (
        STATE_FIELD_REGISTRY[("map_declaration", "effective_status")].deterministic_check
        is False
    )
    identity = MapDeclarationIdentityRef(
        contract_version=1,
        novel_id=novel_id,
        node_id=node_id,
        revision_id=revision_id,
        subject_id=subject_id,
        declaration_kind="feature",
        declaration_id="feature:harbor",
        field_key="effective_status",
    )
    provenance = FieldProvenance(
        field_key="effective_status",
        dimension="entities",
        object_type="map_declaration",
        event_id=str(uuid4()),
        subject_ref=subject_id,
        version=0,
        recorded_at_sequence=2049,
        author_confirmed=True,
        identity_ref=identity,
    )
    checkpoint = SimpleNamespace(
        state_json={
            "entities": {subject_id: {"effective_status": "inactive"}},
            "_field_provenance": [provenance.model_dump(mode="json")],
        },
        id="checkpoint-map-state",
        confirmed=False,
        source="system_generated",
    )
    entry = next(
        item
        for item in SceneStateViewService._entries_for("entities", checkpoint)
        if item.field == "effective_status"
    )
    assert entry.confidence == "confirmed"
    assert entry.source["provenance"]["identity_ref"]["declaration_id"] == (
        "feature:harbor"
    )
    view_service = SceneStateViewService()
    author, _, _ = view_service._filter_entries(
        "entities",
        [entry],
        kind="author",
        target_id=None,
        knowledge_grants={},
        reveal_cache={},
    )
    character, _, _ = view_service._filter_entries(
        "entities",
        [entry],
        kind="character",
        target_id=str(uuid4()),
        knowledge_grants={},
        reveal_cache={},
    )
    reader, _, _ = view_service._filter_entries(
        "entities",
        [entry],
        kind="reader",
        target_id=None,
        knowledge_grants={},
        reveal_cache={},
    )
    assert author == [entry]
    assert character == []
    assert reader == []

    machine_event = SimpleNamespace(
        event_type="entity_created",
        entity_id=subject_id,
        entity_type="map_declaration",
        source="evolution",
        snapshot_after={
            "effective_status": "active",
            "meta": {
                "author_confirmed": True,
                "author_confirmed_state": True,
                "map_declaration_state": identity.model_dump(mode="json"),
            },
        },
    )
    assigned = SceneMemoryProjectionService._assigned_motif_fields(
        {"entities": {subject_id: {"effective_status": "active"}}},
        "entities",
        machine_event,
    )
    assert assigned == ()


async def _async_value(value):
    return value
