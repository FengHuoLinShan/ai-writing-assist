"""test_map_territory_service — 由 test_map.py 拆分生成。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.map_repositories import MapTerritoryRepository
from modules.world.map_schemas import (
    MapConfigCreate,
    MapTerritoryCreate,
    MapTerritoryUpdate,
)
from modules.world.models import CoreEntity
from modules.world.services.map_service import (
    MapConfigService,
    MapTerritoryService,
)
from modules.world.tests.helpers import (
    _create_project,
)


class TestMapTerritoryService:
    """TestMapTerritoryService 测试集合。"""

    @pytest.mark.asyncio
    async def test_list_territories_empty(self, db_session: AsyncSession, world_map):
        svc = MapTerritoryService()
        territories = await svc.list(db_session, world_map.novel_id, str(world_map.id))
        assert territories == []

    @pytest.mark.asyncio
    async def test_create_territory(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[
                    {"hex_q": 1, "hex_r": 1, "style_override": {"color": "#FF0000"}},
                    {"hex_q": 1, "hex_r": 2},
                ],
            ),
        )
        assert len(territories) == 2
        assert territories[0].faction_entity_id == organization_entity_id
        assert territories[0].hex_q == 1

    @pytest.mark.asyncio
    async def test_repository_get_by_hexes_batches_unique_hexes(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[
                    {"hex_q": 1, "hex_r": 1},
                    {"hex_q": 1, "hex_r": 2},
                    {"hex_q": 2, "hex_r": 1},
                ],
            ),
        )
        other_map = await MapConfigService().create(
            db_session,
            world_map.novel_id,
            MapConfigCreate(name="other", map_type="world", grid_width=5, grid_height=5),
        )
        await svc.create(
            db_session,
            world_map.novel_id,
            str(other_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[{"hex_q": 1, "hex_r": 1}],
            ),
        )

        rows = await MapTerritoryRepository().get_by_hexes(
            db_session,
            uuid.UUID(hex=world_map.novel_id),
            uuid.UUID(hex=world_map.id),
            [(1, 1), (1, 2), (1, 1)],
        )

        assert [(row.hex_q, row.hex_r) for row in rows] == [(1, 1), (1, 2)]

    @pytest.mark.asyncio
    async def test_create_territory_non_org(self, db_session: AsyncSession, world_map):
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

        svc = MapTerritoryService()
        with pytest.raises(DomainError) as exc:
            await svc.create(
                db_session,
                world_map.novel_id,
                str(world_map.id),
                MapTerritoryCreate(
                    faction_entity_id=str(char_id),
                    hexes=[{"hex_q": 1, "hex_r": 1}],
                ),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_create_territory_rejects_pending_compatibility_shadow(
        self,
        db_session: AsyncSession,
        world_map,
    ) -> None:
        shadow_id = uuid.uuid4()
        db_session.add(
            CoreEntity(
                id=shadow_id,
                novel_id=uuid.UUID(hex=world_map.novel_id),
                entity_type="organization",
                name="AI 待处理势力",
                status="candidate",
                content_json={
                    "_meta": {
                        "compatibility_shadow": True,
                        "suggestion_id": str(uuid.uuid4()),
                    }
                },
            )
        )
        await db_session.flush()

        with pytest.raises(DomainError) as exc:
            await MapTerritoryService().create(
                db_session,
                world_map.novel_id,
                str(world_map.id),
                MapTerritoryCreate(
                    faction_entity_id=str(shadow_id),
                    hexes=[{"hex_q": 1, "hex_r": 1}],
                ),
            )

        assert exc.value.status_code == 400
        assert exc.value.code == "unadopted_map_entity"

        legacy = await MapTerritoryRepository().create_batch(
            db_session,
            uuid.UUID(hex=world_map.novel_id),
            uuid.UUID(hex=world_map.id),
            shadow_id,
            [{"hex_q": 1, "hex_r": 1, "style_override": {}}],
        )
        listed = await MapTerritoryService().list(
            db_session,
            world_map.novel_id,
            str(world_map.id),
        )
        assert {item.id for item in listed}.isdisjoint({str(item.id) for item in legacy})

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
        with pytest.raises(DomainError) as exc:
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
    async def test_update_territory(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[{"hex_q": 1, "hex_r": 1}],
            ),
        )
        tid = territories[0].id

        updated = await svc.update(
            db_session,
            world_map.novel_id,
            tid,
            MapTerritoryUpdate(style_override={"color": "#00FF00"}),
        )
        assert updated.style_override == {"color": "#00FF00"}

    @pytest.mark.asyncio
    async def test_delete_territory(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        territories = await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[{"hex_q": 1, "hex_r": 1}],
            ),
        )
        tid = territories[0].id

        await svc.delete(db_session, world_map.novel_id, tid)
        remaining = await svc.list(db_session, world_map.novel_id, str(world_map.id))
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_delete_by_faction(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[
                    {"hex_q": 1, "hex_r": 1},
                    {"hex_q": 1, "hex_r": 2},
                    {"hex_q": 2, "hex_r": 1},
                ],
            ),
        )

        deleted = await svc.delete_by_faction(
            db_session, world_map.novel_id, str(world_map.id), organization_entity_id
        )
        assert deleted == 3
        remaining = await svc.list(db_session, world_map.novel_id, str(world_map.id))
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_cross_novel_delete(
        self, db_session: AsyncSession, two_projects: tuple[str, str]
    ):
        nid1, nid2 = two_projects
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

        with pytest.raises(DomainError) as exc:
            await svc.delete(db_session, nid2, tid)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_state_includes_territories(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
                hexes=[{"hex_q": 3, "hex_r": 3}],
            ),
        )

        cfg_svc = MapConfigService()
        state = await cfg_svc.get_state(db_session, world_map.novel_id, str(world_map.id))
        assert len(state.territories) >= 1
        assert state.territories[0].faction_entity_id == organization_entity_id

    @pytest.mark.asyncio
    async def test_focus_mode(
        self,
        db_session: AsyncSession,
        world_map,
        organization_entity_id: str,
    ):
        svc = MapTerritoryService()
        await svc.create(
            db_session,
            world_map.novel_id,
            str(world_map.id),
            MapTerritoryCreate(
                faction_entity_id=organization_entity_id,
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
            db_session,
            uuid.UUID(hex=world_map.novel_id),
            uuid.UUID(hex=world_map.id),
            uuid.UUID(hex=organization_entity_id),
        )
        assert len(territories) == 2
        related = [(t.hex_q, t.hex_r) for t in territories]
        assert (1, 1) in related
        assert (1, 2) in related
