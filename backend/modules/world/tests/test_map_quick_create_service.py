from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapQuickCreateConfirmRequest,
    MapQuickCreatePreviewRequest,
)
from modules.world.repositories import CoreEntityRepository, EntityRelationRepository
from modules.world.schemas import EntityRelationCreate
from modules.world.services.map_quick_create import MapQuickCreateService
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_quick_create_preview_uses_only_canonical_by_default(
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

    preview = await MapQuickCreateService().preview(
        db_session,
        novel_id,
        MapQuickCreatePreviewRequest(include_candidates=False),
    )

    layout_ids = {item.location_entity_id for item in preview.location_layouts}
    assert str(canonical.id) in layout_ids
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
