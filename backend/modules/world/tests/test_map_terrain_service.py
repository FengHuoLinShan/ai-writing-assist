from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from modules.world.map_repositories import (
    MapTerrainLayerRepository,
    MapTerrainRegionRepository,
)
from modules.world.map_schemas import (
    MapConfigCreate,
    MapTerrainBindingCreate,
    MapTerrainBindingUpdate,
    MapTerrainLayerCreate,
    MapTerrainLayerUpdate,
    MapTerrainPatchItem,
    MapTerrainPatchReplaceRequest,
    MapTerrainRegionCreate,
)
from modules.world.models import CoreEntity
from modules.world.services.map.map_terrain import MapTerrainService
from modules.world.services.map_service import MapConfigService
from modules.world.tests.helpers import _create_location_entity, _create_project


@pytest.mark.asyncio
async def test_replace_terrain_layer_patches_creates_layer_region_and_patches(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_id = uuid.uuid4().hex

    state = await MapTerrainService().replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="结界层", terrain_asset_key="barrier"),
            regions=[
                MapTerrainRegionCreate(
                    id=region_id,
                    layer_id=layer_id,
                    name="结界 1",
                )
            ],
            patches=[
                MapTerrainPatchItem(region_id=region_id, hex_q=2, hex_r=2),
                MapTerrainPatchItem(region_id=region_id, hex_q=3, hex_r=2),
            ],
        ),
    )

    assert [layer.name for layer in state.layers] == ["结界层"]
    assert [region.name for region in state.regions] == ["结界 1"]
    assert {(patch.hex_q, patch.hex_r) for patch in state.patches} == {(2, 2), (3, 2)}


@pytest.mark.asyncio
async def test_replace_terrain_layer_patches_overwrites_existing_layer_patches(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_id = uuid.uuid4().hex
    service = MapTerrainService()
    await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="深渊层", terrain_asset_key="abyss"),
            regions=[
                MapTerrainRegionCreate(id=region_id, layer_id=layer_id, name="深渊 1")
            ],
            patches=[MapTerrainPatchItem(region_id=region_id, hex_q=1, hex_r=1)],
        ),
    )

    state = await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            patches=[MapTerrainPatchItem(region_id=region_id, hex_q=4, hex_r=4)]
        ),
    )

    assert {(patch.hex_q, patch.hex_r) for patch in state.patches} == {(4, 4)}


@pytest.mark.asyncio
async def test_terrain_layer_partial_update_lock_and_delete_counts(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location_id = await _create_location_entity(db_session, novel_id, "昆仑")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_id = uuid.uuid4().hex
    service = MapTerrainService()
    await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(
                name="结界层",
                terrain_asset_key="barrier",
                opacity=0.25,
                meta={"pack_key": "fantasy"},
            ),
            regions=[
                MapTerrainRegionCreate(id=region_id, layer_id=layer_id, name="结界")
            ],
            patches=[MapTerrainPatchItem(region_id=region_id, hex_q=2, hex_r=2)],
        ),
    )
    await service.create_binding(
        db_session,
        novel_id,
        created.id,
        MapTerrainBindingCreate(
            region_id=region_id,
            location_entity_id=location_id,
            binding_type="influence",
        ),
    )

    locked = await service.update_layer(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainLayerUpdate(name="结界层 A", locked=True),
    )
    assert locked.name == "结界层 A"
    assert locked.opacity == 0.25
    assert locked.meta == {"pack_key": "fantasy"}
    with pytest.raises(DomainError) as draw_error:
        await service.replace_layer_patches(
            db_session,
            novel_id,
            created.id,
            layer_id,
            MapTerrainPatchReplaceRequest(
                patches=[MapTerrainPatchItem(region_id=region_id, hex_q=3, hex_r=3)]
            ),
        )
    assert draw_error.value.code == "map_terrain_layer_locked"
    with pytest.raises(DomainError) as delete_error:
        await service.delete_layer(db_session, novel_id, created.id, layer_id)
    assert delete_error.value.code == "map_terrain_layer_locked"

    await service.update_layer(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainLayerUpdate(locked=False),
    )
    deleted = await service.delete_layer(db_session, novel_id, created.id, layer_id)
    assert deleted.deleted_regions == 1
    assert deleted.deleted_patches == 1
    assert deleted.deleted_bindings == 1
    assert (await service.get_state(db_session, novel_id, created.id)).layers == []
    archived = await MapTerrainLayerRepository().get_by_map(
        db_session,
        uuid.UUID(novel_id),
        uuid.UUID(created.id),
        status="all",
    )
    assert len(archived) == 1
    assert archived[0].status == "archived"

    restored = await service.restore_layer(
        db_session,
        novel_id,
        created.id,
        layer_id,
    )
    assert restored.status == "active"
    restored_state = await service.get_state(db_session, novel_id, created.id)
    assert [item.id for item in restored_state.layers] == [str(uuid.UUID(layer_id))]
    assert [item.id for item in restored_state.regions] == [str(uuid.UUID(region_id))]
    assert len(restored_state.patches) == 1
    assert len(restored_state.bindings) == 1


