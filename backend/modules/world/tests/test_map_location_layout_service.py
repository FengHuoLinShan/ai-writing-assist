from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapConfigCreate,
    MapLocationLayoutItem,
    MapLocationLayoutReplaceRequest,
)
from modules.world.services.map_location_layout import MapLocationLayoutService
from modules.world.services.map_service import MapConfigService
from modules.world.services.map_state_assembler import MapStateAssembler
from modules.world.tests.helpers import (
    _create_location_entity,
    _create_project,
)


@pytest.mark.asyncio
async def test_replace_location_layouts_saves_center_radius_and_lock(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location_id = await _create_location_entity(db_session, novel_id, "洛阳")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )

    response = await MapLocationLayoutService().replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=3,
                    center_hex_r=4,
                    occupy_radius=2,
                    locked=True,
                    layout_source="user_drag",
                    sync_geo_setting=False,
                )
            ]
        ),
    )

    assert response.total == 1
    layout = response.items[0]
    assert layout.center_hex_q == 3
    assert layout.center_hex_r == 4
    assert layout.occupy_radius == 2
    assert layout.locked is True
    assert layout.layout_source == "user_drag"
    assert layout.sync_geo_setting is False


@pytest.mark.asyncio
async def test_replace_location_layout_rejects_cross_novel_location(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    other_location_id = await _create_location_entity(db_session, other_novel_id, "他界")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )

    with pytest.raises(HTTPException) as exc:
        await MapLocationLayoutService().replace(
            db_session,
            novel_id,
            created.id,
            MapLocationLayoutReplaceRequest(
                layouts=[
                    MapLocationLayoutItem(
                        location_entity_id=other_location_id,
                        center_hex_q=1,
                        center_hex_r=1,
                    )
                ]
            ),
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_map_state_returns_empty_new_layout_and_terrain_arrays(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=3, grid_height=3),
    )

    state = await MapStateAssembler().assemble(db_session, novel_id, created.id)

    assert state.location_layouts == []
    assert state.terrain_layers == []
    assert state.terrain_regions == []
    assert state.terrain_patches == []
    assert state.terrain_bindings == []
