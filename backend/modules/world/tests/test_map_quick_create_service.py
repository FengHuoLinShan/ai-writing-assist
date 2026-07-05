from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import (
    MapConfigRepository,
    MapFactRepository,
    MapLocationBindingRepository,
)
from modules.world.map_schemas import (
    MapQuickCreateConfirmRequest,
    MapQuickCreatePreviewRequest,
)
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import EntityRelationCreate
from modules.world.services.map_location_binding_service import (
    MapLocationBindingService,
)
from modules.world.services.map_quick_create import MapQuickCreateService
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_quick_create_preview_uses_draft_and_canonical_by_default(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    canonical = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="正史城",
        status="canonical",
    )
    candidate = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="候选城",
        status="candidate",
    )
    draft = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="草稿港",
        status="draft",
    )

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=False),
    )

    layout_ids = {item.location_entity_id for item in preview.location_layouts}
    assert str(canonical.id) in layout_ids
    assert str(draft.id) in layout_ids
    assert str(candidate.id) not in layout_ids
    assert preview.map["grid_width"] == 40
    assert preview.map["grid_height"] == 30


@pytest.mark.asyncio
async def test_quick_create_preview_includes_candidates_when_enabled(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    candidate = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="候选城",
        status="candidate",
    )

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=True),
    )

    layout = preview.location_layouts[0]
    assert layout.location_entity_id == str(candidate.id)
    assert layout.meta == {"entity_status": "candidate"}


@pytest.mark.asyncio
async def test_quick_create_preview_uses_list_repositories_without_count(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    entity_repo = MagicMock()
    relation_repo = MagicMock()
    entity_repo.list_by_novel = AsyncMock(side_effect=[[], [], []])
    entity_repo.get_by_novel = AsyncMock(
        side_effect=AssertionError("quick create should not count entities")
    )
    relation_repo.list_by_novel = AsyncMock(return_value=[])
    relation_repo.get_by_novel = AsyncMock(
        side_effect=AssertionError("quick create should not count relations")
    )

    preview = await MapQuickCreateService(
        entity_repo=entity_repo,
        relation_repo=relation_repo,
    ).preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=True),
    )

    assert preview.location_layouts == []
    assert entity_repo.list_by_novel.await_count == 3
    relation_repo.list_by_novel.assert_awaited_once()
    entity_repo.get_by_novel.assert_not_awaited()
    relation_repo.get_by_novel.assert_not_awaited()


@pytest.mark.asyncio
async def test_quick_create_confirm_creates_one_map_without_new_world_objects(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="洛阳",
        status="canonical",
    )
    entity_repo = CoreEntityRepository()
    before, before_total = await entity_repo.get_by_novel(
        db_session,
        uuid.UUID(hex=novel_id),
        limit=100,
    )

    response = await MapQuickCreateService().confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(name="一键地图"),
    )
    after, after_total = await entity_repo.get_by_novel(
        db_session,
        uuid.UUID(hex=novel_id),
        limit=100,
    )

    assert response.map.name == "一键地图"
    assert len(response.location_layouts) == 1
    assert len(response.location_bindings) == 1
    assert before_total == after_total
    assert {item.id for item in before} == {item.id for item in after}


@pytest.mark.asyncio
async def test_quick_create_confirm_batches_location_bindings(
    db_session: AsyncSession,
) -> None:
    class BulkOnlyBindingService(MapLocationBindingService):
        def __init__(self) -> None:
            super().__init__()
            self.batch_create_many_calls = 0

        async def batch_create(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("quick create should batch all location bindings")

        async def batch_create_many(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            self.batch_create_many_calls += 1
            return await super().batch_create_many(*args, **kwargs)

    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="洛阳",
        status="canonical",
    )
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="长安",
        status="canonical",
    )
    binding_service = BulkOnlyBindingService()

    response = await MapQuickCreateService(binding_service=binding_service).confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(name="一键地图"),
    )

    assert binding_service.batch_create_many_calls == 1
    assert len(response.location_bindings) == 2
    assert all(binding.is_center for binding in response.location_bindings)


