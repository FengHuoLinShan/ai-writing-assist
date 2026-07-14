"""Acceptance coverage for map archive, CAS editing, layer tree, and presence."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapLocationLayout
from modules.world.models import CoreEntity
from modules.world.services.map import map_editor_apply as map_editor_apply_module
from modules.world.tests.helpers import _create_project


async def _create_map(
    client: AsyncClient,
    novel_id: str,
    name: str,
    *,
    parent_map_id: str | None = None,
) -> dict:
    response = await client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": name,
            "map_type": "world" if parent_map_id is None else "city",
            "grid_width": 4,
            "grid_height": 4,
            "parent_map_id": parent_map_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _tree_write_nodes(nodes: list[dict], *, marker_locked: bool) -> list[dict]:
    result = []
    for node in nodes:
        result.append(
            {
                "id": node["id"],
                "parent_id": node.get("parent_id"),
                "terrain_layer_id": node.get("terrain_layer_id"),
                "node_type": node["node_type"],
                "layer_key": node.get("layer_key"),
                "name": node["name"],
                "visible": node["visible"],
                "locked": (
                    marker_locked if node.get("layer_key") == "marker" else node["locked"]
                ),
                "opacity": node["opacity"],
                "sort_order": node["sort_order"],
                "min_zoom": node.get("min_zoom"),
                "max_zoom": node.get("max_zoom"),
                "meta": node.get("meta") or {},
            }
        )
    return result


@pytest.mark.asyncio
async def test_editor_cas_increments_once_and_failed_batch_rolls_back(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "CAS 地图")
    map_id = map_data["id"]

    first = await async_client.post(
        f"/api/world/maps/{map_id}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "base_terrain_replace",
                    "changes": [
                        {"hex_q": 0, "hex_r": 0, "terrain_type": "water"},
                        {"hex_q": 1, "hex_r": 1, "terrain_type": "mountain"},
                    ],
                }
            ],
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["editor_revision"] == 1

    stale = await async_client.post(
        f"/api/world/maps/{map_id}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "base_terrain_replace",
                    "changes": [{"hex_q": 0, "hex_r": 0, "terrain_type": "forest"}],
                }
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "map_editor_revision_conflict"
    assert stale.json()["context"]["current_revision"] == 1

    failed = await async_client.post(
        f"/api/world/maps/{map_id}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "base_terrain_replace",
                    "changes": [{"hex_q": 0, "hex_r": 0, "terrain_type": "forest"}],
                },
                {
                    "type": "marker_create",
                    "client_id": "new-marker",
                    "data": {
                        "entity_id": str(uuid.uuid4()),
                        "marker_type": "character",
                        "hex_q": 2,
                        "hex_r": 2,
                    },
                },
            ],
        },
    )
    assert failed.status_code == 404

    state = await async_client.get(
        f"/api/world/maps/{map_id}/state", params={"novel_id": novel_id}
    )
    tile = next(
        item
        for item in state.json()["tiles"]
        if item["hex_q"] == 0 and item["hex_r"] == 0
    )
    assert tile["terrain_type"] == "water"
    assert state.json()["map"]["editor_revision"] == 1


@pytest.mark.asyncio
async def test_editor_treats_uuid_client_id_as_alias_not_formal_resource_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "client id 冲突")
    entity = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "已有角色", "status": "canonical"},
    )
    marker = await async_client.post(
        f"/api/world/maps/{map_data['id']}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": entity.json()["id"],
            "marker_type": "character",
            "hex_q": 1,
            "hex_r": 1,
        },
    )
    assert marker.status_code == 201, marker.text

    created = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "marker_create",
                    "client_id": marker.json()["id"],
                    "data": {
                        "entity_id": entity.json()["id"],
                        "marker_type": "character",
                        "hex_q": 2,
                        "hex_r": 2,
                    },
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    created_id = created.json()["client_id_map"][marker.json()["id"]]
    assert created_id != marker.json()["id"]

    markers = await async_client.get(
        f"/api/world/maps/{map_data['id']}/markers",
        params={"novel_id": novel_id},
    )
    assert markers.status_code == 200
    assert {item["id"] for item in markers.json()} == {
        marker.json()["id"],
        created_id,
    }


@pytest.mark.asyncio
async def test_editor_resolves_terrain_region_client_layer_alias(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "地形别名解析")
    # UUID-valued aliases are correlation tokens, while region.layer_id is
    # canonicalized by Pydantic.  The service must compare their canonical forms.
    client_layer_id = str(uuid.uuid4()).upper()
    region_id = str(uuid.uuid4())

    response = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "terrain_layer_create",
                    "client_id": client_layer_id,
                    "data": {"name": "森林", "terrain_asset_key": "forest"},
                },
                {
                    "type": "terrain_patch_replace",
                    "layer_ref": {"client_id": client_layer_id},
                    "data": {
                        "regions": [
                            {
                                "id": region_id,
                                "layer_id": client_layer_id,
                                "name": "北部森林",
                            }
                        ],
                        "patches": [{"region_id": region_id, "hex_q": 1, "hex_r": 1}],
                    },
                },
            ],
        },
    )

    assert response.status_code == 200, response.text
    resolved_layer_id = response.json()["client_id_map"][client_layer_id]
    assert resolved_layer_id != client_layer_id

    terrain = await async_client.get(
        f"/api/world/maps/{map_data['id']}/terrain",
        params={"novel_id": novel_id},
    )
    assert terrain.status_code == 200, terrain.text
    assert [item["id"] for item in terrain.json()["layers"]] == [resolved_layer_id]
    assert terrain.json()["regions"][0]["layer_id"] == resolved_layer_id
    assert terrain.json()["patches"][0]["region_id"] == region_id


@pytest.mark.asyncio
async def test_editor_rejects_terrain_region_mismatched_client_layer_alias(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "地形别名隔离")
    client_layer_id = str(uuid.uuid4())
    other_client_layer_id = str(uuid.uuid4())

    response = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "terrain_layer_create",
                    "client_id": client_layer_id,
                    "data": {"name": "森林", "terrain_asset_key": "forest"},
                },
                {
                    "type": "terrain_layer_create",
                    "client_id": other_client_layer_id,
                    "data": {"name": "草原", "terrain_asset_key": "grass"},
                },
                {
                    "type": "terrain_patch_replace",
                    "layer_ref": {"client_id": client_layer_id},
                    "data": {
                        "regions": [
                            {
                                "id": str(uuid.uuid4()),
                                "layer_id": other_client_layer_id,
                                "name": "错误图层区域",
                            }
                        ]
                    },
                },
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_terrain_region_layer"

    terrain = await async_client.get(
        f"/api/world/maps/{map_data['id']}/terrain",
        params={"novel_id": novel_id},
    )
    assert terrain.status_code == 200, terrain.text
    assert terrain.json()["layers"] == []

    state = await async_client.get(
        f"/api/world/maps/{map_data['id']}/state",
        params={"novel_id": novel_id},
    )
    assert state.status_code == 200, state.text
    assert state.json()["map"]["editor_revision"] == 0


@pytest.mark.asyncio
async def test_editor_rejects_duplicate_and_forward_client_aliases_before_writes(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "client alias 预检")

    duplicate = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "terrain_layer_create",
                    "client_id": "duplicate-alias",
                    "data": {"name": "森林", "terrain_asset_key": "forest"},
                },
                {
                    "type": "marker_create",
                    "client_id": "duplicate-alias",
                    "data": {
                        "entity_id": str(uuid.uuid4()),
                        "marker_type": "character",
                        "hex_q": 1,
                        "hex_r": 1,
                    },
                },
            ],
        },
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["error"] == "duplicate_map_client_id"

    forward = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "terrain_patch_replace",
                    "layer_ref": {"client_id": "future-layer"},
                    "data": {"regions": [], "patches": []},
                },
                {
                    "type": "terrain_layer_create",
                    "client_id": "future-layer",
                    "data": {"name": "未来图层", "terrain_asset_key": "forest"},
                },
            ],
        },
    )
    assert forward.status_code == 400
    assert forward.json()["error"] == "invalid_map_client_reference"

    terrain = await async_client.get(
        f"/api/world/maps/{map_data['id']}/terrain",
        params={"novel_id": novel_id},
    )
    assert terrain.status_code == 200, terrain.text
    assert terrain.json()["layers"] == []


@pytest.mark.asyncio
async def test_editor_hex_limit_counts_rows_removed_by_replace(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "替换格计数")
    layer_id = str(uuid.uuid4())
    region_id = str(uuid.uuid4())
    created = await async_client.put(
        f"/api/world/maps/{map_data['id']}/terrain/layers/{layer_id}/patches",
        params={"novel_id": novel_id},
        json={
            "layer": {"name": "既有层", "terrain_asset_key": "forest"},
            "regions": [{"id": region_id, "layer_id": layer_id, "name": "既有区域"}],
            "patches": [{"region_id": region_id, "hex_q": 0, "hex_r": 0}],
        },
    )
    assert created.status_code == 200, created.text
    monkeypatch.setattr(map_editor_apply_module, "_MAX_CHANGED_HEXES", 1)

    response = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "terrain_patch_replace",
                    "layer_ref": {"id": layer_id},
                    "data": {
                        "patches": [{"region_id": region_id, "hex_q": 1, "hex_r": 1}]
                    },
                }
            ],
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "map_editor_hex_limit"


@pytest.mark.asyncio
async def test_archive_restore_subtree_and_active_name_uniqueness(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    root = await _create_map(async_client, novel_id, "旧世界")
    await _create_map(async_client, novel_id, "旧都", parent_map_id=root["id"])

    impact = await async_client.get(
        f"/api/world/maps/{root['id']}/archive-impact",
        params={"novel_id": novel_id},
    )
    assert impact.status_code == 200
    assert impact.json()["map_count"] == 2

    archived = await async_client.post(
        f"/api/world/maps/{root['id']}/archive",
        params={"novel_id": novel_id},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"

    active_list = await async_client.get(
        "/api/world/maps", params={"novel_id": novel_id, "status": "active"}
    )
    archived_list = await async_client.get(
        "/api/world/maps", params={"novel_id": novel_id, "status": "archived"}
    )
    assert active_list.json()["total"] == 0
    assert archived_list.json()["total"] == 2

    replacement = await _create_map(async_client, novel_id, "旧世界")
    conflict = await async_client.post(
        f"/api/world/maps/{root['id']}/restore",
        params={"novel_id": novel_id},
        json={},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "duplicate_map_name"

    restored = await async_client.post(
        f"/api/world/maps/{root['id']}/restore",
        params={"novel_id": novel_id},
        json={"root_name": "复原世界"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored_map_count"] == 2
    assert restored.json()["map"]["name"] == "复原世界"
    assert replacement["name"] == "旧世界"


@pytest.mark.asyncio
async def test_archived_maps_cannot_be_updated_or_used_as_active_parents(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    root = await _create_map(async_client, novel_id, "归档父图")
    child = await _create_map(async_client, novel_id, "原子图", parent_map_id=root["id"])
    archived = await async_client.post(
        f"/api/world/maps/{root['id']}/archive",
        params={"novel_id": novel_id},
    )
    assert archived.status_code == 200

    create_under_archived = await async_client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": "不应创建",
            "map_type": "city",
            "grid_width": 4,
            "grid_height": 4,
            "parent_map_id": root["id"],
        },
    )
    update_archived = await async_client.patch(
        f"/api/world/maps/{child['id']}",
        params={"novel_id": novel_id},
        json={"name": "不应改名"},
    )
    assert create_under_archived.status_code == 404
    assert update_archived.status_code == 404

    restored = await async_client.post(
        f"/api/world/maps/{root['id']}/restore",
        params={"novel_id": novel_id},
        json={},
    )
    assert restored.status_code == 200
    await _create_map(async_client, novel_id, "同层新图", parent_map_id=root["id"])
    duplicate_rename = await async_client.patch(
        f"/api/world/maps/{child['id']}",
        params={"novel_id": novel_id},
        json={"name": "同层新图"},
    )
    assert duplicate_rename.status_code == 409
    assert duplicate_rename.json()["error"] == "duplicate_map_name"


@pytest.mark.asyncio
async def test_recursive_group_lock_blocks_legacy_marker_writes_and_unlocks(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "图层锁")
    entity_response = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "character",
            "name": "锁定测试角色",
            "status": "canonical",
        },
    )
    entity_id = entity_response.json()["id"]

    tree = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    assert tree.status_code == 200, tree.text
    nodes = tree.json()["nodes"]
    lock = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "layer_tree_replace",
                    "nodes": _tree_write_nodes(nodes, marker_locked=True),
                }
            ],
        },
    )
    assert lock.status_code == 200, lock.text

    blocked = await async_client.post(
        f"/api/world/maps/{map_data['id']}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": entity_id,
            "marker_type": "character",
            "hex_q": 1,
            "hex_r": 1,
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "map_layer_locked"

    locked_tree = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    unlock = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 1,
            "commands": [
                {
                    "type": "layer_tree_replace",
                    "nodes": _tree_write_nodes(
                        locked_tree.json()["nodes"], marker_locked=False
                    ),
                }
            ],
        },
    )
    assert unlock.status_code == 200, unlock.text

    created = await async_client.post(
        f"/api/world/maps/{map_data['id']}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": entity_id,
            "marker_type": "character",
            "hex_q": 1,
            "hex_r": 1,
        },
    )
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_custom_group_lock_blocks_legacy_marker_territory_and_terrain(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "递归视觉锁")
    character = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "角色", "status": "canonical"},
    )
    organization = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "organization",
            "name": "组织",
            "status": "canonical",
        },
    )
    layer_id = str(uuid.uuid4())
    terrain = await async_client.put(
        f"/api/world/maps/{map_data['id']}/terrain/layers/{layer_id}/patches",
        params={"novel_id": novel_id},
        json={
            "layer": {"name": "风暴", "terrain_asset_key": "storm"},
            "regions": [],
            "patches": [],
        },
    )
    assert terrain.status_code == 200, terrain.text

    tree = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    nodes = _tree_write_nodes(tree.json()["nodes"], marker_locked=False)
    for order, layer_key in enumerate(("marker", "territory", "terrainOverlay")):
        node = next(item for item in nodes if item["layer_key"] == layer_key)
        node["parent_id"] = None
        node["parent_client_id"] = "visual-group"
        node["sort_order"] = order
    nodes.append(
        {
            "client_id": "visual-group",
            "parent_id": None,
            "node_type": "group",
            "layer_key": None,
            "name": "视觉组",
            "visible": True,
            "locked": True,
            "opacity": 1,
            "sort_order": 2,
            "min_zoom": None,
            "max_zoom": None,
            "meta": {},
        }
    )
    locked = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": tree.json()["editor_revision"],
            "commands": [{"type": "layer_tree_replace", "nodes": nodes}],
        },
    )
    assert locked.status_code == 200, locked.text

    locked_tree = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    locked_nodes = _tree_write_nodes(locked_tree.json()["nodes"], marker_locked=False)
    visual_group = next(item for item in locked_nodes if item["name"] == "视觉组")
    locked_nodes.append(
        {
            "client_id": "new-child-group",
            "parent_id": visual_group["id"],
            "node_type": "group",
            "layer_key": None,
            "name": "不应加入",
            "visible": True,
            "locked": False,
            "opacity": 1,
            "sort_order": 3,
            "min_zoom": None,
            "max_zoom": None,
            "meta": {},
        }
    )
    added_to_locked_group = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": locked_tree.json()["editor_revision"],
            "commands": [{"type": "layer_tree_replace", "nodes": locked_nodes}],
        },
    )
    assert added_to_locked_group.status_code == 409
    assert added_to_locked_group.json()["error"] == "map_layer_locked"

    blocked_marker = await async_client.post(
        f"/api/world/maps/{map_data['id']}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": character.json()["id"],
            "marker_type": "character",
            "hex_q": 1,
            "hex_r": 1,
        },
    )
    blocked_territory = await async_client.post(
        f"/api/world/maps/{map_data['id']}/territories",
        params={"novel_id": novel_id},
        json={
            "faction_entity_id": organization.json()["id"],
            "hexes": [{"hex_q": 1, "hex_r": 1}],
        },
    )
    blocked_terrain = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/terrain/layers/{layer_id}",
        params={"novel_id": novel_id},
        json={"name": "不应改名"},
    )
    assert blocked_marker.status_code == 409
    assert blocked_territory.status_code == 409
    assert blocked_terrain.status_code == 409

    current_tree = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    unlocked_nodes = _tree_write_nodes(current_tree.json()["nodes"], marker_locked=False)
    next(item for item in unlocked_nodes if item["name"] == "视觉组")["locked"] = False
    unlocked = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": current_tree.json()["editor_revision"],
            "commands": [{"type": "layer_tree_replace", "nodes": unlocked_nodes}],
        },
    )
    assert unlocked.status_code == 200, unlocked.text
    terrain_update = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/terrain/layers/{layer_id}",
        params={"novel_id": novel_id},
        json={"name": "已解锁"},
    )
    assert terrain_update.status_code == 200, terrain_update.text


@pytest.mark.asyncio
async def test_entity_presence_unions_layout_and_binding_and_hides_archived_maps(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    first_map = await _create_map(async_client, novel_id, "布局地图")
    second_map = await _create_map(async_client, novel_id, "绑定地图")
    entity_response = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "location",
            "name": "双向地点",
            "status": "canonical",
        },
    )
    entity_id = entity_response.json()["id"]

    layout = await async_client.put(
        f"/api/world/maps/{first_map['id']}/location-layouts",
        params={"novel_id": novel_id},
        json={
            "layouts": [
                {
                    "location_entity_id": entity_id,
                    "center_hex_q": 1,
                    "center_hex_r": 2,
                }
            ]
        },
    )
    assert layout.status_code == 200, layout.text
    binding = await async_client.post(
        f"/api/world/maps/{second_map['id']}/location-bindings",
        params={"novel_id": novel_id},
        json={
            "location_entity_id": entity_id,
            "hexes": [{"hex_q": 2, "hex_r": 1, "is_center": True}],
        },
    )
    assert binding.status_code == 201, binding.text

    engine = db_session.bind.sync_engine
    config_selects: list[str] = []
    layer_node_selects: list[str] = []

    def count_config_selects(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from map_configs " in normalized:
            config_selects.append(normalized)
        if normalized.startswith("select") and " from map_layer_nodes " in normalized:
            layer_node_selects.append(normalized)

    event.listen(engine, "before_cursor_execute", count_config_selects)
    try:
        presence = await async_client.get(
            f"/api/world/entities/{entity_id}/map-presence",
            params={"novel_id": novel_id},
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_config_selects)
    assert presence.status_code == 200, presence.text
    assert len(config_selects) == 1
    assert len(layer_node_selects) == 1
    assert presence.json()["total"] == 2
    assert {item["map_name"] for item in presence.json()["items"]} == {
        "布局地图",
        "绑定地图",
    }

    archived = await async_client.post(
        f"/api/world/maps/{first_map['id']}/archive",
        params={"novel_id": novel_id},
    )
    assert archived.status_code == 200
    active_presence = await async_client.get(
        f"/api/world/entities/{entity_id}/map-presence",
        params={"novel_id": novel_id},
    )
    assert active_presence.json()["total"] == 1

    candidate = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(hex=novel_id),
        entity_type="location",
        name="待处理地点",
        status="candidate",
    )
    db_session.add(candidate)
    await db_session.flush()
    db_session.add(
        MapLocationLayout(
            novel_id=uuid.UUID(hex=novel_id),
            map_id=uuid.UUID(second_map["id"]),
            location_entity_id=candidate.id,
            center_hex_q=3,
            center_hex_r=3,
        )
    )
    await db_session.flush()

    hidden = await async_client.get(
        f"/api/world/entities/{candidate.id}/map-presence",
        params={"novel_id": novel_id},
    )
    review = await async_client.get(
        f"/api/world/entities/{candidate.id}/map-presence",
        params={"novel_id": novel_id, "include_candidates": True},
    )
    assert hidden.json()["total"] == 0
    assert review.json()["items"][0]["display_state"] == "review"

    candidate.status = "ignored"
    await db_session.flush()
    historical = await async_client.get(
        f"/api/world/entities/{candidate.id}/map-presence",
        params={"novel_id": novel_id, "include_candidates": True},
    )
    assert historical.json()["total"] == 0


@pytest.mark.asyncio
async def test_terrain_only_presence_returns_a_representative_hex(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "地形绑定地图")
    entity_response = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "location",
            "name": "地形关联地点",
            "status": "canonical",
        },
    )
    entity_id = entity_response.json()["id"]
    layer_id = str(uuid.uuid4())
    region_id = str(uuid.uuid4())
    terrain = await async_client.put(
        f"/api/world/maps/{map_data['id']}/terrain/layers/{layer_id}/patches",
        params={"novel_id": novel_id},
        json={
            "layer": {"name": "地脉", "terrain_asset_key": "leyline"},
            "regions": [{"id": region_id, "layer_id": layer_id, "name": "地脉区域"}],
            "patches": [
                {"region_id": region_id, "hex_q": 3, "hex_r": 1},
                {"region_id": region_id, "hex_q": 2, "hex_r": 2},
            ],
        },
    )
    assert terrain.status_code == 200, terrain.text
    binding = await async_client.post(
        f"/api/world/maps/{map_data['id']}/terrain/regions/{region_id}/bindings",
        params={"novel_id": novel_id},
        json={
            "region_id": region_id,
            "location_entity_id": entity_id,
            "binding_type": "influence",
            "review_state": "confirmed",
        },
    )
    assert binding.status_code == 201, binding.text

    presence = await async_client.get(
        f"/api/world/entities/{entity_id}/map-presence",
        params={"novel_id": novel_id},
    )
    assert presence.status_code == 200, presence.text
    assert presence.json()["items"][0]["roles"] == ["terrain"]
    assert presence.json()["items"][0]["binding_count"] == 1
    assert (
        presence.json()["items"][0]["representative_hex_q"],
        presence.json()["items"][0]["representative_hex_r"],
    ) == (2, 2)

    candidate = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/terrain/bindings/{binding.json()['id']}",
        params={"novel_id": novel_id},
        json={"review_state": "candidate"},
    )
    assert candidate.status_code == 200, candidate.text
    hidden = await async_client.get(
        f"/api/world/entities/{entity_id}/map-presence",
        params={"novel_id": novel_id},
    )
    review = await async_client.get(
        f"/api/world/entities/{entity_id}/map-presence",
        params={"novel_id": novel_id, "include_candidates": True},
    )
    assert hidden.json()["total"] == 0
    assert review.json()["items"][0]["display_state"] == "review"

    ignored = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/terrain/bindings/{binding.json()['id']}",
        params={"novel_id": novel_id},
        json={"review_state": "ignored"},
    )
    assert ignored.status_code == 200, ignored.text
    ignored_presence = await async_client.get(
        f"/api/world/entities/{entity_id}/map-presence",
        params={"novel_id": novel_id, "include_candidates": True},
    )
    assert ignored_presence.json()["total"] == 0


@pytest.mark.asyncio
async def test_same_novel_cross_map_visual_resources_are_not_addressable(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    first_map = await _create_map(async_client, novel_id, "资源地图 A")
    second_map = await _create_map(async_client, novel_id, "资源地图 B")
    character = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={"entity_type": "character", "name": "角色", "status": "canonical"},
    )
    organization = await async_client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "organization",
            "name": "组织",
            "status": "canonical",
        },
    )
    marker = await async_client.post(
        f"/api/world/maps/{first_map['id']}/markers",
        params={"novel_id": novel_id},
        json={
            "entity_id": character.json()["id"],
            "marker_type": "character",
            "hex_q": 1,
            "hex_r": 1,
        },
    )
    territory = await async_client.post(
        f"/api/world/maps/{first_map['id']}/territories",
        params={"novel_id": novel_id},
        json={
            "faction_entity_id": organization.json()["id"],
            "hexes": [{"hex_q": 1, "hex_r": 1}],
        },
    )
    layer_id = str(uuid.uuid4())
    terrain = await async_client.put(
        f"/api/world/maps/{first_map['id']}/terrain/layers/{layer_id}/patches",
        params={"novel_id": novel_id},
        json={
            "layer": {"name": "河流", "terrain_asset_key": "river"},
            "regions": [],
            "patches": [],
        },
    )
    assert terrain.status_code == 200, terrain.text

    marker_cross_map = await async_client.patch(
        f"/api/world/maps/{second_map['id']}/markers/{marker.json()['id']}",
        params={"novel_id": novel_id},
        json={"hex_q": 2},
    )
    territory_cross_map = await async_client.delete(
        f"/api/world/maps/{second_map['id']}/territories/{territory.json()[0]['id']}",
        params={"novel_id": novel_id},
    )
    terrain_cross_map = await async_client.patch(
        f"/api/world/maps/{second_map['id']}/terrain/layers/{layer_id}",
        params={"novel_id": novel_id},
        json={"name": "越权改名"},
    )
    assert marker_cross_map.status_code == 404
    assert territory_cross_map.status_code == 404
    assert terrain_cross_map.status_code == 404


@pytest.mark.asyncio
async def test_layer_tree_complete_singletons_and_empty_zoom_intersection(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_map(async_client, novel_id, "缩放树")
    tree = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    nodes = _tree_write_nodes(tree.json()["nodes"], marker_locked=False)

    incomplete = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "layer_tree_replace",
                    "nodes": [node for node in nodes if node["layer_key"] != "pending"],
                }
            ],
        },
    )
    assert incomplete.status_code == 400
    assert incomplete.json()["error"] == "incomplete_map_layer_tree"

    for node in nodes:
        if node["layer_key"] == "marker":
            node["min_zoom"] = 2
        if node["layer_key"] == "marker.character":
            node["max_zoom"] = 1
    applied = await async_client.post(
        f"/api/world/maps/{map_data['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [{"type": "layer_tree_replace", "nodes": nodes}],
        },
    )
    assert applied.status_code == 200, applied.text

    refreshed = await async_client.get(
        f"/api/world/maps/{map_data['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    character_node = next(
        node
        for node in refreshed.json()["nodes"]
        if node["layer_key"] == "marker.character"
    )
    assert character_node["effective_visible"] is False
    assert character_node["effective_min_zoom"] == 2
    assert character_node["effective_max_zoom"] == 1


@pytest.mark.asyncio
async def test_layer_tree_rejects_wrong_singleton_type_and_foreign_node_ids(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    first_map = await _create_map(async_client, novel_id, "图层树 A")
    second_map = await _create_map(async_client, novel_id, "图层树 B")
    first_tree = await async_client.get(
        f"/api/world/maps/{first_map['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    second_tree = await async_client.get(
        f"/api/world/maps/{second_map['id']}/layer-tree",
        params={"novel_id": novel_id},
    )
    nodes = _tree_write_nodes(first_tree.json()["nodes"], marker_locked=False)
    pending = next(node for node in nodes if node["layer_key"] == "pending")
    pending["node_type"] = "group"
    wrong_type = await async_client.post(
        f"/api/world/maps/{first_map['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [{"type": "layer_tree_replace", "nodes": nodes}],
        },
    )
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"] == "invalid_map_singleton_node_type"

    pending["node_type"] = "leaf"
    foreign_pending = next(
        node for node in second_tree.json()["nodes"] if node["layer_key"] == "pending"
    )
    pending["id"] = foreign_pending["id"]
    foreign = await async_client.post(
        f"/api/world/maps/{first_map['id']}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [{"type": "layer_tree_replace", "nodes": nodes}],
        },
    )
    assert foreign.status_code == 400
    assert foreign.json()["error"] == "invalid_map_layer_parent"
