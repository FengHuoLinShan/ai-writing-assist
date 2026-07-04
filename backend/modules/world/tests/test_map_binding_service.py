"""test_map_binding_service — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.map_schemas import (
    MapConfigCreate,
    MapLocationBindingCreate,
)
from modules.world.models import CoreEntity
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
)
from modules.world.tests.helpers import (
    _create_location_entity,
)


class TestMapLocationBindingService:
    """TestMapLocationBindingService 测试集合。"""

    @pytest.mark.asyncio
    async def test_batch_create_binding(
        self,
        db_session: AsyncSession,
        world_map,
        location_entity_id: str,
    ):
        bind_svc = MapLocationBindingService()
        result = await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
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
    async def test_center_uniqueness_switching_clears_old(
        self,
        db_session: AsyncSession,
        world_map,
        location_entity_id: str,
    ):
        """二次设中心点应清除旧中心（同 location 同 map 最多一个中心）。"""
        bind_svc = MapLocationBindingService()
        # 第一次中心在 (5,5)
        await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
                hexes=[{"hex_q": 5, "hex_r": 5, "is_center": True}],
            ),
        )
        # 第二次新增 (6,6) 为中心 → 应清除 (5,5) 的中心
        await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
                hexes=[{"hex_q": 6, "hex_r": 6, "is_center": True}],
            ),
        )
        from modules.world.map_repositories import MapLocationBindingRepository

        centers = await MapLocationBindingRepository().get_centers(
            db_session,
            uuid.UUID(hex=world_map.novel_id),
            uuid.UUID(hex=world_map.id),
        )
        assert len(centers) == 1
        assert centers[0].hex_q == 6 and centers[0].hex_r == 6

    @pytest.mark.asyncio
    async def test_repository_get_by_hexes_for_entity_statuses(
        self,
        db_session: AsyncSession,
        world_map,
        location_entity_id: str,
    ):
        from modules.world.map_repositories import MapLocationBindingRepository

        bind_svc = MapLocationBindingService()
        await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
                hexes=[
                    {"hex_q": 5, "hex_r": 5, "is_center": True},
                    {"hex_q": 5, "hex_r": 6, "is_center": False},
                    {"hex_q": 6, "hex_r": 6, "is_center": False},
                ],
            ),
        )
        candidate_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=candidate_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="location",
                name="候选地点",
                status="candidate",
            )
        )
        await db_session.flush()
        await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=str(candidate_id),
                hexes=[{"hex_q": 5, "hex_r": 5}],
            ),
        )
        other_map = await MapConfigService().create(
            db_session,
            world_map.novel_id,
            MapConfigCreate(
                name="other",
                map_type="world",
                grid_width=10,
                grid_height=10,
            ),
        )
        await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            other_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
                hexes=[{"hex_q": 5, "hex_r": 5}],
            ),
        )

        rows = await MapLocationBindingRepository().get_by_hexes_for_entity_statuses(
            db_session,
            uuid.UUID(hex=world_map.novel_id),
            uuid.UUID(hex=world_map.id),
            [(5, 5), (5, 6), (5, 5)],
            statuses=["canonical"],
        )

        assert [(row.hex_q, row.hex_r) for row in rows] == [(5, 5), (5, 6)]
        assert {row.location_entity_id for row in rows} == {
            uuid.UUID(hex=location_entity_id)
        }

    @pytest.mark.asyncio
    async def test_bind_non_location_entity_returns_400(
        self, db_session: AsyncSession, world_map
    ):
        # 创建 character 类型实体（非 location）
        char_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=char_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="character",
                name="主角",
                status="canonical",
            )
        )
        await db_session.flush()

        bind_svc = MapLocationBindingService()

        with pytest.raises(DomainError) as exc:
            await bind_svc.batch_create(
                db_session,
                world_map.novel_id,
                world_map.id,
                MapLocationBindingCreate(
                    location_entity_id=str(char_id),
                    hexes=[{"hex_q": 5, "hex_r": 5, "is_center": True}],
                ),
            )
        assert exc.value.status_code == 400
        assert "location" in exc.value.detail

    @pytest.mark.asyncio
    async def test_bind_cross_novel_entity_returns_404(
        self, db_session: AsyncSession, two_projects: tuple[str, str]
    ):
        nid1, nid2 = two_projects
        # 地图在 novel1，地点实体在 novel2
        cfg_svc = MapConfigService()
        created = await cfg_svc.create(
            db_session,
            nid1,
            MapConfigCreate(name="m", map_type="world", grid_width=10, grid_height=10),
        )
        loc_id = await _create_location_entity(db_session, nid2, "异界地点")

        bind_svc = MapLocationBindingService()

        with pytest.raises(DomainError) as exc:
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

    @pytest.mark.asyncio
    async def test_update_binding_set_center(
        self,
        db_session,
        world_map,
        location_entity_id: str,
    ):
        """PATCH 单个 binding 设为中心点，清除旧中心。"""
        bind_svc = MapLocationBindingService()
        # 建两个绑定，第一个为中心
        result = await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
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
            world_map.novel_id,
            non_center.id,
            MapLocationBindingUpdate(is_center=True),
        )
        assert updated.is_center is True

        # 旧中心应被清除
        from modules.world.map_repositories import MapLocationBindingRepository

        centers = await MapLocationBindingRepository().get_centers(
            db_session,
            uuid.UUID(hex=world_map.novel_id),
            uuid.UUID(hex=world_map.id),
        )
        assert len(centers) == 1
        assert centers[0].id == uuid.UUID(hex=non_center.id)

    @pytest.mark.parametrize("operation", ["update", "delete"])
    @pytest.mark.asyncio
    async def test_binding_cross_novel_returns_404(
        self, db_session, two_projects: tuple[str, str], operation: str
    ):
        """binding update/delete 跨 novel 返回 404。"""

        from modules.world.map_schemas import MapLocationBindingUpdate

        nid1, nid2 = two_projects
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

        with pytest.raises(DomainError) as exc:
            if operation == "update":
                await bind_svc.update(
                    db_session,
                    nid2,
                    binding_id,
                    MapLocationBindingUpdate(label_override="x"),
                )
            else:
                await bind_svc.delete(db_session, nid2, binding_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_binding(
        self,
        db_session,
        world_map,
        location_entity_id: str,
    ):
        """DELETE binding 成功。"""
        bind_svc = MapLocationBindingService()
        result = await bind_svc.batch_create(
            db_session,
            world_map.novel_id,
            world_map.id,
            MapLocationBindingCreate(
                location_entity_id=location_entity_id,
                hexes=[{"hex_q": 1, "hex_r": 1, "is_center": False}],
            ),
        )
        binding_id = result[0].id
        await bind_svc.delete(db_session, world_map.novel_id, binding_id)

        # 再删应 404

        with pytest.raises(DomainError) as exc:
            await bind_svc.delete(db_session, world_map.novel_id, binding_id)
        assert exc.value.status_code == 404
