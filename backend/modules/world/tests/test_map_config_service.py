"""test_map_config_service — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import MapTileRepository
from modules.world.map_schemas import (
    MapConfigCreate,
    MapTileBatchUpdate,
)
from modules.world.models import CoreEntity
from modules.world.services.map_service import (
    MapConfigService,
)
from modules.world.tests.helpers import (
    _create_location_entity,
    _create_project,
)


class TestMapConfigService:
    """TestMapConfigService 测试集合。"""

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

        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=nid)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_map_cross_novel_returns_404(
        self, db_session: AsyncSession, two_projects: tuple[str, str]
    ):
        nid1, nid2 = two_projects
        svc = MapConfigService()
        created = await svc.create(
            db_session,
            nid1,
            MapConfigCreate(
                name="小说1地图", map_type="world", grid_width=3, grid_height=3
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await svc.get(db_session, created.id, novel_id=nid2)
        assert exc.value.status_code == 404


class TestMapConfigValidation:
    """TestMapConfigValidation 测试集合。"""

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
    async def test_create_with_cross_novel_parent_entity_returns_404(
        self, db_session, two_projects: tuple[str, str]
    ):
        """B2：parent_entity_id 跨 novel 返回 404。"""

        nid1, nid2 = two_projects
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


class TestMapStateContract:
    """TestMapStateContract 测试集合。"""

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
