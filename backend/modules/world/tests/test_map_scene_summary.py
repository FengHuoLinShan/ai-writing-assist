"""Map Scene summary API tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate
from modules.world.map_facade import summarize_scene_map_for_writing
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapLocationBindingCreate,
    MapMarkerCreate,
    MapTerritoryCreate,
    TerritoryHex,
)
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
    MapMarkerService,
    MapTerritoryService,
)
from modules.world.tests.helpers import _create_entity, _create_project


async def _create_scene(
    db_session: AsyncSession,
    novel_id: str,
    *,
    scene_index: int = 7,
    title: str = "东门封锁",
):
    return await SceneRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        SceneCreate(scene_index=scene_index, title=title, status="canonical"),
    )


@pytest.mark.asyncio
async def test_scene_summary_static_route_is_not_captured_by_map_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scene_id"] == str(scene.id)
    assert body["open_target"]["mode"] == "recent"


@pytest.mark.asyncio
async def test_scene_summary_without_markers_returns_empty_summary_and_fallback(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["primary_location"] is None
    assert body["characters"] == []
    assert body["events"] == []
    assert body["factions"] == []
    assert body["open_target"] == {
        "mode": "recent",
        "map_id": None,
        "scene_id": str(scene.id),
        "focus_entity_id": None,
        "fallback_reason": "scene_without_map",
        "fallback_message": "当前 Scene 暂无地图上下文，已回退到最近地图",
    }
    assert body["warnings"][0]["code"] == "scene_without_map_context"
    assert body["warnings"][0]["message"] == "当前 Scene 暂无地图上下文"


@pytest.mark.asyncio
async def test_scene_summary_ignores_candidate_markers_for_default_context(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    candidate_character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="待确认人物",
        status="candidate",
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_resp.id,
        MapMarkerCreate(
            entity_id=str(candidate_character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="待确认人物",
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["characters"] == []
    assert body["open_target"]["mode"] == "recent"
    assert body["warnings"][0]["code"] == "scene_without_map_context"


@pytest.mark.asyncio
async def test_writing_map_facade_excludes_candidate_markers_by_default(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    candidate_character = await _create_entity(
        db_session,
        nid,
        entity_type="character",
        name="待确认人物",
        status="candidate",
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_resp.id,
        MapMarkerCreate(
            entity_id=str(candidate_character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="待确认人物",
        ),
    )

    summary = await summarize_scene_map_for_writing(
        db_session,
        nid,
        str(scene.id),
    )

    assert summary["characters"] == []
    assert summary["open_target"]["mode"] == "recent"


@pytest.mark.asyncio
async def test_scene_summary_with_marker_but_no_bound_location_warns_missing_location(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    character = await _create_entity(
        db_session, nid, entity_type="character", name="沈砚"
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_resp.id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="沈砚",
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["open_target"]["mode"] == "map"
    assert body["primary_location"] is None
    assert body["warnings"][0]["code"] == "scene_without_location"
    assert body["warnings"][0]["message"] == "当前 Scene 暂无主地点"


@pytest.mark.asyncio
async def test_scene_summary_returns_location_characters_events_and_factions(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)

    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    map_id = map_resp.id

    location = await _create_entity(
        db_session, nid, entity_type="location", name="洛阳外城"
    )
    character = await _create_entity(
        db_session, nid, entity_type="character", name="沈砚"
    )
    event = await _create_entity(db_session, nid, entity_type="event", name="东门封锁")
    faction = await _create_entity(
        db_session, nid, entity_type="organization", name="北府"
    )

    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        map_id,
        MapLocationBindingCreate(
            location_entity_id=str(location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="沈砚",
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        map_id,
        MapMarkerCreate(
            entity_id=str(event.id),
            marker_type="event",
            hex_q=2,
            hex_r=1,
            start_scene_id=str(scene.id),
            start_scene_index=scene.scene_index,
            label="封锁",
        ),
    )
    await MapTerritoryService().create(
        db_session,
        nid,
        map_id,
        MapTerritoryCreate(
            faction_entity_id=str(faction.id),
            hexes=[TerritoryHex(hex_q=1, hex_r=1)],
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["open_target"]["mode"] == "map"
    assert body["open_target"]["map_id"] == map_id
    assert body["primary_location"]["name"] == "洛阳外城"
    assert body["primary_location"]["hex_q"] == 1
    assert [item["name"] for item in body["characters"]] == ["沈砚"]
    assert [item["name"] for item in body["events"]] == ["东门封锁"]
    assert [item["name"] for item in body["factions"]] == ["北府"]
    assert body["crises"] == []
    assert body["risks"] == []


@pytest.mark.asyncio
async def test_scene_summary_exposes_crises_and_risks_from_map_observations(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    scene = await _create_scene(db_session, nid)
    map_resp = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="九州世界", map_type="world", grid_width=5, grid_height=5),
    )
    location = await _create_entity(
        db_session, nid, entity_type="location", name="洛阳外城"
    )
    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        map_resp.id,
        MapLocationBindingCreate(
            location_entity_id=str(location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    crisis_resp = await async_client.post(
        f"/api/world/maps/{map_resp.id}/observations",
        params={"novel_id": nid},
        json={
            "scene_id": str(scene.id),
            "target_entity_type": "event",
            "target_name": "东门封锁",
            "dynamic_type": "crisis",
            "confidence": 0.39,
            "scene_index": scene.scene_index,
            "source_ref": {"source": "deep_import"},
        },
    )
    assert crisis_resp.status_code == 201, crisis_resp.text

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [item["name"] for item in body["crises"]] == ["东门封锁"]
    assert body["risks"] == [
        {
            "level": "warning",
            "code": "map_dynamic_risk",
            "message": "东门封锁：待确认",
        }
    ]


@pytest.mark.asyncio
async def test_scene_summary_warns_when_character_previous_marker_is_on_other_map(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    previous_scene = await _create_scene(
        db_session, nid, scene_index=6, title="江陵旧事"
    )
    current_scene = await _create_scene(
        db_session, nid, scene_index=7, title="洛阳外城"
    )
    old_map = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="江陵", map_type="world", grid_width=5, grid_height=5),
    )
    new_map = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="洛阳", map_type="world", grid_width=5, grid_height=5),
    )
    character = await _create_entity(
        db_session, nid, entity_type="character", name="陆青"
    )
    location = await _create_entity(
        db_session, nid, entity_type="location", name="洛阳外城"
    )
    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        new_map.id,
        MapLocationBindingCreate(
            location_entity_id=str(location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        old_map.id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(previous_scene.id),
            start_scene_index=previous_scene.scene_index,
            label="陆青",
        ),
    )
    await MapMarkerService().create(
        db_session,
        nid,
        new_map.id,
        MapMarkerCreate(
            entity_id=str(character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            start_scene_id=str(current_scene.id),
            start_scene_index=current_scene.scene_index,
            label="陆青",
        ),
    )

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid, "scene_id": str(current_scene.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["warnings"][0]["code"] == "character_cross_map"
    assert "陆青上一场在其他地图" in body["warnings"][0]["message"]


@pytest.mark.asyncio
async def test_scene_summary_cross_novel_scene_returns_404(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    nid1 = uuid.uuid4().hex
    nid2 = uuid.uuid4().hex
    await _create_project(db_session, nid1)
    await _create_project(db_session, nid2)
    scene = await _create_scene(db_session, nid1)

    resp = await async_client.get(
        "/api/world/maps/scene-summary",
        params={"novel_id": nid2, "scene_id": str(scene.id)},
    )

    assert resp.status_code == 404
