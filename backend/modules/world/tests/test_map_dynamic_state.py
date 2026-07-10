from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import SceneCreate
from modules.outline.services import SceneService
from modules.world.map_repositories import (
    MapLocationBindingRepository,
    MapMarkerRepository,
)
from modules.world.services.map.map_state_assembler import MapStateAssembler
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_dynamic_state_returns_only_scene_dynamic_layers(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await SceneService().create(
        db_session,
        novel_id,
        SceneCreate(scene_index=1, title="暗巷追逐", chapter_ids=["1"]),
    )
    other_scene = await SceneService().create(
        db_session,
        novel_id,
        SceneCreate(scene_index=2, title="城门回声", chapter_ids=["2"]),
    )
    location = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="暗巷",
        status="canonical",
    )
    candidate_location = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="临时据点",
        status="candidate",
    )
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    candidate_character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="疑似目击者",
        status="candidate",
    )
    faction = await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name="巡夜司",
        status="canonical",
    )
    await db_session.flush()

    map_resp = await async_client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={"name": "九州", "map_type": "world", "grid_width": 6, "grid_height": 6},
    )
    assert map_resp.status_code == 201, map_resp.text
    map_id = map_resp.json()["id"]

    await MapLocationBindingRepository().bulk_create(
        db_session,
        uuid.UUID(hex=novel_id),
        uuid.UUID(map_id),
        candidate_location.id,
        [{"hex_q": 1, "hex_r": 1, "is_center": True}],
    )
    canonical_binding_resp = await async_client.post(
        f"/api/world/maps/{map_id}/location-bindings",
        params={"novel_id": novel_id},
        json={
            "location_entity_id": str(location.id),
            "hexes": [{"hex_q": 2, "hex_r": 2, "is_center": True}],
        },
    )
    assert canonical_binding_resp.status_code == 201, canonical_binding_resp.text

    marker_resp = await async_client.post(
        f"/api/world/maps/{map_id}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": str(character.id),
            "marker_type": "character",
            "hex_q": 2,
            "hex_r": 2,
            "start_scene_id": scene.id,
            "start_scene_index": 1,
        },
    )
    assert marker_resp.status_code == 201, marker_resp.text
    await MapMarkerRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        uuid.UUID(map_id),
        {
            "entity_id": candidate_character.id,
            "marker_type": "character",
            "hex_q": 3,
            "hex_r": 3,
            "start_scene_id": uuid.UUID(str(scene.id)),
            "start_scene_index": 1,
        },
    )
    other_marker_resp = await async_client.post(
        f"/api/world/maps/{map_id}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": str(character.id),
            "marker_type": "character",
            "hex_q": 4,
            "hex_r": 4,
            "start_scene_id": other_scene.id,
            "start_scene_index": 2,
        },
    )
    assert other_marker_resp.status_code == 201, other_marker_resp.text

    territory_resp = await async_client.post(
        f"/api/world/maps/{map_id}/territories",
        params={"novel_id": novel_id},
        json={
            "faction_entity_id": str(faction.id),
            "hexes": [{"hex_q": 2, "hex_r": 2}],
        },
    )
    assert territory_resp.status_code == 201, territory_resp.text

    response = await async_client.get(
        f"/api/world/maps/{map_id}/state/dynamic",
        params={"novel_id": novel_id, "scene_id": scene.id},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "markers",
        "territories",
        "candidate_location_bindings",
        "candidate_markers",
        "candidate_territories",
        "scene",
    }
    assert body["scene"]["id"] == scene.id
    assert [marker["entity_id"] for marker in body["markers"]] == [str(character.id)]
    assert body["candidate_markers"][0]["entity_id"] == str(candidate_character.id)
    assert body["candidate_location_bindings"][0]["location_entity_id"] == str(
        candidate_location.id
    )
    assert body["territories"][0]["faction_entity_id"] == str(faction.id)


@pytest.mark.asyncio
async def test_dynamic_state_uses_status_scoped_queries() -> None:
    """Scene refresh should not reload every binding/territory on the map."""
    calls: list[tuple[str, tuple[str, ...]]] = []

    class _Ctx:
        async def require_map(self, db, novel_id, map_id):
            return object()

    class _BindingRepo:
        async def get_by_map(self, *args, **kwargs):
            raise AssertionError("dynamic state must not load all bindings")

        async def get_by_map_for_entity_statuses(self, *args, statuses, **kwargs):
            calls.append(("bindings", tuple(statuses)))
            return []

    class _MarkerRepo:
        async def get_by_map_and_scene(self, *args, **kwargs):
            raise AssertionError("dynamic state must not load unsplit markers")

        async def get_by_map_and_scene_for_entity_statuses(
            self,
            *args,
            statuses,
            **kwargs,
        ):
            calls.append(("markers", tuple(statuses)))
            return []

    class _TerritoryRepo:
        async def get_by_map(self, *args, **kwargs):
            raise AssertionError("dynamic state must not load all territories")

        async def get_by_map_for_entity_statuses(self, *args, statuses, **kwargs):
            calls.append(("territories", tuple(statuses)))
            return []

    class _EntityRepo:
        async def get_by_ids(self, *args, **kwargs):
            raise AssertionError("dynamic state should not split full rows in memory")

    assembler = MapStateAssembler(
        binding_repo=_BindingRepo(),  # type: ignore[arg-type]
        marker_repo=_MarkerRepo(),  # type: ignore[arg-type]
        territory_repo=_TerritoryRepo(),  # type: ignore[arg-type]
        entity_repo=_EntityRepo(),  # type: ignore[arg-type]
        ctx=_Ctx(),  # type: ignore[arg-type]
    )

    response = await assembler.assemble_dynamic(
        object(),  # type: ignore[arg-type]
        uuid.uuid4().hex,
        uuid.uuid4().hex,
    )

    assert response.markers == []
    assert response.territories == []
    assert response.candidate_location_bindings == []
    assert calls == [
        ("bindings", ("draft", "candidate")),
        ("markers", ("canonical",)),
        ("markers", ("draft", "candidate")),
        ("territories", ("canonical",)),
        ("territories", ("draft", "candidate")),
    ]
