from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.world.map_models import MapVisualRevision
from modules.world.map_repositories import (
    MapConfigRepository,
    MapLocationBindingRepository,
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapConfigUpdate,
    MapLocationBindingCreate,
    MapTerritoryCreate,
    MapTileBatchUpdate,
    MapTileChange,
    TerritoryHex,
)
from modules.world.models import CoreEntity
from modules.world.services.map.map_revision import MapRevisionService
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
    MapTerritoryService,
    MapTileService,
)
from modules.world.tests.helpers import _create_project


async def _current_revision(
    db: AsyncSession,
    novel_id: str,
    map_id: str,
) -> int:
    config = await MapConfigRepository().get_in_novel(
        db,
        uuid.UUID(novel_id),
        uuid.UUID(map_id),
    )
    assert config is not None
    return config.editor_revision


@pytest.mark.asyncio
async def test_visual_revision_restores_baseline_and_creates_new_revision(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(
            name="可逆地图",
            map_type="world",
            grid_width=4,
            grid_height=4,
        ),
    )
    before = await MapConfigService().get_state(db_session, novel_id, created.id)
    original = next(item for item in before.tiles if item.hex_q == 0 and item.hex_r == 0)
    replacement = "water" if original.terrain_type != "water" else "forest"

    await MapTileService().batch_update(
        db_session,
        novel_id,
        created.id,
        MapTileBatchUpdate(
            changes=[
                MapTileChange(
                    hex_q=0,
                    hex_r=0,
                    terrain_type=replacement,
                )
            ]
        ),
    )

    history = await MapRevisionService().list_revisions(
        db_session,
        novel_id,
        created.id,
    )
    assert [item.revision_number for item in history.items] == [1, 0]
    assert history.items[1].operation == "baseline"
    tile_change = next(
        item
        for item in history.items[0].forward_changes
        if item["resource_type"] == "map_tiles"
        and item["after"]["hex_q"] == 0
        and item["after"]["hex_r"] == 0
    )
    assert tile_change["before"]["terrain_type"] == original.terrain_type
    assert tile_change["after"]["terrain_type"] == replacement

    restored = await MapRevisionService().restore_revision(
        db_session,
        novel_id,
        created.id,
        0,
        expected_revision=1,
    )
    assert restored.editor_revision == 2
    state = await MapConfigService().get_state(db_session, novel_id, created.id)
    current = next(item for item in state.tiles if item.hex_q == 0 and item.hex_r == 0)
    assert current.terrain_type == original.terrain_type
    latest = (
        await MapRevisionService().list_revisions(
            db_session,
            novel_id,
            created.id,
            limit=1,
        )
    ).items[0]
    assert latest.operation == "revision_restore"
    assert latest.restored_from_revision == 0


