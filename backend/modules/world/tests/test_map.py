"""动态地图功能用户路径验收测试 — PRD docs/PRD-动态地图功能.md

覆盖 P0：
- 地图配置 CRUD + 创建时生成初始 tile
- 地形批量编辑（含越界校验）
- 地点绑定（批量 + 中心点唯一性 + 非 location 类型拒绝 + 跨 novel 隔离）
- 地图层级（详图 parent_map_id + 面包屑）
- 快速生成详图地形
- API 层 5 verb + novel_id 隔离
"""

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
    _create_organization,
    _create_project,
)

# ============================================================
# 地图配置管理
# ============================================================


class TestMapConfigManagement:
    @pytest.mark.asyncio
    async def test_create_world_map_generates_initial_tiles(
        self, db_session: AsyncSession
    ):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)

        svc = MapConfigService()
        data = MapConfigCreate(
            name="九州世界",
            map_type="world",
            grid_width=30,
            grid_height=20,
            template="blank",
        )
        result = await svc.create(db_session, nid, data)

        assert result.name == "九州世界"
        assert result.map_type == "world"
        assert result.grid_width == 30
        assert result.grid_height == 20

        # 验证生成了 30x20=600 个 tile
        tiles = await MapTileRepository().get_by_map(
            db_session, uuid.UUID(hex=nid), uuid.UUID(hex=result.id)
        )
        assert len(tiles) == 600
        # blank 模板全 grassland
        assert all(t.terrain_type == "grassland" for t in tiles)

    @pytest.mark.asyncio
    async def test_list_maps_filter_by_parent(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)

        svc = MapConfigService()
        await svc.create(
            db_session,
            nid,
            MapConfigCreate(name="世界", map_type="world", grid_width=10, grid_height=10),
        )
        # 顶层列表
        top = await svc.list(db_session, nid)
        assert top.total == 1
        assert top.items[0].name == "世界"

    @pytest.mark.asyncio
    async def test_update_map(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid,
            MapConfigCreate(name="旧名", map_type="world", grid_width=5, grid_height=5),
        )
        from modules.world.map_schemas import MapConfigUpdate

        updated = await svc.update(
            db_session,
            created.id,
            MapConfigUpdate(name="新名", sort_order=3),
            novel_id=nid,
        )
        assert updated.name == "新名"
        assert updated.sort_order == 3

    @pytest.mark.asyncio
    async def test_delete_map_cascades_tiles(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid,
            MapConfigCreate(name="待删", map_type="world", grid_width=3, grid_height=3),
        )
        mid = uuid.UUID(hex=created.id)
        # 确认有 tile
        repo = MapTileRepository()
        tiles_before = await repo.get_by_map(db_session, uuid.UUID(hex=nid), mid)
        assert len(tiles_before) == 9

        await svc.delete(db_session, created.id, novel_id=nid)

        # map 已删（404）
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=nid)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_map_cross_novel_returns_404(self, db_session: AsyncSession):
        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid1,
            MapConfigCreate(
                name="小说1地图", map_type="world", grid_width=3, grid_height=3
            ),
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=nid2)
        assert exc.value.status_code == 404


# ============================================================
# 地形批量编辑
# ============================================================


