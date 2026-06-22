"""test_map_marker_service — 由 test_map.py 拆分生成。"""

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



class TestMapMarkerCRUD:
    """TestMapMarkerCRUD 测试集合。"""
    @pytest.mark.asyncio
    async def test_create_marker(self, db_session: AsyncSession, world_map):
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="character",
                name="张三",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        marker = await marker_svc.create(
            db_session,
            world_map.novel_id,
            world_map.id,
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
    async def test_list_markers(self, db_session: AsyncSession, world_map):
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="character",
                name="李四",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        await marker_svc.create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=1,
                hex_r=2,
            ),
        )
        markers = await marker_svc.list(db_session, world_map.novel_id, world_map.id)
        assert len(markers) >= 1


    @pytest.mark.asyncio
    async def test_update_marker(self, db_session: AsyncSession, world_map):
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="character",
                name="王五",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        created_marker = await marker_svc.create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=0,
                hex_r=0,
            ),
        )
        updated = await marker_svc.update(
            db_session,
            world_map.novel_id,
            created_marker.id,
            MapMarkerUpdate(hex_q=5, hex_r=6, label="更新标签"),
        )
        assert updated.hex_q == 5
        assert updated.hex_r == 6
        assert updated.label == "更新标签"


    @pytest.mark.asyncio
    async def test_delete_marker(self, db_session: AsyncSession, world_map):
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="character",
                name="赵六",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        created_marker = await marker_svc.create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=2,
                hex_r=3,
            ),
        )
        await marker_svc.delete(db_session, world_map.novel_id, created_marker.id)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await marker_svc.update(
                db_session,
                world_map.novel_id,
                created_marker.id,
                MapMarkerUpdate(label="应该404"),
            )
        assert exc.value.status_code == 404


    @pytest.mark.asyncio
    async def test_cross_novel_marker_404(
        self, db_session: AsyncSession, two_projects: tuple[str, str]
    ):
        nid1, nid2 = two_projects
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
    async def test_state_includes_markers(self, db_session: AsyncSession, world_map):
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="character",
                name="周八",
                status="canonical",
            )
        )
        await db_session.flush()

        marker_svc = MapMarkerService()
        await marker_svc.create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapMarkerCreate(
                entity_id=str(char_id),
                marker_type="character",
                hex_q=5,
                hex_r=5,
            ),
        )

        cfg_svc = MapConfigService()
        state = await cfg_svc.get_state(db_session, world_map.novel_id, world_map.id)
        assert len(state.markers) >= 1
