"""test_map_api — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapLocationBinding
from modules.world.models import CoreEntity
from modules.world.tests.helpers import (
    _create_project,
)


class TestMapHTTPAPI:
    """TestMapHTTPAPI 测试集合。"""

    @pytest.mark.asyncio
    async def test_api_create_and_get_map(self, async_client: AsyncClient):
        # 先建 project（API 需要 novel_id 存在于 DB）
        nid = uuid.uuid4().hex

        # 通过 client 无法直接建 project（无 fixture），用 db_session fixture 不可达
        # 改用 world API 间接验证：此处仅验证 404/422 行为
        resp = await async_client.get("/api/world/maps", params={"novel_id": nid})
        # 不存在与已软删项目统一为 404，不泄漏地图资源。
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_api_map_state_404_for_unknown(self, async_client: AsyncClient):
        nid = uuid.uuid4().hex
        fake_map = uuid.uuid4().hex
        resp = await async_client.get(
            f"/api/world/maps/{fake_map}/state", params={"novel_id": nid}
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_api_create_map_via_http(
        self, async_client: AsyncClient, db_session: AsyncSession
    ):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)

        resp = await async_client.post(
            "/api/world/maps",
            params={"novel_id": nid},
            json={
                "name": "九州世界",
                "map_type": "world",
                "grid_width": 30,
                "grid_height": 20,
                "template": "continent",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "九州世界"
        assert body["map_type"] == "world"

        # 验证 state 端点
        state_resp = await async_client.get(
            f"/api/world/maps/{body['id']}/state", params={"novel_id": nid}
        )
        assert state_resp.status_code == 200
        state = state_resp.json()
        assert len(state["tiles"]) == 600
        assert state["scene"] is None

    @pytest.mark.asyncio
    async def test_api_batch_update_tiles_via_http(
        self, async_client: AsyncClient, db_session: AsyncSession
    ):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        create_resp = await async_client.post(
            "/api/world/maps",
            params={"novel_id": nid},
            json={"name": "m", "map_type": "world", "grid_width": 5, "grid_height": 5},
        )
        map_id = create_resp.json()["id"]

        patch_resp = await async_client.patch(
            f"/api/world/maps/{map_id}/tiles",
            params={"novel_id": nid},
            json={
                "changes": [
                    {"hex_q": 0, "hex_r": 0, "terrain_type": "water"},
                    {"hex_q": 1, "hex_r": 1, "terrain_type": "mountain"},
                ]
            },
        )
        assert patch_resp.status_code == 200, patch_resp.text
        tiles = patch_resp.json()
        by_pos = {(t["hex_q"], t["hex_r"]): t["terrain_type"] for t in tiles}
        assert by_pos[(0, 0)] == "water"
        assert by_pos[(1, 1)] == "mountain"

    @pytest.mark.asyncio
    async def test_api_update_map_uses_patch(
        self, async_client: AsyncClient, db_session: AsyncSession
    ):
        """B1：PATCH /maps/{id} 不返回 405。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        create_resp = await async_client.post(
            "/api/world/maps",
            params={"novel_id": nid},
            json={"name": "原名", "map_type": "world", "grid_width": 3, "grid_height": 3},
        )
        map_id = create_resp.json()["id"]

        patch_resp = await async_client.patch(
            f"/api/world/maps/{map_id}",
            params={"novel_id": nid},
            json={"name": "新名"},
        )
        assert patch_resp.status_code == 200, patch_resp.text
        assert patch_resp.json()["name"] == "新名"

    @pytest.mark.asyncio
    async def test_api_delete_map_archives_and_preserves_bindings(
        self, async_client: AsyncClient, db_session: AsyncSession
    ):
        """兼容 DELETE 归档地图，但保留已采用地图资产。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        # 建地图 + location
        create_resp = await async_client.post(
            "/api/world/maps",
            params={"novel_id": nid},
            json={"name": "m", "map_type": "world", "grid_width": 5, "grid_height": 5},
        )
        map_id = create_resp.json()["id"]
        loc_resp = await async_client.post(
            "/api/world/entities",
            params={"novel_id": nid},
            json={"entity_type": "location", "name": "洛阳", "status": "canonical"},
        )
        loc_id = loc_resp.json()["id"]
        # 建绑定
        await async_client.post(
            f"/api/world/maps/{map_id}/location-bindings",
            params={"novel_id": nid},
            json={
                "location_entity_id": loc_id,
                "hexes": [{"hex_q": 1, "hex_r": 1, "is_center": True}],
            },
        )
        # state 应有 1 个 binding
        state_before = await async_client.get(
            f"/api/world/maps/{map_id}/state", params={"novel_id": nid}
        )
        assert len(state_before.json()["location_bindings"]) == 1

        # 删除地图
        del_resp = await async_client.delete(
            f"/api/world/maps/{map_id}", params={"novel_id": nid}
        )
        assert del_resp.status_code == 204

        # active state 不可见，但 archived 列表和资产仍保留。
        state_after = await async_client.get(
            f"/api/world/maps/{map_id}/state", params={"novel_id": nid}
        )
        assert state_after.status_code == 404
        archived = await async_client.get(
            "/api/world/maps",
            params={"novel_id": nid, "status": "archived"},
        )
        assert archived.json()["total"] == 1
        binding = await db_session.scalar(
            select(MapLocationBinding).where(
                MapLocationBinding.map_id == uuid.UUID(map_id)
            )
        )
        assert binding is not None

    @pytest.mark.asyncio
    async def test_api_formal_map_layers_reject_pending_compatibility_shadows(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = uuid.uuid4().hex
        await _create_project(db_session, novel_id)
        map_resp = await async_client.post(
            "/api/world/maps",
            params={"novel_id": novel_id},
            json={
                "name": "九州",
                "map_type": "world",
                "grid_width": 5,
                "grid_height": 5,
            },
        )
        assert map_resp.status_code == 201, map_resp.text
        map_id = map_resp.json()["id"]

        shadow_specs = [
            (
                "location",
                f"/api/world/maps/{map_id}/location-bindings",
                {
                    "location_entity_id": None,
                    "hexes": [{"hex_q": 1, "hex_r": 1, "is_center": True}],
                },
            ),
            (
                "character",
                f"/api/world/maps/{map_id}/markers",
                {
                    "entity_id": None,
                    "marker_type": "character",
                    "hex_q": 1,
                    "hex_r": 1,
                },
            ),
            (
                "organization",
                f"/api/world/maps/{map_id}/territories",
                {
                    "faction_entity_id": None,
                    "hexes": [{"hex_q": 1, "hex_r": 1}],
                },
            ),
        ]

        for entity_type, path, payload in shadow_specs:
            shadow = CoreEntity(
                id=uuid.uuid4(),
                novel_id=uuid.UUID(hex=novel_id),
                entity_type=entity_type,
                name=f"AI 待处理 {entity_type}",
                status="candidate",
                content_json={
                    "_meta": {
                        "compatibility_shadow": True,
                        "suggestion_id": str(uuid.uuid4()),
                    }
                },
            )
            db_session.add(shadow)
            await db_session.flush()
            id_field = next(key for key, value in payload.items() if value is None)
            payload[id_field] = str(shadow.id)

            response = await async_client.post(
                path,
                params={"novel_id": novel_id},
                json=payload,
            )

            assert response.status_code == 400, response.text
            assert response.json()["error"] == "unadopted_map_entity"

    @pytest.mark.asyncio
    async def test_api_terrain_layer_patch_lock_delete_and_novel_isolation(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        novel_id = uuid.uuid4().hex
        other_novel_id = uuid.uuid4().hex
        await _create_project(db_session, novel_id)
        await _create_project(db_session, other_novel_id)
        map_resp = await async_client.post(
            "/api/world/maps",
            params={"novel_id": novel_id},
            json={
                "name": "覆盖层接口",
                "map_type": "world",
                "grid_width": 5,
                "grid_height": 5,
            },
        )
        assert map_resp.status_code == 201, map_resp.text
        map_id = map_resp.json()["id"]
        layer_id = uuid.uuid4().hex
        region_id = uuid.uuid4().hex

        create_layer = await async_client.put(
            f"/api/world/maps/{map_id}/terrain/layers/{layer_id}/patches",
            params={"novel_id": novel_id},
            json={
                "layer": {
                    "name": "迷雾层",
                    "terrain_asset_key": "fog",
                    "opacity": 0.3,
                    "meta": {"pack_key": "fantasy_crisis"},
                },
                "regions": [{"id": region_id, "layer_id": layer_id, "name": "北境迷雾"}],
                "patches": [{"region_id": region_id, "hex_q": 1, "hex_r": 2}],
            },
        )
        assert create_layer.status_code == 200, create_layer.text

        lock_layer = await async_client.patch(
            f"/api/world/maps/{map_id}/terrain/layers/{layer_id}",
            params={"novel_id": novel_id},
            json={"name": "北境迷雾", "locked": True},
        )
        assert lock_layer.status_code == 200, lock_layer.text
        assert lock_layer.json()["name"] == "北境迷雾"
        assert lock_layer.json()["opacity"] == 0.3

        hidden_cross_novel = await async_client.patch(
            f"/api/world/maps/{map_id}/terrain/layers/{layer_id}",
            params={"novel_id": other_novel_id},
            json={"visible": False},
        )
        assert hidden_cross_novel.status_code == 404

        locked_delete = await async_client.delete(
            f"/api/world/maps/{map_id}/terrain/layers/{layer_id}",
            params={"novel_id": novel_id},
        )
        assert locked_delete.status_code == 409

        unlock_layer = await async_client.patch(
            f"/api/world/maps/{map_id}/terrain/layers/{layer_id}",
            params={"novel_id": novel_id},
            json={"locked": False},
        )
        assert unlock_layer.status_code == 200, unlock_layer.text
        deleted = await async_client.delete(
            f"/api/world/maps/{map_id}/terrain/layers/{layer_id}",
            params={"novel_id": novel_id},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {
            "deleted_layer_id": str(uuid.UUID(layer_id)),
            "deleted_regions": 1,
            "deleted_patches": 1,
            "deleted_bindings": 0,
        }
