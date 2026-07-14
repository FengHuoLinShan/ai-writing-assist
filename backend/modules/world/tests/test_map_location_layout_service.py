from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.map_repositories import (
    MapFactRepository,
    MapLocationBindingRepository,
    MapLocationLayoutRepository,
)
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapLocationBindingCreate,
    MapLocationLayoutItem,
    MapLocationLayoutReplaceRequest,
)
from modules.world.models import CoreEntity
from modules.world.services.map.map_location_binding_service import (
    MapLocationBindingService,
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

        async def require_canonical_entities(
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
async def test_sync_location_layout_translates_footprint_and_deprecates_quick_fact(
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
    service = MapLocationLayoutService()
    await service.replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=2,
                    center_hex_r=2,
                )
            ]
        ),
    )
    await MapLocationBindingService().batch_create(
        db_session,
        novel_id,
        created.id,
        MapLocationBindingCreate(
            location_entity_id=location_id,
            hexes=[
                BindingHex(
                    hex_q=2,
                    hex_r=2,
                    is_center=True,
                    label_override="主城",
                ),
                BindingHex(
                    hex_q=3,
                    hex_r=2,
                    style_override={"color": "red"},
                ),
            ],
        ),
    )
    fact_repo = MapFactRepository()
    fact = await fact_repo.create(
        db_session,
        uuid.UUID(hex=novel_id),
        {
            "map_id": uuid.UUID(created.id),
            "target_entity_id": uuid.UUID(location_id),
            "target_entity_type": "location",
            "target_name": "洛阳",
            "dynamic_type": "location",
            "fact_status": "confirmed",
            "source_ref": {"source": "map_quick_create"},
        },
    )

    await service.replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            sync_bindings=True,
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=4,
                    center_hex_r=3,
                    layout_source="user_drag",
                )
            ],
        ),
    )

    bindings = await MapLocationBindingRepository().get_by_map(
        db_session,
        uuid.UUID(hex=novel_id),
        uuid.UUID(created.id),
    )
    assert {(item.hex_q, item.hex_r) for item in bindings} == {(4, 3), (5, 3)}
    assert [item.is_center for item in bindings].count(True) == 1
    center = next(item for item in bindings if item.is_center)
    edge = next(item for item in bindings if not item.is_center)
    assert center.label_override == "主城"
    assert edge.style_override == {"color": "red"}
    refreshed_fact = await fact_repo.get(db_session, fact.id)
    assert refreshed_fact is not None
    assert refreshed_fact.fact_status == "deprecated"
    assert refreshed_fact.source_ref["superseded_reason"] == "location_layout_edit"


@pytest.mark.asyncio
async def test_sync_location_layout_allows_explicit_unlock_and_move_together(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location_id = await _create_location_entity(db_session, novel_id, "锁龙关")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    service = MapLocationLayoutService()
    await service.replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=2,
                    center_hex_r=2,
                    locked=True,
                )
            ]
        ),
    )

    response = await service.replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            sync_bindings=True,
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=3,
                    center_hex_r=3,
                    locked=False,
                    layout_source="user_drag",
                )
            ],
        ),
    )

    assert response.items[0].locked is False
    assert (response.items[0].center_hex_q, response.items[0].center_hex_r) == (3, 3)


@pytest.mark.asyncio
async def test_sync_location_layout_rejects_moving_a_still_locked_location(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location_id = await _create_location_entity(db_session, novel_id, "不动城")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    service = MapLocationLayoutService()
    await service.replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=2,
                    center_hex_r=2,
                    locked=True,
                )
            ]
        ),
    )

    with pytest.raises(DomainError) as exc:
        await service.replace(
            db_session,
            novel_id,
            created.id,
            MapLocationLayoutReplaceRequest(
                sync_bindings=True,
                layouts=[
                    MapLocationLayoutItem(
                        location_entity_id=location_id,
                        center_hex_q=3,
                        center_hex_r=3,
                        locked=True,
                    )
                ],
            ),
        )

    assert exc.value.code == "locked_location_layout"


@pytest.mark.asyncio
async def test_sync_location_layout_out_of_bounds_keeps_layout_and_footprint(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location_id = await _create_location_entity(db_session, novel_id, "边关")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    service = MapLocationLayoutService()
    await service.replace(
        db_session,
        novel_id,
        created.id,
        MapLocationLayoutReplaceRequest(
            layouts=[
                MapLocationLayoutItem(
                    location_entity_id=location_id,
                    center_hex_q=6,
                    center_hex_r=6,
                )
            ]
        ),
    )
    await MapLocationBindingService().batch_create(
        db_session,
        novel_id,
        created.id,
        MapLocationBindingCreate(
            location_entity_id=location_id,
            hexes=[
                BindingHex(hex_q=6, hex_r=6, is_center=True),
                BindingHex(hex_q=7, hex_r=6),
            ],
        ),
    )

    with pytest.raises(DomainError):
        await service.replace(
            db_session,
            novel_id,
            created.id,
            MapLocationLayoutReplaceRequest(
                sync_bindings=True,
                layouts=[
                    MapLocationLayoutItem(
                        location_entity_id=location_id,
                        center_hex_q=7,
                        center_hex_r=6,
                    )
                ],
            ),
        )

    layout = (await service.list(db_session, novel_id, created.id)).items[0]
    bindings = await MapLocationBindingRepository().get_by_map(
        db_session,
        uuid.UUID(hex=novel_id),
        uuid.UUID(created.id),
    )
    assert (layout.center_hex_q, layout.center_hex_r) == (6, 6)
    assert {(item.hex_q, item.hex_r) for item in bindings} == {(6, 6), (7, 6)}


def test_legacy_anchor_uses_deterministic_axial_centroid_tie_break() -> None:
    bindings = [
        SimpleNamespace(id="b", hex_q=2, hex_r=0, is_center=False),
        SimpleNamespace(id="a", hex_q=0, hex_r=2, is_center=False),
    ]

    assert MapLocationLayoutService._resolve_anchor(None, bindings) == (0, 2)


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
async def test_layout_write_rejects_pending_owner_and_legacy_row_is_review_only(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    shadow = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="待处理港口",
        status="candidate",
    )
    db_session.add(shadow)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    request = MapLocationLayoutReplaceRequest(
        layouts=[
            MapLocationLayoutItem(
                location_entity_id=str(shadow.id),
                center_hex_q=1,
                center_hex_r=1,
            )
        ]
    )

    with pytest.raises(DomainError) as exc:
        await MapLocationLayoutService().replace(
            db_session,
            novel_id,
            created.id,
            request,
        )
    assert exc.value.code == "unadopted_map_entity"

    await MapLocationLayoutRepository().create(
        db_session,
        uuid.UUID(novel_id),
        uuid.UUID(created.id),
        {
            "location_entity_id": shadow.id,
            "center_hex_q": 1,
            "center_hex_r": 1,
            "occupy_radius": 1,
            "locked": False,
            "layout_source": "legacy",
            "layout_version": 1,
            "sync_geo_setting": False,
            "meta": {},
        },
    )

    listed = await MapLocationLayoutService().list(
        db_session,
        novel_id,
        created.id,
    )
    state = await MapStateAssembler().assemble(db_session, novel_id, created.id)
    assert listed.items == []
    assert state.location_layouts == []
    assert [item.location_entity_id for item in state.candidate_location_layouts] == [
        str(shadow.id)
    ]


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