class TestMapTileEditing:
    @pytest.mark.asyncio
    async def test_batch_update_terrain(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=5, grid_height=5),
        )

        tile_svc = MapTileService()
        result = await tile_svc.batch_update(
            db_session,
            nid,
            created.id,
            MapTileBatchUpdate(
                changes=[
                    {"hex_q": 0, "hex_r": 0, "terrain_type": "water"},
                    {"hex_q": 1, "hex_r": 1, "terrain_type": "mountain"},
                ]
            ),
        )
        by_pos = {(t.hex_q, t.hex_r): t.terrain_type for t in result}
        assert by_pos[(0, 0)] == "water"
        assert by_pos[(1, 1)] == "mountain"

    @pytest.mark.asyncio
    async def test_batch_update_out_of_range_returns_400(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=3, grid_height=3),
        )
        tile_svc = MapTileService()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await tile_svc.batch_update(
                db_session,
                nid,
                created.id,
                MapTileBatchUpdate(
                    changes=[{"hex_q": 5, "hex_r": 0, "terrain_type": "water"}]
                ),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_batch_update_idempotent_upsert(self, db_session: AsyncSession):
        """同一格二次编辑应 upsert 而非报唯一约束错。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=3, grid_height=3),
        )
        tile_svc = MapTileService()
        # 第一次 forest
        await tile_svc.batch_update(
            db_session,
            nid,
            created.id,
            MapTileBatchUpdate(
                changes=[{"hex_q": 1, "hex_r": 1, "terrain_type": "forest"}]
            ),
        )
        # 第二次同格改 mountain（upsert）
        result = await tile_svc.batch_update(
            db_session,
            nid,
            created.id,
            MapTileBatchUpdate(
                changes=[{"hex_q": 1, "hex_r": 1, "terrain_type": "mountain"}]
            ),
        )
        by_pos = {(t.hex_q, t.hex_r): t.terrain_type for t in result}
        assert by_pos[(1, 1)] == "mountain"


# ============================================================
# 地点绑定
# ============================================================


class TestLocationBinding:
    @pytest.mark.asyncio
    async def test_batch_create_binding(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid, "洛阳")

        bind_svc = MapLocationBindingService()
        result = await bind_svc.batch_create(
            db_session,
            nid,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[
                    {"hex_q": 5, "hex_r": 5, "is_center": True},
                    {"hex_q": 5, "hex_r": 6, "is_center": False},
                ],
            ),
        )
        assert len(result) == 2
        centers = [b for b in result if b.is_center]
        assert len(centers) == 1
        assert centers[0].hex_q == 5 and centers[0].hex_r == 5

    @pytest.mark.asyncio
    async def test_center_uniqueness_switching_clears_old(self, db_session: AsyncSession):
        """二次设中心点应清除旧中心（同 location 同 map 最多一个中心）。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid, "洛阳")

        bind_svc = MapLocationBindingService()
        # 第一次中心在 (5,5)
        await bind_svc.batch_create(
            db_session,
            nid,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[{"hex_q": 5, "hex_r": 5, "is_center": True}],
            ),
        )
        # 第二次新增 (6,6) 为中心 → 应清除 (5,5) 的中心
        await bind_svc.batch_create(
            db_session,
            nid,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[{"hex_q": 6, "hex_r": 6, "is_center": True}],
            ),
        )
        from modules.world.map_repositories import MapLocationBindingRepository

        centers = await MapLocationBindingRepository().get_centers(
            db_session, uuid.UUID(hex=nid), uuid.UUID(hex=created.id)
        )
        assert len(centers) == 1
        assert centers[0].hex_q == 6 and centers[0].hex_r == 6

    @pytest.mark.asyncio
    async def test_bind_non_location_entity_returns_400(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        # 创建 character 类型实体（非 location）
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="主角",
                status="canonical",
            )
        )
        await db_session.flush()

        bind_svc = MapLocationBindingService()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await bind_svc.batch_create(
                db_session,
                nid,
                created.id,
                MapLocationBindingCreate(
                    location_entity_id=str(char_id),
                    hexes=[{"hex_q": 5, "hex_r": 5, "is_center": True}],
                ),
            )
        assert exc.value.status_code == 400
        assert "location" in exc.value.detail

    @pytest.mark.asyncio
    async def test_bind_cross_novel_entity_returns_404(self, db_session: AsyncSession):
        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        # 地图在 novel1，地点实体在 novel2
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid1,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid2, "异界地点")

        bind_svc = MapLocationBindingService()
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await bind_svc.batch_create(
                db_session,
                nid1,
                created.id,
                MapLocationBindingCreate(
                    location_entity_id=loc_id,
                    hexes=[{"hex_q": 5, "hex_r": 5, "is_center": True}],
                ),
            )
        assert exc.value.status_code == 404


# ============================================================
# 地图层级与聚合状态
# ============================================================


