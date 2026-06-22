"""test_map_generation_service — 由 test_map.py 拆分生成。"""

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



class TestMapGenerationService:
    """TestMapGenerationService 测试集合。"""
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