@pytest.mark.asyncio
async def test_quick_create_preview_warns_when_geo_relations_are_missing(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="洛阳",
        status="canonical",
    )

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(),
    )

    assert preview.warnings == ["缺少地点方向/距离关系，已生成等间距草稿"]


@pytest.mark.asyncio
async def test_quick_create_confirm_places_existing_draft_locations_and_facts(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    bay = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="draft",
    )
    tower = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="归潮塔群",
        status="draft",
    )

    response = await MapQuickCreateService().confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(name="霭潮地图"),
    )
    facts, total = await MapFactRepository().list(
        db_session,
        uuid.UUID(hex=novel_id),
        map_id=uuid.UUID(response.map.id),
        fact_status="confirmed",
        limit=20,
    )

    placed_ids = {item.location_entity_id for item in response.location_layouts}
    binding_ids = {item.location_entity_id for item in response.location_bindings}
    fact_ids = {str(item.target_entity_id) for item in facts}
    assert placed_ids == {str(bay.id), str(tower.id)}
    assert binding_ids == placed_ids
    assert fact_ids == placed_ids
    assert total == 2
    assert {item.dynamic_type for item in facts} == {"location"}
    assert all((item.spatial_anchor or {}).get("hex_q") is not None for item in facts)


@pytest.mark.asyncio
async def test_quick_create_confirm_reuses_existing_map_and_replaces_outputs(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    bay = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="draft",
    )
    tower = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="归潮塔群",
        status="draft",
    )

    service = MapQuickCreateService()
    first = await service.confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(name="快速创建世界地图"),
    )
    second = await service.confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(
            name="快速创建世界地图",
            layouts=[
                {
                    "location_entity_id": str(bay.id),
                    "center_hex_q": 3,
                    "center_hex_r": 4,
                    "occupy_radius": 2,
                    "locked": True,
                    "layout_source": "user_drag",
                },
                {
                    "location_entity_id": str(tower.id),
                    "center_hex_q": 9,
                    "center_hex_r": 10,
                    "occupy_radius": 1,
                    "locked": False,
                    "layout_source": "quick_create",
                },
            ],
        ),
    )

    maps, total_maps = await MapConfigRepository().get_by_novel(
        db_session,
        uuid.UUID(hex=novel_id),
        limit=20,
    )
    bindings = await MapLocationBindingRepository().get_by_map(
        db_session,
        uuid.UUID(hex=novel_id),
        uuid.UUID(second.map.id),
    )
    facts, total_facts = await MapFactRepository().list(
        db_session,
        uuid.UUID(hex=novel_id),
        map_id=uuid.UUID(second.map.id),
        fact_status="confirmed",
        limit=20,
    )

    assert first.map.id == second.map.id
    assert total_maps == 1
    assert [item.name for item in maps] == ["快速创建世界地图"]
    assert len(bindings) == 2
    assert total_facts == 2
    by_location = {str(item.target_entity_id): item for item in facts}
    assert by_location[str(bay.id)].spatial_anchor == {
        "map_id": second.map.id,
        "hex_q": 3,
        "hex_r": 4,
    }
    assert by_location[str(tower.id)].spatial_anchor == {
        "map_id": second.map.id,
        "hex_q": 9,
        "hex_r": 10,
    }


@pytest.mark.asyncio
async def test_quick_create_preview_uses_direction_relations_for_layout(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    west = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="西城",
        status="canonical",
    )
    east = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="东城",
        status="canonical",
    )
    await EntityRelationRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        EntityRelationCreate(
            source_id=str(east.id),
            target_id=str(west.id),
            relation_type="east_of",
        ),
    )

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(),
    )

    by_id = {layout.location_entity_id: layout for layout in preview.location_layouts}
    assert by_id[str(east.id)].center_hex_q > by_id[str(west.id)].center_hex_q
    assert preview.warnings == []
