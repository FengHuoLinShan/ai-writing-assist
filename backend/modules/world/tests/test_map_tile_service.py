"""test_map_tile_service — 由 test_map.py 拆分生成。"""

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



class TestMapTileService:
    """TestMapTileService 测试集合。"""
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
