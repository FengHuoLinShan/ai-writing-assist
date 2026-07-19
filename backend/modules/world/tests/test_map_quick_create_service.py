from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from core.errors import ValidationError as DomainValidationError
from modules.world.map_repositories import (
    MapConfigRepository,
    MapFactRepository,
    MapLocationBindingRepository,
)
from modules.world.map_schemas import (
    MapConfigCreate,
    MapQuickCreateConfirmRequest,
    MapQuickCreatePreviewRequest,
)
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import EntityRelationCreate
from modules.world.services.map.map_location_binding_service import (
    MapLocationBindingService,
)
from modules.world.services.map.map_quick_create import MapQuickCreateService
from modules.world.services.map_service import MapConfigService
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_quick_create_preview_uses_only_adopted_locations_by_default(
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
    assert str(draft.id) not in layout_ids
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
    draft = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="建议影子港",
        status="draft",
    )

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=True),
    )

    layouts = {item.location_entity_id: item for item in preview.location_layouts}
    assert layouts[str(candidate.id)].meta == {"entity_status": "candidate"}
    assert layouts[str(draft.id)].meta == {"entity_status": "draft"}


@pytest.mark.asyncio
async def test_quick_create_context_exposes_scope_parent_and_detail_map_advice(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    city = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="廷根市",
        status="canonical",
        summary="鲁恩王国阿霍瓦郡的城市",
    )
    office = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="黑荆棘安保公司",
        status="canonical",
    )
    await EntityRelationRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        EntityRelationCreate(
            source_id=str(city.id),
            target_id=str(office.id),
            relation_type="contains",
            status="canonical",
        ),
    )
    detail_map = await MapConfigService().create(
        db_session,
        novel_id,
        MapConfigCreate(
            name="黑荆棘内部详图",
            map_type="region",
            grid_width=6,
            grid_height=6,
            parent_entity_id=str(office.id),
        ),
    )

    context = await MapQuickCreateService().context(db_session, novel_id)

    locations = {item["id"]: item for item in context.locations}
    assert locations[str(city.id)]["map_scope"] == {
        "key": "settlement",
        "label": "城市/聚落",
        "basis": "name_summary",
        "recommended_targets": ["world", "detail"],
    }
    assert locations[str(office.id)]["parent_locations"] == [
        {"id": str(city.id), "name": "廷根市"}
    ]
    assert locations[str(office.id)]["has_detail_map"] is True
    assert locations[str(office.id)]["detail_maps"] == [
        {"id": detail_map.id, "name": "黑荆棘内部详图", "map_type": "region"}
    ]


@pytest.mark.asyncio
async def test_quick_create_world_preview_warns_about_cross_scale_locations(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="鲁恩王国",
        status="canonical",
    )
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="地下炼金室",
        status="canonical",
    )

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(target="world"),
    )

    assert any("建筑或室内地点" in warning for warning in preview.warnings)


@pytest.mark.asyncio
async def test_candidate_preview_does_not_move_canonical_locations(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    canonical_ids = []
    for name in ("洛阳", "长安", "临安", "建康"):
        entity = await _create_entity(
            db_session,
            novel_id,
            entity_type="location",
            name=name,
            status="canonical",
        )
        canonical_ids.append(str(entity.id))
    for name in ("候选港", "草稿城", "建议关"):
        await _create_entity(
            db_session,
            novel_id,
            entity_type="location",
            name=name,
            status="candidate",
        )
    service = MapQuickCreateService()

    canonical_only = await service.preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=False),
    )
    with_candidates = await service.preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=True),
    )

    def positions(response):  # type: ignore[no-untyped-def]
        return {
            item.location_entity_id: (item.center_hex_q, item.center_hex_r)
            for item in response.location_layouts
            if item.location_entity_id in canonical_ids
        }

    assert positions(with_candidates) == positions(canonical_only)


@pytest.mark.asyncio
async def test_quick_create_detail_scopes_to_parent_direct_children_and_explicit_extra(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    parent = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="王都",
        status="canonical",
    )
    child = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="内城",
        status="canonical",
    )
    unrelated = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="远港",
        status="canonical",
    )
    await EntityRelationRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        EntityRelationCreate(
            source_id=str(parent.id),
            target_id=str(child.id),
            relation_type="contains",
            status="canonical",
        ),
    )

    scoped = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(
            target="detail",
            parent_entity_id=str(parent.id),
        ),
    )
    expanded = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(
            target="detail",
            parent_entity_id=str(parent.id),
            location_entity_ids=[str(unrelated.id)],
        ),
    )

    assert {item.location_entity_id for item in scoped.location_layouts} == {
        str(parent.id),
        str(child.id),
    }
    assert {item.location_entity_id for item in expanded.location_layouts} == {
        str(parent.id),
        str(child.id),
        str(unrelated.id),
    }


