"""MapStateAssembler tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import SceneContract
from modules.world.map_repositories import (
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    BindingHex,
    MapConfigCreate,
    MapLocationBindingCreate,
    MapMarkerCreate,
    MapTerritoryCreate,
    TerritoryHex,
)
from modules.world.services.map.map_state_assembler import MapStateAssembler
from modules.world.services.map_service import (
    MapConfigService,
    MapLocationBindingService,
    MapMarkerService,
    MapTerritoryService,
)
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.asyncio
async def test_assemble_without_scene_id_does_not_lookup_scene(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    created = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="世界", map_type="world", grid_width=3, grid_height=3),
    )
    scene_lookup = AsyncMock()

    state = await MapStateAssembler(scene_lookup=scene_lookup).assemble(
        db_session,
        nid,
        created.id,
    )

    scene_lookup.assert_not_awaited()
    assert state.scene is None
    assert len(state.tiles) == 9


@pytest.mark.asyncio
async def test_assemble_uses_scene_contract_index_for_marker_lookup(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    created = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="世界", map_type="world", grid_width=3, grid_height=3),
    )
    scene_id = uuid.uuid4().hex
    scene_lookup = AsyncMock(
        return_value=SceneContract(
            id=scene_id,
            novel_id=nid,
            scene_index=7,
            title="初遇",
        )
    )
    marker_repo = Mock()
    marker_repo.get_by_map_and_scene = AsyncMock(return_value=[])

    state = await MapStateAssembler(
        marker_repo=marker_repo,
        scene_lookup=scene_lookup,
    ).assemble(db_session, nid, created.id, scene_id=scene_id)

    scene_lookup.assert_awaited_once_with(db_session, nid, scene_id)
    marker_repo.get_by_map_and_scene.assert_awaited_once()
    _, args, kwargs = marker_repo.get_by_map_and_scene.mock_calls[0]
    assert args[1] == uuid.UUID(hex=nid)
    assert args[2] == uuid.UUID(hex=created.id)
    assert kwargs == {"scene_id": uuid.UUID(hex=scene_id), "scene_index": 7}
    assert state.scene == {
        "id": scene_id,
        "index": 7,
        "title": "初遇",
        "chapter_title": None,
    }


@pytest.mark.asyncio
async def test_assemble_missing_scene_keeps_scene_none(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    created = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="世界", map_type="world", grid_width=3, grid_height=3),
    )
    scene_id = uuid.uuid4().hex
    marker_repo = Mock()
    marker_repo.get_by_map_and_scene = AsyncMock(return_value=[])

    state = await MapStateAssembler(
        marker_repo=marker_repo,
        scene_lookup=AsyncMock(return_value=None),
    ).assemble(db_session, nid, created.id, scene_id=scene_id)

    marker_repo.get_by_map_and_scene.assert_awaited_once()
    _, _, kwargs = marker_repo.get_by_map_and_scene.mock_calls[0]
    assert kwargs == {"scene_id": uuid.UUID(hex=scene_id), "scene_index": None}
    assert state.scene is None


@pytest.mark.asyncio
async def test_assemble_splits_canonical_and_candidate_map_facts_by_entity_status(
    db_session: AsyncSession,
) -> None:
    nid = uuid.uuid4().hex
    await _create_project(db_session, nid)
    created = await MapConfigService().create(
        db_session,
        nid,
        MapConfigCreate(name="世界", map_type="world", grid_width=4, grid_height=4),
    )
    canonical_location = await _create_entity(
        db_session, nid, entity_type="location", name="正史地点", status="canonical"
    )
    draft_location = await _create_entity(
        db_session, nid, entity_type="location", name="草稿地点", status="draft"
    )
    candidate_location = await _create_entity(
        db_session, nid, entity_type="location", name="待确认地点", status="candidate"
    )
    canonical_character = await _create_entity(
        db_session, nid, entity_type="character", name="正史人物", status="canonical"
    )
    candidate_character = await _create_entity(
        db_session, nid, entity_type="character", name="待确认人物", status="candidate"
    )
    canonical_faction = await _create_entity(
        db_session, nid, entity_type="organization", name="正史势力", status="canonical"
    )
    candidate_faction = await _create_entity(
        db_session, nid, entity_type="organization", name="待确认势力", status="candidate"
    )

    await MapLocationBindingService().batch_create(
        db_session,
        nid,
        created.id,
        MapLocationBindingCreate(
            location_entity_id=str(canonical_location.id),
            hexes=[BindingHex(hex_q=1, hex_r=1, is_center=True)],
        ),
    )
    novel_uuid = uuid.UUID(hex=nid)
    map_uuid = uuid.UUID(created.id)
    await MapLocationBindingRepository().bulk_create(
        db_session,
        novel_uuid,
        map_uuid,
        candidate_location.id,
        [{"hex_q": 2, "hex_r": 1, "is_center": True}],
    )
    await MapLocationBindingRepository().bulk_create(
        db_session,
        novel_uuid,
        map_uuid,
        draft_location.id,
        [{"hex_q": 3, "hex_r": 1, "is_center": True}],
    )
    await MapMarkerService().create(
        db_session,
        nid,
        created.id,
        MapMarkerCreate(
            entity_id=str(canonical_character.id),
            marker_type="character",
            hex_q=1,
            hex_r=1,
            label="正史人物",
        ),
    )
    await MapMarkerRepository().create(
        db_session,
        novel_uuid,
        map_uuid,
        {
            "entity_id": candidate_character.id,
            "marker_type": "character",
            "hex_q": 2,
            "hex_r": 1,
            "label": "待处理人物",
        },
    )
    await MapTerritoryService().create(
        db_session,
        nid,
        created.id,
        MapTerritoryCreate(
            faction_entity_id=str(canonical_faction.id),
            hexes=[TerritoryHex(hex_q=1, hex_r=1)],
        ),
    )
    await MapTerritoryRepository().create_batch(
        db_session,
        novel_uuid,
        map_uuid,
        candidate_faction.id,
        [{"hex_q": 2, "hex_r": 1, "style_override": {}}],
    )

    state = await MapStateAssembler().assemble(db_session, nid, created.id)

    assert {b.location_entity_id for b in state.location_bindings} == {
        str(canonical_location.id),
    }
    assert {b.location_entity_id for b in state.candidate_location_bindings} == {
        str(candidate_location.id),
        str(draft_location.id),
    }
    assert [m.entity_id for m in state.markers] == [str(canonical_character.id)]
    assert [m.entity_id for m in state.candidate_markers] == [
        str(candidate_character.id)
    ]
    assert [t.faction_entity_id for t in state.territories] == [
        str(canonical_faction.id)
    ]
    assert [t.faction_entity_id for t in state.candidate_territories] == [
        str(candidate_faction.id)
    ]