@pytest.mark.asyncio
async def test_replace_terrain_layer_patches_reuses_existing_region_id(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_id = uuid.uuid4().hex
    service = MapTerrainService()
    payload = MapTerrainPatchReplaceRequest(
        layer=MapTerrainLayerCreate(name="结界层", terrain_asset_key="barrier"),
        regions=[MapTerrainRegionCreate(id=region_id, layer_id=layer_id, name="结界 1")],
        patches=[MapTerrainPatchItem(region_id=region_id, hex_q=1, hex_r=1)],
    )
    await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        payload,
    )

    state = await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            regions=[
                MapTerrainRegionCreate(id=region_id, layer_id=layer_id, name="结界 1A")
            ],
            patches=[MapTerrainPatchItem(region_id=region_id, hex_q=2, hex_r=2)],
        ),
    )

    assert [region.name for region in state.regions] == ["结界 1A"]
    assert {(patch.hex_q, patch.hex_r) for patch in state.patches} == {(2, 2)}


@pytest.mark.asyncio
async def test_replace_terrain_regions_cannot_cross_layers_or_maps(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    first_map = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界 A", map_type="world", grid_width=8, grid_height=8),
    )
    second_map = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界 B", map_type="world", grid_width=8, grid_height=8),
    )
    layer_a = uuid.uuid4().hex
    layer_b = uuid.uuid4().hex
    layer_c = uuid.uuid4().hex
    region_a = uuid.uuid4().hex
    region_b = uuid.uuid4().hex
    service = MapTerrainService()
    await service.replace_layer_patches(
        db_session,
        novel_id,
        first_map.id,
        layer_a,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="锁定层", terrain_asset_key="mountain"),
            regions=[MapTerrainRegionCreate(id=region_a, layer_id=layer_a, name="山脉")],
            patches=[],
        ),
    )
    await service.replace_layer_patches(
        db_session,
        novel_id,
        first_map.id,
        layer_b,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="目标层", terrain_asset_key="forest"),
            regions=[MapTerrainRegionCreate(id=region_b, layer_id=layer_b, name="森林")],
            patches=[],
        ),
    )
    await service.update_layer(
        db_session,
        novel_id,
        first_map.id,
        layer_a,
        MapTerrainLayerUpdate(locked=True),
    )

    with pytest.raises(DomainError) as locked_error:
        await service.replace_layer_patches(
            db_session,
            novel_id,
            first_map.id,
            layer_b,
            MapTerrainPatchReplaceRequest(
                regions=[
                    MapTerrainRegionCreate(
                        id=region_a,
                        layer_id=layer_b,
                        name="不应迁移",
                    )
                ],
                patches=[],
            ),
        )
    assert locked_error.value.code == "map_terrain_layer_locked"

    await service.update_layer(
        db_session,
        novel_id,
        first_map.id,
        layer_a,
        MapTerrainLayerUpdate(locked=False),
    )
    with pytest.raises(DomainError) as layer_error:
        await service.replace_layer_patches(
            db_session,
            novel_id,
            first_map.id,
            layer_b,
            MapTerrainPatchReplaceRequest(
                regions=[
                    MapTerrainRegionCreate(
                        id=region_a,
                        layer_id=layer_b,
                        name="仍不应迁移",
                    )
                ],
                patches=[],
            ),
        )
    assert layer_error.value.code == "invalid_terrain_region_layer"

    await service.replace_layer_patches(
        db_session,
        novel_id,
        second_map.id,
        layer_c,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="异图层", terrain_asset_key="water"),
            regions=[],
            patches=[],
        ),
    )
    with pytest.raises(DomainError) as map_error:
        await service.replace_layer_patches(
            db_session,
            novel_id,
            second_map.id,
            layer_c,
            MapTerrainPatchReplaceRequest(
                regions=[
                    MapTerrainRegionCreate(
                        id=region_a,
                        layer_id=layer_c,
                        name="异图引用",
                    )
                ],
                patches=[],
            ),
        )
    assert map_error.value.code == "map_terrain_region_not_found"


