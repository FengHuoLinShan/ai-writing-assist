"""Acceptance coverage for continuous paths, floors, and typed anchors."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.tests.helpers import _create_project


async def _create_map(
    client: AsyncClient,
    novel_id: str,
    name: str,
) -> dict:
    response = await client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": name,
            "map_type": "world",
            "grid_width": 8,
            "grid_height": 8,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_path(
    client: AsyncClient,
    novel_id: str,
    map_id: str,
    *,
    start_location_entity_id: str | None = None,
    end_location_entity_id: str | None = None,
    locked: bool = False,
) -> dict:
    response = await client.post(
        f"/api/world/maps/{map_id}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "path_layer_create",
                    "client_id": "transport-layer",
                    "leaf_client_id": "transport-leaf",
                    "display_name": "交通线",
                    "category": "transport",
                },
                {
                    "type": "path_create",
                    "client_id": "main-road",
                    "data": {
                        "layer_ref": {"client_id": "transport-layer"},
                        "name": "王都大道",
                        "path_type": "major_road",
                        "locked": locked,
                        "start_location_entity_id": start_location_entity_id,
                        "end_location_entity_id": end_location_entity_id,
                        "nodes": [
                            {"q": 1.25, "r": 1.5},
                            {
                                "q": 3.5,
                                "r": 2.75,
                                "width_scale": 1.5,
                                "tension": 0.4,
                                "segment_type": "street",
                            },
                        ],
                    },
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_path_create_read_and_server_owned_ids(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "线路地图")

    applied = await _create_path(async_client, novel_id, map_data["id"])

    assert applied["editor_revision"] == 1
    ids = applied["client_id_map"]
    assert set(ids) == {"transport-layer", "transport-leaf", "main-road"}
    assert all(str(uuid.UUID(value)) == value for value in ids.values())
    assert all(value not in ids for value in ids.values())

    response = await async_client.get(
        f"/api/world/maps/{map_data['id']}/paths",
        params={"novel_id": novel_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["editor_revision"] == 1
    assert body["layers"][0]["name"] == "交通线"
    assert body["layers"][0]["layer_node_id"] == ids["transport-leaf"]
    assert body["paths"][0]["id"] == ids["main-road"]
    assert body["paths"][0]["nodes"][0]["q"] == 1.25
    assert body["paths"][0]["nodes"][1]["segment_type"] == "street"

    single = await async_client.get(
        f"/api/world/maps/{map_data['id']}/paths/{ids['main-road']}",
        params={"novel_id": novel_id},
    )
    assert single.status_code == 200
    assert single.json()["content_revision"] == 1


@pytest.mark.asyncio
async def test_locked_path_requires_unlock_only_command(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "锁定线路")
    location = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "location",
            "name": "未布置地点",
            "status": "canonical",
        },
    )
    assert location.status_code == 201, location.text
    applied = await _create_path(
        async_client,
        novel_id,
        map_data["id"],
        start_location_entity_id=location.json()["id"],
        locked=True,
    )

    blocked = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "path_update",
                    "ref": {"id": applied["client_id_map"]["main-road"]},
                    "data": {"locked": False, "snap_start": True},
                }
            ],
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "map_path_locked"


@pytest.mark.asyncio
async def test_spatial_anchor_rejects_and_scrubs_cross_novel_location(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    map_data = await _create_map(async_client, novel_id, "锚点隔离")
    foreign_location = await async_client.post(
        "/api/world/entities",
        params={"novel_id": other_novel_id},
        json={
            "entity_type": "location",
            "name": "外项目地点",
            "status": "canonical",
        },
    )
    assert foreign_location.status_code == 201, foreign_location.text

    rejected = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "movement",
            "spatial_anchor": {
                "location_entity_id": foreign_location.json()["id"],
            },
        },
    )
    assert rejected.status_code == 404

    spoofed_snapshot = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "movement",
            "spatial_anchor": {"path_revision": 9, "path_name": "伪造线路"},
        },
    )
    assert spoofed_snapshot.status_code == 422

    from modules.world.services.map_service import MapDynamicFactService

    imported = await MapDynamicFactService().create_observation_from_delta_event(
        db_session,
        novel_id,
        event={
            "category": "movement",
            "meta": {
                "map_id": map_data["id"],
                "spatial_anchor": {
                    "location_entity_id": foreign_location.json()["id"],
                },
            },
        },
        scene_index=1,
    )
    assert imported.spatial_anchor is not None
    assert "location_entity_id" not in imported.spatial_anchor
    assert imported.source_ref["invalid_spatial_anchor"]["reason"] == (
        "invalid_location_reference"
    )


@pytest.mark.asyncio
async def test_path_preflight_counts_snap_rewrite_and_rejects_deleted_layer_ref(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "路径预检")
    location = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "location",
            "name": "吸附目标",
            "status": "canonical",
        },
    )
    applied = await _create_path(
        async_client,
        novel_id,
        map_data["id"],
        start_location_entity_id=location.json()["id"],
    )

    from modules.world.services.map import map_editor_apply as editor_module

    monkeypatch.setattr(editor_module, "_MAX_CHANGED_PATH_NODES", 3)
    limited = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "path_update",
                    "ref": {"id": applied["client_id_map"]["main-road"]},
                    "data": {"snap_start": True},
                }
            ],
        },
    )
    assert limited.status_code == 400
    assert limited.json()["error"] == "map_editor_path_node_limit"

    other_map = await _create_map(async_client, novel_id, "删除后引用")
    layer = await async_client.post(
        f"/api/world/maps/{other_map['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "path_layer_create",
                    "client_id": "empty-layer",
                    "leaf_client_id": "empty-leaf",
                    "display_name": "空线路层",
                    "category": "transport",
                }
            ],
        },
    )
    assert layer.status_code == 200, layer.text
    layer_id = layer.json()["client_id_map"]["empty-layer"]
    invalid_order = await async_client.post(
        f"/api/world/maps/{other_map['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {"type": "path_layer_delete", "ref": {"id": layer_id}},
                {
                    "type": "path_create",
                    "client_id": "late-path",
                    "data": {
                        "layer_ref": {"id": layer_id},
                        "name": "不应创建",
                        "path_type": "major_road",
                        "nodes": [{"q": 0, "r": 0}, {"q": 1, "r": 1}],
                    },
                },
            ],
        },
    )
    assert invalid_order.status_code == 400
    assert invalid_order.json()["error"] == "invalid_map_command_order"
    state = await async_client.get(
        f"/api/world/maps/{other_map['id']}/paths",
        params={"novel_id": novel_id},
    )
    assert {item["id"] for item in state.json()["layers"]} == {layer_id}


@pytest.mark.asyncio
async def test_path_anchor_fact_snapshot_presence_and_archive_lifecycle(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "叙事线路")
    locations = []
    for name in ("王都", "北港"):
        response = await async_client.post(
            "/api/world/entities",
            params={"novel_id": novel_id},
            json={"entity_type": "location", "name": name, "status": "canonical"},
        )
        assert response.status_code == 201, response.text
        locations.append(response.json()["id"])
    applied = await _create_path(
        async_client,
        novel_id,
        map_data["id"],
        start_location_entity_id=locations[0],
        end_location_entity_id=locations[1],
    )
    path_id = applied["client_id_map"]["main-road"]

    observation = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "movement",
            "target_name": "北上行程",
            "spatial_anchor": {"path_id": path_id},
        },
    )
    assert observation.status_code == 201, observation.text
    assert observation.json()["spatial_anchor"]["map_id"] == map_data["id"]

    confirmed = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations/"
        f"{observation.json()['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert confirmed.status_code == 200, confirmed.text
    anchor = confirmed.json()["spatial_anchor"]
    assert anchor["path_id"] == path_id
    assert anchor["path_revision"] == 1
    assert anchor["path_name"] == "王都大道"
    assert 1.25 < anchor["representative_q"] < 3.5

    presence = await async_client.get(
        f"/api/world/entities/{locations[0]}/map-presence",
        params={"novel_id": novel_id},
    )
    assert presence.status_code == 200, presence.text
    item = presence.json()["items"][0]
    assert "path.start" in item["roles"]
    assert item["path_refs"][0]["path_id"] == path_id
    assert item["open_target"]["focus_path_id"] == path_id
    assert item["representative_world_q"] == 1.25

    pending = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "dynamic_type": "movement",
            "target_name": "待确认行程",
            "spatial_anchor": {"path_id": path_id},
        },
    )
    assert pending.status_code == 201, pending.text

    impact = await async_client.get(
        f"/api/world/maps/{map_data['id']}/paths/{path_id}/archive-impact",
        params={"novel_id": novel_id},
    )
    assert impact.status_code == 200
    assert impact.json()["observation_count"] == 2
    assert impact.json()["fact_count"] == 1

    archived = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [{"type": "path_archive", "ref": {"id": path_id}}],
        },
    )
    assert archived.status_code == 200, archived.text
    blocked = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations/"
        f"{pending.json()['id']}/confirm",
        params={"novel_id": novel_id},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "map_path_archived"

    layer_id = applied["client_id_map"]["transport-layer"]
    non_empty = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 2,
            "commands": [
                {"type": "path_layer_delete", "ref": {"id": layer_id}}
            ],
        },
    )
    assert non_empty.status_code == 409
    assert non_empty.json()["error"] == "map_path_layer_not_empty"

    restored = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 2,
            "commands": [{"type": "path_restore", "ref": {"id": path_id}}],
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["editor_revision"] == 3


@pytest.mark.asyncio
async def test_floor_tree_validation_and_cross_map_path_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    first = await _create_map(async_client, novel_id, "楼层地图")
    second = await _create_map(async_client, novel_id, "其他地图")
    applied = await _create_path(async_client, novel_id, first["id"])
    path_id = applied["client_id_map"]["main-road"]

    cross_map = await async_client.get(
        f"/api/world/maps/{second['id']}/paths/{path_id}",
        params={"novel_id": novel_id},
    )
    assert cross_map.status_code == 404

    tree = await async_client.get(
        f"/api/world/maps/{second['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    nodes = tree.json()["nodes"]
    marker = next(node for node in nodes if node["layer_key"] == "marker")
    children = [node for node in nodes if node["parent_id"] == marker["id"]]
    writes = []
    for node in nodes:
        floor_level = None
        if node in children:
            floor_level = children.index(node) - 1
        writes.append(
            {
                "id": node["id"],
                "parent_id": node["parent_id"],
                "terrain_layer_id": node["terrain_layer_id"],
                "path_layer_id": node["path_layer_id"],
                "node_type": node["node_type"],
                "layer_key": node["layer_key"],
                "name": node["name"],
                "visible": node["visible"],
                "locked": node["locked"],
                "opacity": node["opacity"],
                "sort_order": node["sort_order"],
                "min_zoom": node["min_zoom"],
                "max_zoom": node["max_zoom"],
                "selection_mode": (
                    "floor" if node["id"] == marker["id"] else "normal"
                ),
                "floor_level": floor_level,
                "meta": node["meta"] or {},
            }
        )
    saved = await async_client.post(
        f"/api/world/maps/{second['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [{"type": "layer_tree_replace", "nodes": writes}],
        },
    )
    assert saved.status_code == 200, saved.text
    saved_tree = await async_client.get(
        f"/api/world/maps/{second['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    saved_marker = next(
        node for node in saved_tree.json()["nodes"] if node["layer_key"] == "marker"
    )
    assert saved_marker["selection_mode"] == "floor"
    assert {
        node["floor_level"]
        for node in saved_tree.json()["nodes"]
        if node["parent_id"] == saved_marker["id"]
    } == {-1, 0, 1}

    duplicate = [dict(node) for node in writes]
    for node in duplicate:
        if node["parent_id"] == marker["id"]:
            node["floor_level"] = 0
    rejected = await async_client.post(
        f"/api/world/maps/{second['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [{"type": "layer_tree_replace", "nodes": duplicate}],
        },
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "duplicate_map_floor_level"