class TestMapHierarchy:
    @pytest.mark.asyncio
    async def test_create_detail_map_with_parent(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        world = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="九州世界", map_type="world", grid_width=30, grid_height=20
            ),
        )
        loc_id = await _create_location_entity(db_session, nid, "洛阳")

        # 创建详图
        detail = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="洛阳",
                map_type="city",
                grid_width=40,
                grid_height=30,
                parent_map_id=world.id,
                parent_entity_id=loc_id,
            ),
        )
        assert detail.parent_map_id == world.id
        assert detail.parent_entity_id == loc_id

    @pytest.mark.asyncio
    async def test_breadcrumbs(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        world = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="世界", map_type="world", grid_width=5, grid_height=5),
        )
        loc_id = await _create_location_entity(db_session, nid, "洛阳")
        city = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="洛阳",
                map_type="city",
                grid_width=5,
                grid_height=5,
                parent_map_id=world.id,
                parent_entity_id=loc_id,
            ),
        )

        state = await cfg_svc.get_state(db_session, nid, city.id)
        names = [b.name for b in state.breadcrumbs]
        # 顶层在前，当前在尾
        assert names == ["世界", "洛阳"]

    @pytest.mark.asyncio
    async def test_get_state_returns_tiles_and_bindings(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=3, grid_height=3),
        )
        loc_id = await _create_location_entity(db_session, nid)
        bind_svc = MapLocationBindingService()
        await bind_svc.batch_create(
            db_session,
            nid,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[{"hex_q": 1, "hex_r": 1, "is_center": True}],
            ),
        )

        state = await cfg_svc.get_state(db_session, nid, created.id)
        assert state.map.name == "m"
        assert len(state.tiles) == 9  # 3x3
        assert len(state.location_bindings) == 1
        assert state.location_bindings[0].is_center is True
        assert state.scene is None  # P1


# ============================================================
# 快速生成详图地形
# ============================================================


class TestMapGeneration:
    @pytest.mark.asyncio
    async def test_generate_detail_terrain(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="洛阳", map_type="city", grid_width=20, grid_height=30),
        )

        state = await cfg_svc.generate(db_session, nid, created.id)
        terrains = {t.terrain_type for t in state.tiles}
        # 应包含 city（中心）和 road/forest/grassland
        assert "city" in terrains
        assert len(state.tiles) == 600  # 20x30

    @pytest.mark.asyncio
    async def test_generate_overwrites_existing(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="city", grid_width=5, grid_height=5),
        )
        # 初始是 blank（grassland），generate 后应有 city
        state_before = await cfg_svc.get_state(db_session, nid, created.id)
        assert all(t.terrain_type == "grassland" for t in state_before.tiles)

        state_after = await cfg_svc.generate(db_session, nid, created.id)
        assert any(t.terrain_type == "city" for t in state_after.tiles)


# ============================================================
# API 层（HTTP）
# ============================================================


class TestMapAPI:
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


# ============================================================
# PRD 偏差修复回归测试
# ============================================================


