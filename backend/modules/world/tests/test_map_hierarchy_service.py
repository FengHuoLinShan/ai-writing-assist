"""test_map_hierarchy_service — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapConfigCreate,
    MapLocationBindingCreate,
)
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
)
from modules.world.tests.helpers import (
    _create_location_entity,
    _create_project,
)


class TestMapHierarchyService:
    """TestMapHierarchyService 测试集合。"""

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
