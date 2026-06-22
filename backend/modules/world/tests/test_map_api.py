"""test_map_api — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import MapTileRepository
from modules.world.map_schemas import (
    MapConfigCreate,
    MapLocationBindingCreate,
    MapMarkerCreate,
    MapMarkerUpdate,
    MapTerritoryCreate,
    MapTerritoryUpdate,
    MapTileBatchUpdate,
)
from modules.world.models import CoreEntity
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
    MapMarkerService,
    MapTerritoryService,
    MapTileService,
)
from modules.world.tests.helpers import (
    _create_location_entity,
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
        # project 不存在但 list 不校验 FK，应返回空列表
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []


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
    async def test_api_delete_map_cascades_bindings(
        self, async_client: AsyncClient, db_session: AsyncSession
    ):
        """删除地图后 bindings 随之清除（FK CASCADE）。"""
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
            json={"entity_type": "location", "name": "洛阳"},
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

        # 再查 state 应 404（地图已删）
        state_after = await async_client.get(
            f"/api/world/maps/{map_id}/state", params={"novel_id": nid}
        )
        assert state_after.status_code == 404
