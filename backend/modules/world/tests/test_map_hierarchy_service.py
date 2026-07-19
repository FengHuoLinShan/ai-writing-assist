"""test_map_hierarchy_service — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.map_repositories import MapConfigRepository
from modules.world.map_schemas import (
    MapConfigCreate,
    MapConfigUpdate,
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
    async def test_breadcrumbs_three_level_chain(self, db_session: AsyncSession):
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
        inner_loc_id = await _create_location_entity(db_session, nid, "内城")
        inner = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="内城",
                map_type="region",
                grid_width=5,
                grid_height=5,
                parent_map_id=city.id,
                parent_entity_id=inner_loc_id,
            ),
        )

        state = await cfg_svc.get_state(db_session, nid, inner.id)
        names = [b.name for b in state.breadcrumbs]
        # 顶层在前，当前在尾
        assert names == ["世界", "洛阳", "内城"]

    @pytest.mark.asyncio
    async def test_breadcrumbs_parent_cycle_stops_and_preserves_order(
        self, db_session: AsyncSession
    ):
        nid = uuid.uuid4().hex
        await _create_project(db_session, nid)
        cfg_svc = MapConfigService()
        world = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(name="世界", map_type="world", grid_width=5, grid_height=5),
        )
        city_loc_id = await _create_location_entity(db_session, nid, "洛阳")
        city = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="洛阳",
                map_type="city",
                grid_width=5,
                grid_height=5,
                parent_map_id=world.id,
                parent_entity_id=city_loc_id,
            ),
        )
        inner_loc_id = await _create_location_entity(db_session, nid, "内城")
        inner = await cfg_svc.create(
            db_session,
            nid,
            MapConfigCreate(
                name="内城",
                map_type="region",
                grid_width=5,
                grid_height=5,
                parent_map_id=city.id,
                parent_entity_id=inner_loc_id,
            ),
        )

        repo = MapConfigRepository()
        await repo.update(
            db_session,
            uuid.UUID(hex=world.id),
            {"parent_map_id": uuid.UUID(hex=inner.id)},
        )

        breadcrumbs = await repo.get_breadcrumbs(db_session, uuid.UUID(hex=inner.id))
        assert [b.name for b in breadcrumbs] == ["世界", "洛阳", "内城"]

    @pytest.mark.asyncio
    async def test_update_reparents_existing_map_and_can_promote_it_to_root(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = uuid.uuid4().hex
        await _create_project(db_session, novel_id)
        service = MapConfigService()
        world = await service.create(
            db_session,
            novel_id,
            MapConfigCreate(
                name="世界",
                map_type="world",
                grid_width=8,
                grid_height=8,
            ),
        )
        detached = await service.create(
            db_session,
            novel_id,
            MapConfigCreate(
                name="廷根城",
                map_type="region",
                grid_width=8,
                grid_height=8,
            ),
        )
        tingen_id = await _create_location_entity(db_session, novel_id, "廷根市")

        nested = await service.update(
            db_session,
            detached.id,
            MapConfigUpdate(
                parent_map_id=world.id,
                parent_entity_id=tingen_id,
            ),
            novel_id=novel_id,
        )

        assert nested.parent_map_id == world.id
        assert nested.parent_entity_id == tingen_id
        nested_state = await service.get_state(db_session, novel_id, detached.id)
        assert [item.name for item in nested_state.breadcrumbs] == ["世界", "廷根城"]

        promoted = await service.update(
            db_session,
            detached.id,
            MapConfigUpdate(parent_map_id=None, parent_entity_id=None),
            novel_id=novel_id,
        )

        assert promoted.parent_map_id is None
        assert promoted.parent_entity_id is None

    @pytest.mark.asyncio
    async def test_update_rejects_reparenting_map_below_its_descendant(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = uuid.uuid4().hex
        await _create_project(db_session, novel_id)
        service = MapConfigService()
        world = await service.create(
            db_session,
            novel_id,
            MapConfigCreate(
                name="世界",
                map_type="world",
                grid_width=8,
                grid_height=8,
            ),
        )
        city = await service.create(
            db_session,
            novel_id,
            MapConfigCreate(
                name="廷根城",
                map_type="city",
                grid_width=8,
                grid_height=8,
                parent_map_id=world.id,
            ),
        )
        detail = await service.create(
            db_session,
            novel_id,
            MapConfigCreate(
                name="教堂详图",
                map_type="dungeon",
                grid_width=8,
                grid_height=8,
                parent_map_id=city.id,
            ),
        )

        with pytest.raises(ValidationError) as exc_info:
            await service.update(
                db_session,
                world.id,
                MapConfigUpdate(parent_map_id=detail.id),
                novel_id=novel_id,
            )

        assert exc_info.value.code == "map_hierarchy_cycle"

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