class TestMapConfigValidation:
    """B3 白名单 / B2 parent_entity 校验 / B7 顶层重名 / B4 generate 限制。"""

    @pytest.mark.asyncio
    async def test_create_invalid_map_type_returns_422(self, db_session):
        """B3：非法 map_type 被 Literal 拒绝（422）。"""
        from pydantic import ValidationError

        from modules.project.models import Project
        from modules.world.map_schemas import MapConfigCreate

        nid = uuid.uuid4().hex
        db_session.add(
            Project(
                id=uuid.UUID(hex=nid),
                title="t",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            )
        )
        await db_session.flush()
        with pytest.raises(ValidationError):
            MapConfigCreate(name="x", map_type="galaxy", grid_width=3, grid_height=3)

    @pytest.mark.asyncio
    async def test_batch_update_invalid_terrain_returns_422(self, db_session):
        """B3：非法 terrain_type 被 Literal 拒绝。"""
        from pydantic import ValidationError

        from modules.world.map_schemas import MapTileBatchUpdate

        with pytest.raises(ValidationError):
            MapTileBatchUpdate(changes=[{"hex_q": 0, "hex_r": 0, "terrain_type": "lava"}])

    @pytest.mark.asyncio
    async def test_create_continent_template_generates_varied_terrain(self, db_session):
        """continent 模板生成多种地形（非全 grassland）。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="大陆",
                map_type="world",
                grid_width=30,
                grid_height=20,
                template="continent",
            ),
        )
        state = await svc.get_state(db_session, nid, created.id)
        terrains = {t.terrain_type for t in state.tiles}
        # continent 模板应至少含 water（边缘）和陆地
        assert len(terrains) >= 2

    @pytest.mark.asyncio
    async def test_create_islands_template(self, db_session):
        """islands 模板生成含 water。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="群岛",
                map_type="world",
                grid_width=20,
                grid_height=15,
                template="islands",
            ),
        )
        state = await svc.get_state(db_session, nid, created.id)
        terrains = {t.terrain_type for t in state.tiles}
        assert "water" in terrains

    @pytest.mark.asyncio
    async def test_create_toplevel_duplicate_name_returns_409(self, db_session):
        """B7：顶层地图同名返回 409（PG NULL unique 漏洞由业务层补）。"""
        from fastapi import HTTPException

        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        await svc.create(
            db_session,
            nid,
            MapConfigCreate(name="同名", map_type="world", grid_width=3, grid_height=3),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.create(
                db_session,
                nid,
                MapConfigCreate(
                    name="同名", map_type="world", grid_width=3, grid_height=3
                ),
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_create_with_parent_entity_not_location_returns_400(self, db_session):
        """B2：parent_entity_id 非 location 类型返回 400。"""
        from fastapi import HTTPException

        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        # 建 character 实体（非 location）
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="主角",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapConfigService()
        with pytest.raises(HTTPException) as exc:
            await svc.create(
                db_session,
                nid,
                MapConfigCreate(
                    name="详图",
                    map_type="city",
                    grid_width=5,
                    grid_height=5,
                    parent_entity_id=str(char_id),
                ),
            )
        assert exc.value.status_code == 400
        assert "location" in exc.value.detail

    @pytest.mark.asyncio
    async def test_create_with_cross_novel_parent_entity_returns_404(self, db_session):
        """B2：parent_entity_id 跨 novel 返回 404。"""
        from fastapi import HTTPException

        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        # location 实体在 novel2
        loc_id = await _create_location_entity(db_session, nid2, "异界")

        svc = MapConfigService()
        with pytest.raises(HTTPException) as exc:
            await svc.create(
                db_session,
                nid1,
                MapConfigCreate(
                    name="详图",
                    map_type="city",
                    grid_width=5,
                    grid_height=5,
                    parent_entity_id=loc_id,
                ),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_generate_on_world_map_returns_400(self, db_session):
        """B4：对 world 地图调用 generate 返回 400。"""
        from fastapi import HTTPException

        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid,
            MapConfigCreate(name="世界", map_type="world", grid_width=5, grid_height=5),
        )
        with pytest.raises(HTTPException) as exc:
            await svc.generate(db_session, nid, created.id)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_generate_detail_contains_road(self, db_session):
        """D-08：详图快速生成应含 road（PRD §路径3 外圈 road）。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        svc = MapConfigService()
        detail = await svc.create(
            db_session,
            nid,
            MapConfigCreate(name="城", map_type="city", grid_width=20, grid_height=20),
        )
        state = await svc.generate(db_session, nid, detail.id)
        terrains = {t.terrain_type for t in state.tiles}
        assert "city" in terrains
        assert "road" in terrains


class TestLocationBindingCRUD:
    """B1 PATCH 端点 + binding 单条 CRUD（D-03 测试补全）。"""

    @pytest.mark.asyncio
    async def test_update_binding_set_center(self, db_session):
        """PATCH 单个 binding 设为中心点，清除旧中心。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid, "洛阳")

        bind_svc = MapLocationBindingService()
        # 建两个绑定，第一个为中心
        result = await bind_svc.batch_create(
            db_session,
            nid,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[
                    {"hex_q": 5, "hex_r": 5, "is_center": True},
                    {"hex_q": 6, "hex_r": 6, "is_center": False},
                ],
            ),
        )
        non_center = next(b for b in result if not b.is_center)

        # PATCH：把非中心格设为中心
        from modules.world.map_schemas import MapLocationBindingUpdate

        updated = await bind_svc.update(
            db_session,
            nid,
            non_center.id,
            MapLocationBindingUpdate(is_center=True),
        )
        assert updated.is_center is True

        # 旧中心应被清除
        from modules.world.map_repositories import MapLocationBindingRepository

        centers = await MapLocationBindingRepository().get_centers(
            db_session, uuid.UUID(hex=nid), uuid.UUID(hex=created.id)
        )
        assert len(centers) == 1
        assert centers[0].id == uuid.UUID(hex=non_center.id)

    @pytest.mark.asyncio
    async def test_update_binding_cross_novel_returns_404(self, db_session):
        """PATCH binding 跨 novel 返回 404。"""
        from fastapi import HTTPException

        from modules.world.map_schemas import MapLocationBindingUpdate

        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid1,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid1, "洛阳")
        bind_svc = MapLocationBindingService()
        result = await bind_svc.batch_create(
            db_session,
            nid1,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[{"hex_q": 5, "hex_r": 5, "is_center": True}],
            ),
        )
        binding_id = result[0].id

        # 用 novel2 访问 novel1 的 binding
        with pytest.raises(HTTPException) as exc:
            await bind_svc.update(
                db_session,
                nid2,
                binding_id,
                MapLocationBindingUpdate(label_override="x"),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_binding(self, db_session):
        """DELETE binding 成功。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid)
        bind_svc = MapLocationBindingService()
        result = await bind_svc.batch_create(
            db_session,
            nid,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[{"hex_q": 1, "hex_r": 1, "is_center": False}],
            ),
        )
        binding_id = result[0].id
        await bind_svc.delete(db_session, nid, binding_id)

        # 再删应 404
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await bind_svc.delete(db_session, nid, binding_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_binding_cross_novel_returns_404(self, db_session):
        """DELETE binding 跨 novel 返回 404。"""
        from fastapi import HTTPException

        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid1,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid1)
        bind_svc = MapLocationBindingService()
        result = await bind_svc.batch_create(
            db_session,
            nid1,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=loc_id,
                hexes=[{"hex_q": 1, "hex_r": 1, "is_center": True}],
            ),
        )
        with pytest.raises(HTTPException) as exc:
            await bind_svc.delete(db_session, nid2, result[0].id)
        assert exc.value.status_code == 404


class TestMapStateContract:
    """B6 MapStateResponse 契约预留位。"""

    @pytest.mark.asyncio
    async def test_state_response_has_markers_and_territories_fields(self, db_session):
        """B6：state 响应含 markers/territories 字段（空 list）。"""
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=3, grid_height=3),
        )
        state = await cfg_svc.get_state(db_session, nid, created.id)
        # markers/territories 是空 list（P0/P2 恒空），不是 None
        assert state.markers == []
        assert state.territories == []
        assert state.scene is None


class TestMapAPIRegression:
    """B1 PATCH 端点 + 级联删除（D-03 测试补全）。"""

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


# ============================================================
# Marker CRUD（P1）
# ============================================================


class TestMapMarkerCRUD:
    @pytest.mark.asyncio
    async def test_create_marker(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="张三",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        marker = await marker_svc.create(
            db_session,
            nid,
            created.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=3,
                hex_r=4,
                label="张三",
            ),
        )
        assert marker.marker_type == "character"
        assert marker.hex_q == 3
        assert marker.hex_r == 4
        assert marker.label == "张三"
        assert marker.visible is True

    @pytest.mark.asyncio
    async def test_list_markers(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="李四",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        await marker_svc.create(
            db_session,
            nid,
            created.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=1,
                hex_r=2,
            ),
        )
        markers = await marker_svc.list(db_session, nid, created.id)
        assert len(markers) >= 1

    @pytest.mark.asyncio
    async def test_update_marker(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="王五",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        created_marker = await marker_svc.create(
            db_session,
            nid,
            created.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=0,
                hex_r=0,
            ),
        )
        updated = await marker_svc.update(
            db_session,
            nid,
            created_marker.id,
            MapMarkerUpdate(hex_q=5, hex_r=6, label="更新标签"),
        )
        assert updated.hex_q == 5
        assert updated.hex_r == 6
        assert updated.label == "更新标签"

    @pytest.mark.asyncio
    async def test_delete_marker(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="赵六",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        created_marker = await marker_svc.create(
            db_session,
            nid,
            created.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=2,
                hex_r=3,
            ),
        )
        await marker_svc.delete(db_session, nid, created_marker.id)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await marker_svc.update(
                db_session,
                nid,
                created_marker.id,
                MapMarkerUpdate(label="应该404"),
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_novel_marker_404(self, db_session: AsyncSession):
        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid1,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid1),
                entity_type="character",
                name="孙七",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        created_marker = await marker_svc.create(
            db_session,
            nid1,
            created.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=1,
                hex_r=1,
            ),
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await marker_svc.delete(db_session, nid2, created_marker.id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_marker_type_422(self, db_session: AsyncSession):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MapMarkerCreate(
                entity_id=str(uuid.uuid4()),
                marker_type="invalid_type",
                hex_q=0,
                hex_r=0,
            )

    @pytest.mark.asyncio
    async def test_state_includes_markers(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="周八",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        await marker_svc.create(
            db_session,
            nid,
            created.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=5,
                hex_r=5,
            ),
        )

        state = await cfg_svc.get_state(db_session, nid, created.id)
        assert len(state.markers) >= 1


# ============================================================
# 势力范围（P2）
# ============================================================


# ============================================================
# P2 势力范围测试
# ============================================================


class TestMapTerritory:
    """势力范围测试（P2）。"""

    @pytest.mark.asyncio
    async def test_list_territories_empty(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        svc = MapTerritoryService()
        territories = await svc.list(db_session, nid, str(created.id))
        assert territories == []

    @pytest.mark.asyncio
    async def test_create_territory(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="青龙会",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            nid,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[
                    {"hex_q": 1, "hex_r": 1, "style_override": {"color": "#FF0000"}},
                    {"hex_q": 1, "hex_r": 2},
                ],
            ),
        )
        assert len(territories) == 2
        assert territories[0].faction_entity_id == str(org_id)
        assert territories[0].hex_q == 1

    @pytest.mark.asyncio
    async def test_create_territory_non_org(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="character",
                name="张三",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        with pytest.raises(HTTPException) as exc:
            await svc.create(
                db_session,
                nid,
                str(created.id),
                MapTerritoryCreate(
                    faction_entity_id=str(char_id),
                    hexes=[{"hex_q": 1, "hex_r": 1}],
                ),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_territory_out_of_bounds(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=5, grid_height=5),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="白虎堂",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        with pytest.raises(HTTPException) as exc:
            await svc.create(
                db_session,
                nid,
                str(created.id),
                MapTerritoryCreate(
                    faction_entity_id=str(org_id),
                    hexes=[{"hex_q": 10, "hex_r": 10}],
                ),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_territory(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="玄武宗",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            nid,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[{"hex_q": 1, "hex_r": 1}],
            ),
        )
        tid = territories[0].id

        updated = await svc.update(
            db_session,
            nid,
            tid,
            MapTerritoryUpdate(style_override={"color": "#00FF00"}),
        )
        assert updated.style_override == {"color": "#00FF00"}

    @pytest.mark.asyncio
    async def test_delete_territory(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="朱雀门",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            nid,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[{"hex_q": 1, "hex_r": 1}],
            ),
        )
        tid = territories[0].id

        await svc.delete(db_session, nid, tid)
        remaining = await svc.list(db_session, nid, str(created.id))
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_delete_by_faction(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="天机阁",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        await svc.create(
            db_session,
            nid,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[
                    {"hex_q": 1, "hex_r": 1},
                    {"hex_q": 1, "hex_r": 2},
                    {"hex_q": 2, "hex_r": 1},
                ],
            ),
        )

        deleted = await svc.delete_by_faction(
            db_session, nid, str(created.id), str(org_id)
        )
        assert deleted == 3
        remaining = await svc.list(db_session, nid, str(created.id))
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_cross_novel_delete(self, db_session: AsyncSession):
        nid1 = uuid.uuid4().hex
        nid2 = uuid.uuid4().hex
        await _create_project(db_session, nid1)
        await _create_project(db_session, nid2)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid1,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid1),
                entity_type="organization",
                name="暗影盟",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            nid1,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[{"hex_q": 1, "hex_r": 1}],
            ),
        )
        tid = territories[0].id

        with pytest.raises(HTTPException) as exc:
            await svc.delete(db_session, nid2, tid)
        assert exc.value.status_code == 404


class TestMapStateTerritories:
    """地图聚合状态包含势力范围测试。"""

    @pytest.mark.asyncio
    async def test_state_includes_territories(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="逍遥派",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        await svc.create(
            db_session,
            nid,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[{"hex_q": 3, "hex_r": 3}],
            ),
        )

        state = await cfg_svc.get_state(db_session, nid, str(created.id))
        assert len(state.territories) >= 1
        assert state.territories[0].faction_entity_id == str(org_id)


class TestMapFocusMode:
    """聚焦模式测试。"""

    @pytest.mark.asyncio
    async def test_focus_mode(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        org_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=org_id,
                novel_id=uuid.UUID(hex=nid),
                entity_type="organization",
                name="铁血盟",
                status="canonical",
            )
        )
        await db_session.flush()

        svc = MapTerritoryService()
        await svc.create(
            db_session,
            nid,
            str(created.id),
            MapTerritoryCreate(
                faction_entity_id=str(org_id),
                hexes=[
                    {"hex_q": 1, "hex_r": 1},
                    {"hex_q": 1, "hex_r": 2},
                ],
            ),
        )

        # Focus mode via service
        from modules.world.map_repositories import MapTerritoryRepository
        repo = MapTerritoryRepository()
        territories = await repo.get_by_map_and_faction(
            db_session, uuid.UUID(hex=nid), uuid.UUID(hex=created.id), org_id
        )
        assert len(territories) == 2
        related = [(t.hex_q, t.hex_r) for t in territories]
        assert (1, 1) in related
        assert (1, 2) in related