@pytest.mark.asyncio
async def test_quick_create_confirm_requires_pending_location_adoption(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    pending = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="待采用星港",
        status="draft",
    )

    with pytest.raises(DomainValidationError) as exc_info:
        await MapQuickCreateService().confirm(
            db_session,
            novel_id,
            MapQuickCreateConfirmRequest(
                name="不应落地的地图",
                include_candidates=True,
                layouts=[
                    {
                        "location_entity_id": str(pending.id),
                        "center_hex_q": 5,
                        "center_hex_r": 6,
                        "occupy_radius": 1,
                    }
                ],
            ),
        )

    assert exc_info.value.code == "unadopted_quick_create_location"
    maps, total = await MapConfigRepository().get_by_novel(
        db_session,
        uuid.UUID(hex=novel_id),
        limit=20,
    )
    assert maps == []
    assert total == 0


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
async def test_quick_create_api_leaves_commit_to_request_dependency(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    location = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="洛阳",
        status="canonical",
    )

    response = await async_client.post(
        "/api/world/maps/quick-create/confirm",
        params={"novel_id": novel_id},
        json={
            "name": "请求事务快速地图",
            "location_entity_ids": [str(location.id)],
            "grid_width": 6,
            "grid_height": 6,
        },
    )

    assert response.status_code == 201, response.text
    assert db_session.in_transaction() is True


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
async def test_quick_create_confirm_places_existing_adopted_locations_and_facts(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    bay = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="canonical",
    )
    tower = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="归潮塔群",
        status="canonical",
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
async def test_quick_create_confirm_empty_layouts_do_not_fall_back_to_all(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="canonical",
    )
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="归潮塔群",
        status="canonical",
    )

    response = await MapQuickCreateService().confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(name="空选择地图", layouts=[]),
    )
    facts, total = await MapFactRepository().list(
        db_session,
        uuid.UUID(hex=novel_id),
        map_id=uuid.UUID(response.map.id),
        fact_status="confirmed",
        limit=20,
    )

    assert response.map.name == "空选择地图"
    assert response.location_layouts == []
    assert response.location_bindings == []
    assert facts == []
    assert total == 0


@pytest.mark.asyncio
async def test_quick_create_confirm_writes_only_submitted_layouts(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    bay = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="canonical",
    )
    tower = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="归潮塔群",
        status="canonical",
    )

    response = await MapQuickCreateService().confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(
            name="单选地图",
            layouts=[
                {
                    "location_entity_id": str(bay.id),
                    "center_hex_q": 5,
                    "center_hex_r": 6,
                    "occupy_radius": 1,
                },
            ],
        ),
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
    assert placed_ids == {str(bay.id)}
    assert binding_ids == {str(bay.id)}
    assert fact_ids == {str(bay.id)}
    assert str(tower.id) not in placed_ids
    assert total == 1


@pytest.mark.asyncio
async def test_quick_create_confirm_rejects_layouts_outside_preview(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="canonical",
    )
    faction = await _create_entity(
        db_session,
        novel_id,
        entity_type="faction",
        name="北府",
        status="canonical",
    )

    with pytest.raises(DomainValidationError) as exc_info:
        await MapQuickCreateService().confirm(
            db_session,
            novel_id,
            MapQuickCreateConfirmRequest(
                name="越权地图",
                layouts=[
                    {
                        "location_entity_id": str(faction.id),
                        "center_hex_q": 5,
                        "center_hex_r": 6,
                        "occupy_radius": 1,
                    },
                ],
            ),
        )

    maps, total_maps = await MapConfigRepository().get_by_novel(
        db_session,
        uuid.UUID(hex=novel_id),
        limit=20,
    )
    assert exc_info.value.code == "invalid_quick_create_layout"
    assert maps == []
    assert total_maps == 0


@pytest.mark.asyncio
async def test_quick_create_confirm_requires_explicit_existing_map_replacement(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    bay = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="琉璃湾",
        status="canonical",
    )
    tower = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="归潮塔群",
        status="canonical",
    )

    service = MapQuickCreateService()
    first = await service.confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(name="快速创建世界地图"),
    )
    with pytest.raises(ConflictError) as conflict:
        await service.confirm(
            db_session,
            novel_id,
            MapQuickCreateConfirmRequest(name="快速创建世界地图"),
        )
    assert conflict.value.code == "map_quick_create_name_conflict"

    second = await service.confirm(
        db_session,
        novel_id,
        MapQuickCreateConfirmRequest(
            name="快速创建世界地图",
            replace_map_id=first.map.id,
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
