from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.map_schemas import (
    MapConfigCreate,
    MapLocationLayoutItem,
    MapLocationLayoutReplaceRequest,
)
from modules.world.services.map.map_location_layout import MapLocationLayoutService
from modules.world.services.map.map_state_assembler import MapStateAssembler
from modules.world.services.map_service import MapConfigService
from modules.world.tests.helpers import (
    _create_location_entity,
    _create_project,
)


@pytest.mark.asyncio
async def test_replace_location_layouts_batches_entity_validation() -> None:
    novel_id = uuid.uuid4()
    map_id = uuid.uuid4()
    first_location_id = uuid.uuid4()
    second_location_id = uuid.uuid4()

    class Context:
        def __init__(self) -> None:
            self.batch_calls: list[list[str]] = []

        async def require_map(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return SimpleNamespace(grid_width=10, grid_height=10)

        async def require_entity(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("layout replace must validate locations in batch")

        async def require_entities(
            self,
            _db,
            requested_novel_id,
            entity_ids,
            *,
            allowed_types=None,
        ):  # type: ignore[no-untyped-def]
            assert requested_novel_id == str(novel_id)
            assert allowed_types == {"location"}
            self.batch_calls.append(list(entity_ids))
            return []

        def assert_hex_in_bounds(self, config, hex_q, hex_r):  # type: ignore[no-untyped-def]
            assert 0 <= hex_q < config.grid_width
            assert 0 <= hex_r < config.grid_height

    class LayoutRepo:
        async def replace_for_map(
            self,
            _db,
            requested_novel_id,
            requested_map_id,
            layouts,
        ):  # type: ignore[no-untyped-def]
            assert requested_novel_id == novel_id
            assert requested_map_id == map_id
            now = datetime.now(UTC)
            return [
                SimpleNamespace(
                    id=uuid.uuid4(),
                    novel_id=requested_novel_id,
                    map_id=requested_map_id,
                    created_at=now,
                    updated_at=now,
                    **layout,
                )
                for layout in layouts
            ]

    context = Context()
    service = MapLocationLayoutService(
        layout_repo=LayoutRepo(),  # type: ignore[arg-type]
        context=context,  # type: ignore[arg-type]
    )

    response = await service.replace(
        None,  # type: ignore[arg-type]
        str(novel_id),
        str(map_id),
        MapLocationLayoutReplaceRequest(
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=str(first_location_id),
                    center_hex_q=1,
                    center_hex_r=2,
                ),
                MapLocationLayoutItem(
                    location_entity_id=str(second_location_id),
                    center_hex_q=3,
                    center_hex_r=4,
                ),
            ]
        ),
    )

    assert context.batch_calls == [[str(first_location_id), str(second_location_id)]]
    assert response.total == 2


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

    with pytest.raises(DomainError) as exc:
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