@pytest.mark.asyncio
async def test_delete_terrain_layer_recomputes_dfs_projection(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    service = MapTerrainService()
    layer_ids = [uuid.uuid4().hex for _ in range(3)]
    for index, layer_id in enumerate(layer_ids):
        await service.replace_layer_patches(
            db_session,
            novel_id,
            created.id,
            layer_id,
            MapTerrainPatchReplaceRequest(
                layer=MapTerrainLayerCreate(
                    name=f"覆盖层 {index}",
                    terrain_asset_key="forest",
                ),
                regions=[],
                patches=[],
            ),
        )

    await service.delete_layer(
        db_session,
        novel_id,
        created.id,
        layer_ids[1],
    )
    layers = await MapTerrainLayerRepository().get_by_map(
        db_session,
        uuid.UUID(novel_id),
        uuid.UUID(created.id),
    )
    assert [str(layer.id) for layer in layers] == [
        str(uuid.UUID(layer_ids[0])),
        str(uuid.UUID(layer_ids[2])),
    ]
    assert [layer.z_index for layer in layers] == [0, 1]


@pytest.mark.asyncio
async def test_replace_terrain_layer_patches_bulk_upserts_regions(
    db_session: AsyncSession,
) -> None:
    class BulkOnlyRegionRepository(MapTerrainRegionRepository):
        def __init__(self) -> None:
            super().__init__()
            self.upsert_many_calls = 0

        async def upsert(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("terrain region replacement should bulk upsert")

        async def upsert_many(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.upsert_many_calls += 1
            return await super().upsert_many(*args, **kwargs)

    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_ids = [uuid.uuid4().hex, uuid.uuid4().hex]
    region_repo = BulkOnlyRegionRepository()
    service = MapTerrainService(region_repo=region_repo)

    state = await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="结界层", terrain_asset_key="barrier"),
            regions=[
                MapTerrainRegionCreate(
                    id=region_ids[0],
                    layer_id=layer_id,
                    name="结界 1",
                ),
                MapTerrainRegionCreate(
                    id=region_ids[1],
                    layer_id=layer_id,
                    name="结界 2",
                ),
            ],
            patches=[
                MapTerrainPatchItem(region_id=region_ids[0], hex_q=1, hex_r=1),
                MapTerrainPatchItem(region_id=region_ids[1], hex_q=2, hex_r=2),
            ],
        ),
    )

    assert region_repo.upsert_many_calls == 1
    assert [region.name for region in state.regions] == ["结界 1", "结界 2"]
    assert {(patch.hex_q, patch.hex_r) for patch in state.patches} == {(1, 1), (2, 2)}


