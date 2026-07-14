"""Typed map dynamics, Scene projections, and conservative continuity tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.facade import create_scene
from modules.world.map_models import MapObservation
from modules.world.services.map_service import MapDynamicFactService
from modules.world.tests.helpers import _create_entity, _create_project


async def _create_map(client: AsyncClient, novel_id: str, name: str = "动态地图") -> dict:
    response = await client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": name,
            "map_type": "world",
            "grid_width": 12,
            "grid_height": 12,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_scene(
    db: AsyncSession,
    novel_id: str,
    scene_index: int,
) -> dict:
    return await create_scene(
        db,
        novel_id,
        {
            "scene_index": scene_index,
            "title": f"Scene {scene_index}",
            "status": "canonical",
        },
    )


async def _create_fact(
    client: AsyncClient,
    novel_id: str,
    map_id: str,
    *,
    target_entity_id: str | None,
    target_name: str,
    dynamic_type: str,
    scene: dict,
    spatial_anchor: dict,
    value_json: dict,
) -> dict:
    created = await client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_entity_id": target_entity_id,
            "target_entity_type": "character" if target_entity_id else None,
            "target_name": target_name,
            "dynamic_type": dynamic_type,
            "scene_id": scene["id"],
            "scene_index": scene["scene_index"],
            "time_anchor": {"scene_index": scene["scene_index"]},
            "spatial_anchor": spatial_anchor,
            "value_json": value_json,
            "source_ref": {"source": "timeline_test"},
            "confidence": 1,
        },
    )
    assert created.status_code == 201, created.text
    confirmed = await client.post(
        f"/api/world/maps/{map_id}/observations/{created.json()['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


@pytest.mark.asyncio
async def test_typed_values_validate_normalize_and_keep_anchor_authoritative(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    location_a = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="东门",
        status="canonical",
    )
    location_b = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="西门",
        status="canonical",
    )

    typed = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "boundary",
            "value_json": {
                "schema_version": 1,
                "type": "boundary",
                "controller_entity_id": str(location_a.id),
                "hexes": [
                    {"hex_q": 3, "hex_r": 2},
                    {"hex_q": 1, "hex_r": 1},
                    {"hex_q": 3, "hex_r": 2},
                ],
            },
        },
    )
    assert typed.status_code == 201, typed.text
    assert typed.json()["normalization_state"] == "typed"
    assert typed.json()["dimension_key"] == f"boundary:{location_a.id}"
    assert typed.json()["value_json"]["hexes"] == [
        {"hex_q": 1, "hex_r": 1},
        {"hex_q": 3, "hex_r": 2},
    ]
    assert typed.json()["normalized_value"]["hexes"] == [
        {"hex_q": 1, "hex_r": 1},
        {"hex_q": 3, "hex_r": 2},
    ]

    mismatch = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "status",
            "value_json": {
                "schema_version": 1,
                "type": "crisis",
                "crisis_key": "gate",
                "severity": 3,
            },
        },
    )
    assert mismatch.status_code == 422

    legacy_conflict = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "location",
            "spatial_anchor": {"location_entity_id": str(location_a.id)},
            "value_json": {"location_entity_id": str(location_b.id)},
        },
    )
    assert legacy_conflict.status_code == 201, legacy_conflict.text
    assert legacy_conflict.json()["normalization_state"] == "invalid"
    assert legacy_conflict.json()["normalized_value"] is None


@pytest.mark.asyncio
async def test_partial_observation_patch_validates_merged_typed_contract(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    controller = await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name="守城军",
        status="canonical",
    )
    created = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "boundary",
            "value_json": {
                "schema_version": 1,
                "type": "boundary",
                "controller_entity_id": str(controller.id),
                "hexes": [{"hex_q": 1, "hex_r": 1}],
            },
        },
    )
    assert created.status_code == 201, created.text
    observation_id = created.json()["id"]

    type_only = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/observations/{observation_id}",
        params={"novel_id": novel_id},
        json={"dynamic_type": "terrain"},
    )
    assert type_only.status_code == 422
    assert type_only.json()["error"] == "invalid_map_dynamic_value"

    value_only = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/observations/{observation_id}",
        params={"novel_id": novel_id},
        json={
            "value_json": {
                "schema_version": 1,
                "type": "terrain",
                "terrain_key": "flood",
                "state": "spread",
                "hexes": [{"hex_q": 2, "hex_r": 2}],
            }
        },
    )
    assert value_only.status_code == 422
    assert value_only.json()["error"] == "invalid_map_dynamic_value"

    ordinary_patch = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/observations/{observation_id}",
        params={"novel_id": novel_id},
        json={"target_name": "城防边界"},
    )
    assert ordinary_patch.status_code == 200, ordinary_patch.text
    assert ordinary_patch.json()["value_json"] == created.json()["value_json"]


@pytest.mark.asyncio
async def test_confirm_and_batch_revalidate_preexisting_typed_candidates(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    invalid_controller_id = uuid.uuid4()
    stale = MapObservation(
        novel_id=uuid.UUID(novel_id),
        map_id=uuid.UUID(map_data["id"]),
        dynamic_type="boundary",
        spatial_anchor={},
        value_json={
            "schema_version": 1,
            "type": "boundary",
            "controller_entity_id": str(invalid_controller_id),
            "hexes": [{"hex_q": 1, "hex_r": 1}],
        },
        review_state="candidate",
        source_ref={"source": "pre_gate_fixture"},
    )
    db_session.add(stale)
    await db_session.flush()

    confirmed = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations/{stale.id}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirmed.status_code == 404

    batch = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations/batch-review",
        params={"novel_id": novel_id},
        json={"observation_ids": [str(stale.id)], "action": "confirm"},
    )
    assert batch.status_code == 404

    facts = await async_client.get(
        f"/api/world/maps/{map_data['id']}/facts",
        params={"novel_id": novel_id},
    )
    assert facts.status_code == 200
    assert facts.json()["total"] == 0


@pytest.mark.asyncio
async def test_deep_import_typed_gate_canonicalizes_or_quarantines(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    foreign_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, foreign_novel_id)
    map_data = await _create_map(async_client, novel_id)
    controller = await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name="本项目势力",
        status="canonical",
    )
    foreign_controller = await _create_entity(
        db_session,
        foreign_novel_id,
        entity_type="organization",
        name="外项目势力",
        status="canonical",
    )
    service = MapDynamicFactService()

    accepted = await service.create_observation_from_delta_event(
        db_session,
        novel_id,
        event={
            "category": "boundary",
            "meta": {
                "map_id": map_data["id"],
                "dynamic_type": "boundary",
                "map_value": {
                    "schema_version": 1,
                    "type": "boundary",
                    "controller_entity_id": str(controller.id),
                    "hexes": [
                        {"hex_q": 2, "hex_r": 2},
                        {"hex_q": 1, "hex_r": 1},
                        {"hex_q": 2, "hex_r": 2},
                    ],
                },
            },
        },
        scene_index=1,
    )
    assert accepted.value_json["hexes"] == [
        {"hex_q": 1, "hex_r": 1},
        {"hex_q": 2, "hex_r": 2},
    ]
    assert "invalid_map_value" not in accepted.source_ref

    quarantined = await service.create_observation_from_delta_event(
        db_session,
        novel_id,
        event={
            "category": "boundary",
            "meta": {
                "map_id": map_data["id"],
                "dynamic_type": "boundary",
                "map_value": {
                    "schema_version": 1,
                    "type": "boundary",
                    "controller_entity_id": str(foreign_controller.id),
                    "hexes": [{"hex_q": 1, "hex_r": 1}],
                },
            },
        },
        scene_index=2,
    )
    assert "schema_version" not in quarantined.value_json
    assert quarantined.source_ref["invalid_map_value"]["reason"] == (
        "entity_not_found"
    )


@pytest.mark.asyncio
async def test_scene_anchor_rejects_cross_novel_scene(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    map_data = await _create_map(async_client, novel_id)
    foreign_scene = await _create_scene(db_session, other_novel_id, 1)

    response = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "status",
            "scene_id": foreign_scene["id"],
            "scene_index": 1,
            "value_json": {
                "schema_version": 1,
                "type": "status",
                "field_key": "health",
                "value": "well",
            },
        },
    )
    assert response.status_code == 404
    assert response.json()["error"] == "scene_not_found"


@pytest.mark.asyncio
async def test_timeline_uses_prior_baseline_and_candidates_never_change_state(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    east = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="东门",
        status="canonical",
    )
    west = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="西门",
        status="canonical",
    )
    scene_1 = await _create_scene(db_session, novel_id, 1)
    scene_2 = await _create_scene(db_session, novel_id, 2)
    await _create_fact(
        async_client,
        novel_id,
        map_data["id"],
        target_entity_id=str(character.id),
        target_name="沈砚",
        dynamic_type="location",
        scene=scene_1,
        spatial_anchor={
            "location_entity_id": str(east.id),
            "hex_q": 1,
            "hex_r": 1,
        },
        value_json={
            "schema_version": 1,
            "type": "location",
            "location_entity_id": str(east.id),
            "movement_mode": "walk",
        },
    )
    await _create_fact(
        async_client,
        novel_id,
        map_data["id"],
        target_entity_id=str(character.id),
        target_name="沈砚",
        dynamic_type="location",
        scene=scene_2,
        spatial_anchor={
            "location_entity_id": str(west.id),
            "hex_q": 5,
            "hex_r": 2,
        },
        value_json={
            "schema_version": 1,
            "type": "location",
            "location_entity_id": str(west.id),
            "movement_mode": "walk",
        },
    )
    candidate = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "target_entity_id": str(character.id),
            "target_name": "沈砚",
            "dynamic_type": "location",
            "scene_id": scene_2["id"],
            "scene_index": 2,
            "spatial_anchor": {"hex_q": 9, "hex_r": 9},
            "value_json": {
                "schema_version": 1,
                "type": "location",
                "movement_mode": "teleport",
            },
        },
    )
    assert candidate.status_code == 201, candidate.text

    timeline = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 2,
            "to_scene_index": 2,
        },
    )
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert body["candidates"] == []
    assert body["total"] == 1
    assert body["deltas"][0]["change_kind"] == "change"
    assert body["deltas"][0]["before_scene_index"] == 1
    assert body["deltas"][0]["before"]["location_entity_id"] == str(east.id)
    token = body["projection_token"]

    with_candidates = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 2,
            "to_scene_index": 2,
            "include_candidates": True,
        },
    )
    assert with_candidates.status_code == 200, with_candidates.text
    assert len(with_candidates.json()["candidates"]) == 1
    assert with_candidates.json()["projection_token"] == token

    state = await async_client.get(
        f"/api/world/maps/{map_data['id']}/state-at",
        params={"novel_id": novel_id, "scene_index": 2},
    )
    assert state.status_code == 200, state.text
    location_state = next(
        item for item in state.json()["items"] if item["dynamic_type"] == "location"
    )
    assert location_state["normalized_value"]["location_entity_id"] == str(west.id)


@pytest.mark.asyncio
async def test_same_scene_conflict_is_not_selected_and_rollback_reprojects(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="林照",
        status="canonical",
    )
    scene = await _create_scene(db_session, novel_id, 3)
    facts = []
    for q, r in ((1, 1), (8, 8)):
        facts.append(
            await _create_fact(
                async_client,
                novel_id,
                map_data["id"],
                target_entity_id=str(character.id),
                target_name="林照",
                dynamic_type="location",
                scene=scene,
                spatial_anchor={"hex_q": q, "hex_r": r},
                value_json={
                    "schema_version": 1,
                    "type": "location",
                    "movement_mode": "unknown",
                },
            )
        )

    state = await async_client.get(
        f"/api/world/maps/{map_data['id']}/state-at",
        params={"novel_id": novel_id, "scene_index": 3},
    )
    assert state.status_code == 200, state.text
    assert state.json()["items"] == []
    assert state.json()["conflicts"][0]["reason"] == "same_scene_conflict"
    token = state.json()["projection_token"]

    rolled_back = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/facts/{facts[1]['id']}",
        params={"novel_id": novel_id},
        json={"fact_status": "rolled_back"},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    projected = await async_client.get(
        f"/api/world/maps/{map_data['id']}/state-at",
        params={"novel_id": novel_id, "scene_index": 3},
    )
    assert projected.status_code == 200, projected.text
    assert projected.json()["conflicts"] == []
    assert len(projected.json()["items"]) == 1
    assert projected.json()["projection_token"] != token


@pytest.mark.asyncio
async def test_unresolved_targets_are_not_merged_by_display_name(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    scenes = [
        await _create_scene(db_session, novel_id, scene_index)
        for scene_index in (1, 2)
    ]
    for scene, value in zip(scenes, ("open", "closed"), strict=True):
        await _create_fact(
            async_client,
            novel_id,
            map_data["id"],
            target_entity_id=None,
            target_name="同名未解析对象",
            dynamic_type="status",
            scene=scene,
            spatial_anchor={},
            value_json={
                "schema_version": 1,
                "type": "status",
                "field_key": "gate",
                "value": value,
            },
        )

    response = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 1,
            "to_scene_index": 2,
        },
    )
    assert response.status_code == 200, response.text
    assert [item["change_kind"] for item in response.json()["deltas"]] == [
        "initial",
        "initial",
    ]


async def _create_transport_path(
    client: AsyncClient,
    novel_id: str,
    map_id: str,
    start_id: str,
    end_id: str,
) -> dict:
    response = await client.post(
        f"/api/world/maps/{map_id}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "path_layer_create",
                    "client_id": "transport",
                    "leaf_client_id": "transport-leaf",
                    "display_name": "道路",
                    "category": "transport",
                },
                {
                    "type": "path_create",
                    "client_id": "road",
                    "data": {
                        "layer_ref": {"client_id": "transport"},
                        "name": "官道",
                        "path_type": "major_road",
                        "start_location_entity_id": start_id,
                        "end_location_entity_id": end_id,
                        "nodes": [{"q": 1, "r": 1}, {"q": 5, "r": 2}],
                    },
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_focused_timeline_uses_global_route_without_leaking_other_entity(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    other_character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="无关角色",
        status="canonical",
    )
    locations = []
    for name in ("东门", "西门"):
        locations.append(
            await _create_entity(
                db_session,
                novel_id,
                entity_type="location",
                name=name,
                status="canonical",
            )
        )
    path_result = await _create_transport_path(
        async_client,
        novel_id,
        map_data["id"],
        str(locations[0].id),
        str(locations[1].id),
    )
    path_id = path_result["client_id_map"]["road"]
    scene_1 = await _create_scene(db_session, novel_id, 1)
    scene_2 = await _create_scene(db_session, novel_id, 2)
    first_location_fact = await _create_fact(
        async_client,
        novel_id,
        map_data["id"],
        target_entity_id=str(character.id),
        target_name="沈砚",
        dynamic_type="location",
        scene=scene_1,
        spatial_anchor={
            "location_entity_id": str(locations[0].id),
            "hex_q": 1,
            "hex_r": 1,
        },
        value_json={
            "schema_version": 1,
            "type": "location",
            "location_entity_id": str(locations[0].id),
            "path_id": path_id,
            "movement_mode": "walk",
        },
    )
    assert first_location_fact["spatial_anchor"] == {
        "map_id": map_data["id"],
        "path_id": path_id,
        "path_revision": 1,
        "path_name": "官道",
        "location_entity_id": str(locations[0].id),
        "hex_q": 1,
        "hex_r": 1,
        "representative_q": 1.0,
        "representative_r": 1.0,
    }
    await _create_fact(
        async_client,
        novel_id,
        map_data["id"],
        target_entity_id=str(character.id),
        target_name="沈砚",
        dynamic_type="location",
        scene=scene_2,
        spatial_anchor={
            "location_entity_id": str(locations[1].id),
            "hex_q": 5,
            "hex_r": 2,
        },
        value_json={
            "schema_version": 1,
            "type": "location",
            "location_entity_id": str(locations[1].id),
            "path_id": path_id,
            "movement_mode": "walk",
        },
    )
    await _create_fact(
        async_client,
        novel_id,
        map_data["id"],
        target_entity_id=str(other_character.id),
        target_name="无关角色",
        dynamic_type="location",
        scene=scene_2,
        spatial_anchor={
            "location_entity_id": str(locations[0].id),
            "hex_q": 1,
            "hex_r": 1,
        },
        value_json={
            "schema_version": 1,
            "type": "location",
            "location_entity_id": str(locations[0].id),
            "movement_mode": "teleport",
        },
    )

    baseline = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 1,
            "to_scene_index": 2,
            "focus_entity_id": str(character.id),
            "tracks": "journey",
        },
    )
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["continuity_issues"] == []
    assert {
        item["target_entity_id"] for item in baseline.json()["deltas"]
    } == {str(character.id)}

    await _create_fact(
        async_client,
        novel_id,
        map_data["id"],
        target_entity_id=None,
        target_name="官道",
        dynamic_type="route_state",
        scene=scene_2,
        spatial_anchor={},
        value_json={
            "schema_version": 1,
            "type": "route_state",
            "path_id": path_id,
            "state": "blocked",
        },
    )

    response = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 1,
            "to_scene_index": 2,
            "focus_entity_id": str(character.id),
            "tracks": "journey",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["projection_token"] != baseline.json()["projection_token"]
    assert {
        item["target_entity_id"] for item in response.json()["deltas"]
    } == {str(character.id)}
    focused_state = await async_client.get(
        f"/api/world/maps/{map_data['id']}/state-at",
        params={
            "novel_id": novel_id,
            "scene_index": 2,
            "focus_entity_id": str(character.id),
        },
    )
    assert focused_state.status_code == 200, focused_state.text
    assert str(other_character.id) not in {
        item["target_entity_id"] for item in focused_state.json()["items"]
    }
    issues = response.json()["continuity_issues"]
    blocked = next(item for item in issues if item["issue_type"] == "blocked_route")
    assert blocked["path_ids"] == [path_id]
    assert blocked["distance_hex"] == 5
    assert "时" not in blocked["message"]
    suggested = blocked["suggested_observation"]
    assert suggested["dynamic_type"] == "movement_explanation"
    assert suggested["review_state"] == "candidate"

    edited = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "path_update",
                    "ref": {"id": path_id},
                    "data": {
                        "nodes": [
                            {"q": 1, "r": 1},
                            {"q": 4, "r": 2},
                            {"q": 5, "r": 2},
                        ]
                    },
                }
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    after_edit = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 1,
            "to_scene_index": 2,
            "focus_entity_id": str(character.id),
            "tracks": "journey",
        },
    )
    assert after_edit.status_code == 200, after_edit.text
    issue_types = {
        item["issue_type"] for item in after_edit.json()["continuity_issues"]
    }
    assert issue_types == {"path_revision_mismatch"}
    assert after_edit.json()["projection_token"] != response.json()["projection_token"]


@pytest.mark.asyncio
async def test_value_only_path_is_snapshotted_on_batch_confirm_and_reprojects(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id)
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="批量确认角色",
        status="canonical",
    )
    locations = [
        await _create_entity(
            db_session,
            novel_id,
            entity_type="location",
            name=name,
            status="canonical",
        )
        for name in ("北门", "南门")
    ]
    path_result = await _create_transport_path(
        async_client,
        novel_id,
        map_data["id"],
        str(locations[0].id),
        str(locations[1].id),
    )
    path_id = path_result["client_id_map"]["road"]
    scenes = [
        await _create_scene(db_session, novel_id, scene_index)
        for scene_index in (1, 2)
    ]
    observation_ids = []
    for scene, location, (hex_q, hex_r) in zip(
        scenes,
        locations,
        ((1, 1), (5, 2)),
        strict=True,
    ):
        created = await async_client.post(
            f"/api/world/maps/{map_data['id']}/observations",
            params={"novel_id": novel_id},
            json={
                "target_entity_id": str(character.id),
                "target_entity_type": "character",
                "target_name": "批量确认角色",
                "dynamic_type": "location",
                "scene_id": scene["id"],
                "scene_index": scene["scene_index"],
                "spatial_anchor": {
                    "location_entity_id": str(location.id),
                    "hex_q": hex_q,
                    "hex_r": hex_r,
                },
                "value_json": {
                    "schema_version": 1,
                    "type": "location",
                    "location_entity_id": str(location.id),
                    "path_id": path_id,
                    "movement_mode": "walk",
                },
            },
        )
        assert created.status_code == 201, created.text
        assert "path_id" not in created.json()["spatial_anchor"]
        observation_ids.append(created.json()["id"])

    confirmed = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations/batch-review",
        params={"novel_id": novel_id},
        json={"observation_ids": observation_ids, "action": "confirm"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["created_fact_count"] == 2
    for fact in confirmed.json()["facts"]:
        anchor = fact["spatial_anchor"]
        assert anchor["map_id"] == map_data["id"]
        assert anchor["path_id"] == path_id
        assert anchor["path_revision"] == 1
        assert anchor["path_name"] == "官道"
        assert anchor["representative_q"] is not None
        assert anchor["representative_r"] is not None

    edited = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "path_update",
                    "ref": {"id": path_id},
                    "data": {
                        "nodes": [
                            {"q": 1, "r": 1},
                            {"q": 3, "r": 2},
                            {"q": 5, "r": 2},
                        ]
                    },
                }
            ],
        },
    )
    assert edited.status_code == 200, edited.text
    projected = await async_client.get(
        f"/api/world/maps/{map_data['id']}/timeline",
        params={
            "novel_id": novel_id,
            "from_scene_index": 1,
            "to_scene_index": 2,
            "focus_entity_id": str(character.id),
            "tracks": "journey",
        },
    )
    assert projected.status_code == 200, projected.text
    assert {
        item["issue_type"] for item in projected.json()["continuity_issues"]
    } == {"path_revision_mismatch"}