@pytest.mark.asyncio
async def test_config_patch_participates_in_visual_revision_history(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    service = MapConfigService()
    created = await service.create(
        db_session,
        novel_id,
        MapConfigCreate(
            name="旧地图名",
            map_type="world",
            grid_width=3,
            grid_height=3,
        ),
    )

    updated = await service.update(
        db_session,
        created.id,
        MapConfigUpdate(name="新地图名", default_zoom=1.5),
        novel_id=novel_id,
    )

    assert updated.editor_revision == 1
    history = await MapRevisionService().list_revisions(
        db_session,
        novel_id,
        created.id,
    )
    assert [item.revision_number for item in history.items] == [1, 0]
    assert history.items[0].operation == "config_update"
    assert any(
        item["resource_type"] == "map_configs"
        and item["before"]["name"] == "旧地图名"
        and item["after"]["name"] == "新地图名"
        for item in history.items[0].forward_changes
    )

    restored = await MapRevisionService().restore_revision(
        db_session,
        novel_id,
        created.id,
        0,
        expected_revision=1,
    )
    assert restored.editor_revision == 2
    current = await service.get(db_session, created.id, novel_id=novel_id)
    assert current.name == "旧地图名"
    assert current.default_zoom == 0


@pytest.mark.asyncio
async def test_revision_restore_rejects_cross_novel_resource_state(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(
            name="损坏快照门禁",
            map_type="world",
            grid_width=2,
            grid_height=2,
        ),
    )
    await MapTileService().batch_update(
        db_session,
        novel_id,
        created.id,
        MapTileBatchUpdate(
            changes=[MapTileChange(hex_q=0, hex_r=0, terrain_type="water")]
        ),
    )
    baseline = (
        await db_session.execute(
            select(MapVisualRevision).where(
                MapVisualRevision.map_id == uuid.UUID(created.id),
                MapVisualRevision.revision_number == 0,
            )
        )
    ).scalar_one()
    corrupted = dict(baseline.state_json)
    corrupted["resources"] = dict(corrupted["resources"])
    corrupted["resources"]["map_tiles"] = [
        dict(item) for item in corrupted["resources"]["map_tiles"]
    ]
    corrupted["resources"]["map_tiles"][0]["novel_id"] = str(uuid.uuid4())
    baseline.state_json = corrupted
    await db_session.flush()

    with pytest.raises(ConflictError) as exc:
        await MapRevisionService().restore_revision(
            db_session,
            novel_id,
            created.id,
            0,
            expected_revision=1,
        )

    assert exc.value.code == "map_revision_dependency_conflict"


@pytest.mark.asyncio
async def test_projection_deletes_keep_forward_and_reverse_changes(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(
            name="投影历史",
            map_type="world",
            grid_width=4,
            grid_height=4,
        ),
    )
    location_id = uuid.uuid4()
    faction_id = uuid.uuid4()
    db_session.add_all(
        [
            CoreEntity(
                id=location_id,
                novel_id=uuid.UUID(novel_id),
                entity_type="location",
                name="港口",
                status="canonical",
            ),
            CoreEntity(
                id=faction_id,
                novel_id=uuid.UUID(novel_id),
                entity_type="organization",
                name="商会",
                status="canonical",
            ),
        ]
    )
    await db_session.flush()

    binding = (
        await MapLocationBindingService().batch_create(
            db_session,
            novel_id,
            created.id,
            MapLocationBindingCreate(
                location_entity_id=str(location_id),
                hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
            ),
        )
    )[0]
    await MapLocationBindingService().delete(
        db_session,
        novel_id,
        binding.id,
        map_id=created.id,
    )
    binding_delete_revision = await _current_revision(
        db_session,
        novel_id,
        created.id,
    )
    latest = (
        await MapRevisionService().list_revisions(
            db_session,
            novel_id,
            created.id,
            limit=1,
        )
    ).items[0]
    forward = next(
        item
        for item in latest.forward_changes
        if item["resource_type"] == "map_location_bindings"
    )
    reverse = next(
        item
        for item in latest.reverse_changes
        if item["resource_type"] == "map_location_bindings"
    )
    assert forward["operation"] == "delete"
    assert forward["before"]["id"] == binding.id
    assert reverse["operation"] == "create"
    assert reverse["after"]["id"] == binding.id

    await MapRevisionService().restore_revision(
        db_session,
        novel_id,
        created.id,
        binding_delete_revision - 1,
        expected_revision=binding_delete_revision,
    )
    bindings = await MapLocationBindingRepository().get_by_map(
        db_session,
        uuid.UUID(novel_id),
        uuid.UUID(created.id),
    )
    assert [str(item.id) for item in bindings] == [binding.id]

    territory = (
        await MapTerritoryService().create(
            db_session,
            novel_id,
            created.id,
            MapTerritoryCreate(
                faction_entity_id=str(faction_id),
                hexes=[TerritoryHex(hex_q=2, hex_r=2)],
            ),
        )
    )[0]
    await MapTerritoryService().delete(
        db_session,
        novel_id,
        territory.id,
        map_id=created.id,
    )
    territory_delete_revision = await _current_revision(
        db_session,
        novel_id,
        created.id,
    )
    latest = (
        await MapRevisionService().list_revisions(
            db_session,
            novel_id,
            created.id,
            limit=1,
        )
    ).items[0]
    assert any(
        item["resource_type"] == "map_territory_tiles"
        and item["operation"] == "delete"
        and item["before"]["id"] == territory.id
        for item in latest.forward_changes
    )

    await MapRevisionService().restore_revision(
        db_session,
        novel_id,
        created.id,
        territory_delete_revision - 1,
        expected_revision=territory_delete_revision,
    )
    territories = await MapTerritoryRepository().get_by_map(
        db_session,
        uuid.UUID(novel_id),
        uuid.UUID(created.id),
    )
    assert [str(item.id) for item in territories] == [territory.id]