@pytest.mark.asyncio
async def test_terrain_binding_validates_type_and_location_novel(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    other_novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_project(db_session, other_novel_id)
    location_id = await _create_location_entity(db_session, novel_id, "昆仑")
    other_location_id = await _create_location_entity(db_session, other_novel_id, "他界")
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_id = uuid.uuid4().hex
    service = MapTerrainService()
    await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="高山层", terrain_asset_key="mountain"),
            regions=[
                MapTerrainRegionCreate(id=region_id, layer_id=layer_id, name="昆仑山脉")
            ],
            patches=[MapTerrainPatchItem(region_id=region_id, hex_q=2, hex_r=2)],
        ),
    )

    binding = await service.create_binding(
        db_session,
        novel_id,
        created.id,
        MapTerrainBindingCreate(
            region_id=region_id,
            location_entity_id=location_id,
            binding_type="footprint",
        ),
    )
    assert binding.binding_type == "footprint"
    assert binding.review_state == "confirmed"

    with pytest.raises(DomainError) as exc:
        await service.create_binding(
            db_session,
            novel_id,
            created.id,
            MapTerrainBindingCreate(
                region_id=region_id,
                location_entity_id=other_location_id,
                binding_type="influence",
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_confirmed_terrain_binding_requires_adopted_location(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    shadow_location = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="待处理山谷",
        status="candidate",
        content_json={
            "_meta": {
                "compatibility_shadow": True,
                "suggestion_id": uuid.uuid4().hex,
            }
        },
    )
    db_session.add(shadow_location)
    created = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(name="世界", map_type="world", grid_width=8, grid_height=8),
    )
    layer_id = uuid.uuid4().hex
    region_id = uuid.uuid4().hex
    service = MapTerrainService()
    await service.replace_layer_patches(
        db_session,
        novel_id,
        created.id,
        layer_id,
        MapTerrainPatchReplaceRequest(
            layer=MapTerrainLayerCreate(name="山谷层", terrain_asset_key="mountain"),
            regions=[
                MapTerrainRegionCreate(id=region_id, layer_id=layer_id, name="山谷")
            ],
            patches=[MapTerrainPatchItem(region_id=region_id, hex_q=2, hex_r=2)],
        ),
    )

    with pytest.raises(DomainError) as exc:
        await service.create_binding(
            db_session,
            novel_id,
            created.id,
            MapTerrainBindingCreate(
                region_id=region_id,
                location_entity_id=str(shadow_location.id),
                binding_type="footprint",
            ),
        )
    assert exc.value.code == "unadopted_map_entity"

    candidate = await service.create_binding(
        db_session,
        novel_id,
        created.id,
        MapTerrainBindingCreate(
            region_id=region_id,
            location_entity_id=str(shadow_location.id),
            binding_type="footprint",
            review_state="candidate",
        ),
    )
    with pytest.raises(DomainError) as confirm_exc:
        await service.update_binding(
            db_session,
            novel_id,
            created.id,
            candidate.id,
            MapTerrainBindingUpdate(review_state="confirmed"),
        )
    assert confirm_exc.value.code == "unadopted_map_entity"

    default_state = await service.get_state(db_session, novel_id, created.id)
    preview_state = await service.get_state(
        db_session,
        novel_id,
        created.id,
        include_candidates=True,
    )
    assert default_state.bindings == []
    assert [item.id for item in preview_state.candidate_bindings] == [candidate.id]

    legacy = await service._binding_repo.get(  # noqa: SLF001
        db_session,
        uuid.UUID(candidate.id),
    )
    assert legacy is not None
    legacy.review_state = "confirmed"
    await db_session.flush()

    hidden_state = await service.get_state(db_session, novel_id, created.id)
    assert hidden_state.bindings == []
    aggregate = await MapConfigService().get_state(db_session, novel_id, created.id)
    assert aggregate.terrain_bindings == []
    assert [item.id for item in aggregate.candidate_terrain_bindings] == [candidate.id]
    with pytest.raises(DomainError) as legacy_update_exc:
        await service.update_binding(
            db_session,
            novel_id,
            created.id,
            candidate.id,
            MapTerrainBindingUpdate(meta={"edited": True}),
        )
    assert legacy_update_exc.value.code == "unadopted_map_entity"
