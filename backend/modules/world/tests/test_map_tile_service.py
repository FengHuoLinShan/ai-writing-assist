"""test_map_tile_service — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.map_repositories import MapTileRepository
from modules.world.map_schemas import (
    MapConfigCreate,
    MapTileBatchUpdate,
)
from modules.world.services.map_service import (
    MapConfigService,
    MapTileService,
)
from modules.world.tests.helpers import (
    _create_map_config,
    _create_project,
)


class TestMapTileService:
    """TestMapTileService 测试集合。"""

    @pytest.mark.asyncio
    async def test_bulk_upsert_empty_changes_returns_zero(self, db_session: AsyncSession):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        config = await _create_map_config(db_session, nid)

        repo = MapTileRepository()
        count = await repo.bulk_upsert(
            db_session,
            uuid.UUID(hex=nid),
            config.id,
            [],
        )

        assert count == 0
        assert await repo.get_by_map(db_session, uuid.UUID(hex=nid), config.id) == []

    @pytest.mark.asyncio
    async def test_bulk_upsert_multi_values_insert_update_and_count(
        self, db_session: AsyncSession
    ):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        config = await _create_map_config(db_session, nid)

        repo = MapTileRepository()
        inserted_count = await repo.bulk_upsert(
            db_session,
            uuid.UUID(hex=nid),
            config.id,
            [
                {"hex_q": 0, "hex_r": 0, "terrain_type": "water", "elevation": -1},
                {"hex_q": 1, "hex_r": 0, "terrain_type": "forest", "elevation": 2},
                {"hex_q": 2, "hex_r": 0, "terrain_type": "road"},
            ],
        )
        assert inserted_count == 3

        updated_count = await repo.bulk_upsert(
            db_session,
            uuid.UUID(hex=nid),
            config.id,
            [
                {"hex_q": 1, "hex_r": 0, "terrain_type": "mountain", "elevation": 5},
                {"hex_q": 2, "hex_r": 0, "terrain_type": "city", "elevation": 1},
            ],
        )
        assert updated_count == 2

        tiles = await repo.get_by_map(db_session, uuid.UUID(hex=nid), config.id)
        by_pos = {(tile.hex_q, tile.hex_r): tile for tile in tiles}
        assert len(by_pos) == 3
        assert by_pos[(0, 0)].terrain_type == "water"
        assert by_pos[(1, 0)].terrain_type == "mountain"
        assert by_pos[(1, 0)].elevation == 5
        assert by_pos[(2, 0)].terrain_type == "city"
        assert by_pos[(2, 0)].elevation == 1

    @pytest.mark.asyncio
    async def test_bulk_upsert_duplicate_coordinates_last_change_wins(
        self, db_session: AsyncSession
    ):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        config = await _create_map_config(db_session, nid)

        repo = MapTileRepository()
        count = await repo.bulk_upsert(
            db_session,
            uuid.UUID(hex=nid),
            config.id,
            [
                {"hex_q": 0, "hex_r": 0, "terrain_type": "forest", "elevation": 1},
                {"hex_q": 0, "hex_r": 0, "terrain_type": "mountain", "elevation": 3},
            ],
        )

        tiles = await repo.get_by_map(db_session, uuid.UUID(hex=nid), config.id)
        assert count == 2
        assert len(tiles) == 1
        assert tiles[0].terrain_type == "mountain"
        assert tiles[0].elevation == 3

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

        with pytest.raises(DomainError) as exc:
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
