"""Stable imports -> world typed map-candidate seam regressions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.outline.facade import create_scene
from modules.world.contracts import (
    MapBoundaryProposal,
    MapCharacterLocationProposal,
    MapEventLocationProposal,
    MapObservationCandidateAuthorization,
    MapObservationCandidateInput,
    MapRouteStateProposal,
)
from modules.world.facade import create_map_observation_candidates
from modules.world.map_models import MapFact, MapLocationBinding, MapObservation
from modules.world.map_schemas import MapObservationAuthorUpdate
from modules.world.services.map.map_dynamic_service import MapDynamicFactService
from modules.world.tests.helpers import _create_map_config, _create_project
from tests.utils import _create_entity


def _candidate(
    *,
    novel_id: str,
    scene_id: str,
    source_item_key: str,
    proposal,
    target_name: str | None = None,
    target_entity_id: str | None = None,
    resolved_location_entity_id: str | None = None,
    source_workflow: str = "deep_import",
    evidence_text: str = "沈砚抵达青石镇。",
) -> MapObservationCandidateInput:
    return MapObservationCandidateInput(
        workflow_id="workflow-typed-map-1",
        source_workflow=source_workflow,
        task_id="task-typed-map-1",
        source_item_key=source_item_key,
        scene_id=scene_id,
        scene_index=7,
        scene_sequence=0 if source_workflow == "map_enrichment" else None,
        source_chapter_index=3,
        source_start_offset=0 if source_workflow == "map_enrichment" else None,
        source_end_offset=(
            len(evidence_text) if source_workflow == "map_enrichment" else None
        ),
        scene_source_fingerprint="a" * 64,
        context_snapshot_id="snapshot-1",
        evidence_text=evidence_text,
        evidence_anchor="b" * 64,
        confidence=0.91,
        target_entity_id=target_entity_id,
        resolved_location_entity_id=resolved_location_entity_id,
        target_name=target_name,
        proposal=proposal,
        authorization=MapObservationCandidateAuthorization(
            adoption_policy="user_authorized_pipeline",
            authorization_confirmed=True,
            authorized_at=datetime(2026, 7, 15, tzinfo=UTC),
            scope={
                "novel_id": novel_id,
                "start_chapter": 1,
                "end_chapter": 10,
                "stage": (
                    "map_observations" if source_workflow == "map_enrichment" else None
                ),
            },
            snapshot_fingerprint="c" * 64,
        ),
    )


@pytest.mark.parametrize("stage", [None, "world_objects"])
def test_map_enrichment_candidate_contract_rejects_wrong_authorization_stage(
    stage: str | None,
) -> None:
    candidate = _candidate(
        novel_id=uuid.uuid4().hex,
        scene_id=str(uuid.uuid4()),
        source_item_key="map-enrichment-contract",
        source_workflow="map_enrichment",
        target_name="沈砚",
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location",
            location_name="青石镇",
        ),
    )

    wrong_stage = candidate.model_dump(mode="json")
    wrong_stage["authorization"]["scope"]["stage"] = stage
    with pytest.raises(PydanticValidationError, match="scope stage"):
        MapObservationCandidateInput.model_validate(wrong_stage)


def test_map_enrichment_candidate_contract_rejects_evidence_offset_length_mismatch() -> (
    None
):
    candidate = _candidate(
        novel_id=uuid.uuid4().hex,
        scene_id=str(uuid.uuid4()),
        source_item_key="map-enrichment-contract",
        source_workflow="map_enrichment",
        target_name="沈砚",
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location",
            location_name="青石镇",
        ),
    )

    wrong_offset = candidate.model_dump(mode="json")
    wrong_offset["source_end_offset"] += 1
    with pytest.raises(PydanticValidationError, match="evidence text length"):
        MapObservationCandidateInput.model_validate(wrong_offset)


@pytest.mark.parametrize(
    "field_name",
    ["scene_source_fingerprint", "evidence_anchor"],
)
def test_map_candidate_contract_rejects_non_sha256_fingerprint(
    field_name: str,
) -> None:
    candidate = _candidate(
        novel_id=uuid.uuid4().hex,
        scene_id=str(uuid.uuid4()),
        source_item_key="invalid-fingerprint",
        target_name="沈砚",
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location",
            location_name="青石镇",
        ),
    ).model_dump(mode="json")
    candidate[field_name] = "not-a-sha256"

    with pytest.raises(PydanticValidationError):
        MapObservationCandidateInput.model_validate(candidate)


@pytest.mark.asyncio
async def test_map_enrichment_candidate_resolves_entities_and_unique_map_center(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "抵达青石镇", "status": "canonical"},
    )
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    location = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="青石镇",
        status="canonical",
    )
    map_config = await _create_map_config(db_session, novel_id)
    db_session.add(
        MapLocationBinding(
            novel_id=uuid.UUID(novel_id),
            map_id=map_config.id,
            location_entity_id=location.id,
            hex_q=4,
            hex_r=5,
            is_center=True,
        )
    )
    await db_session.flush()
    candidate = _candidate(
        novel_id=novel_id,
        scene_id=scene["id"],
        source_item_key="character-location-resolved",
        source_workflow="map_enrichment",
        target_name="沈砚",
        target_entity_id=str(character.id),
        resolved_location_entity_id=str(location.id),
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location",
            location_name="青石镇",
            movement_mode="walk",
            state="arrived",
        ),
    )

    result = await create_map_observation_candidates(
        db_session,
        novel_id,
        candidates=[candidate],
    )
    observation = await db_session.get(
        MapObservation,
        uuid.UUID(result.items[0].observation_id),
    )
    assert observation is not None
    assert observation.map_id == map_config.id
    assert observation.target_entity_id == character.id
    assert observation.spatial_anchor == {
        "location_entity_id": str(location.id),
        "hex_q": 4,
        "hex_r": 5,
    }
    assert observation.value_json == {
        "schema_version": 1,
        "type": "location",
        "location_entity_id": str(location.id),
        "movement_mode": "walk",
        "state": "arrived",
    }
    assert observation.source_ref["deterministic_map_assignment"] == {
        "status": "assigned_unique_location_center",
        "map_id": str(map_config.id),
    }
    inbox = await MapDynamicFactService().list_observations(
        db_session,
        novel_id,
        map_id=str(map_config.id),
        review_state="candidate",
    )
    assert inbox.items[0].eligibility.can_confirm is True


@pytest.mark.asyncio
async def test_map_enrichment_does_not_assign_hidden_detail_map_center(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "抵达青石镇", "status": "canonical"},
    )
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    location = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="青石镇",
        status="canonical",
    )
    archived_parent = await _create_entity(
        db_session,
        novel_id,
        entity_type="location",
        name="已废弃父地点",
        status="deprecated",
    )
    hidden_map = await _create_map_config(db_session, novel_id)
    hidden_map.parent_entity_id = archived_parent.id
    db_session.add(
        MapLocationBinding(
            novel_id=uuid.UUID(novel_id),
            map_id=hidden_map.id,
            location_entity_id=location.id,
            hex_q=4,
            hex_r=5,
            is_center=True,
        )
    )
    await db_session.flush()

    candidate = _candidate(
        novel_id=novel_id,
        scene_id=scene["id"],
        source_item_key="hidden-map-center",
        source_workflow="map_enrichment",
        target_name="沈砚",
        target_entity_id=str(character.id),
        resolved_location_entity_id=str(location.id),
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location",
            location_name="青石镇",
            state="arrived",
        ),
    )

    result = await create_map_observation_candidates(
        db_session,
        novel_id,
        candidates=[candidate],
    )
    observation = await db_session.get(
        MapObservation,
        uuid.UUID(result.items[0].observation_id),
    )

    assert observation is not None
    assert observation.map_id is None
    assert observation.spatial_anchor == {"location_entity_id": str(location.id)}
    assert observation.source_ref["deterministic_map_assignment"] == {
        "status": "location_has_no_unique_map_center"
    }


@pytest.mark.asyncio
async def test_map_enrichment_rejects_noncanonical_resolved_boundary_target(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "势力边界", "status": "canonical"},
    )
    pending_controller = await _create_entity(
        db_session,
        novel_id,
        entity_type="organization",
        name="玄甲军",
        status="candidate",
    )
    candidate = _candidate(
        novel_id=novel_id,
        scene_id=scene["id"],
        source_item_key="pending-boundary-controller",
        source_workflow="map_enrichment",
        target_name="玄甲军",
        target_entity_id=str(pending_controller.id),
        proposal=MapBoundaryProposal(
            proposal_type="boundary",
            controller_name="玄甲军",
            area_description="控制北岸三镇",
        ),
    )

    with pytest.raises(ValidationError) as exc_info:
        await create_map_observation_candidates(
            db_session,
            novel_id,
            candidates=[candidate],
        )

    assert exc_info.value.code == "map_observation_candidate_target_not_canonical"
    assert await db_session.scalar(select(func.count()).select_from(MapObservation)) == 0


@pytest.mark.asyncio
async def test_candidate_batch_supports_four_proposals_and_reuses_without_fact(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "抵达青石镇", "status": "canonical"},
    )
    candidates = [
        _candidate(
            novel_id=novel_id,
            scene_id=scene["id"],
            source_item_key="character-location-0",
            target_name="沈砚",
            proposal=MapCharacterLocationProposal(
                proposal_type="character_location", location_name="青石镇"
            ),
        ),
        _candidate(
            novel_id=novel_id,
            scene_id=scene["id"],
            source_item_key="event-location-0",
            target_name="旧信之约",
            proposal=MapEventLocationProposal(
                proposal_type="event_location", location_name="石桥"
            ),
        ),
        _candidate(
            novel_id=novel_id,
            scene_id=scene["id"],
            source_item_key="route-state-0",
            proposal=MapRouteStateProposal(
                proposal_type="route_state", path_name="北境商道", state="blocked"
            ),
        ),
        _candidate(
            novel_id=novel_id,
            scene_id=scene["id"],
            source_item_key="boundary-0",
            target_name="玄甲军",
            proposal=MapBoundaryProposal(
                proposal_type="boundary", area_description="控制北岸三镇"
            ),
        ),
    ]

    first = await create_map_observation_candidates(
        db_session, novel_id, candidates=candidates
    )
    second = await create_map_observation_candidates(
        db_session, str(uuid.UUID(novel_id)), candidates=candidates
    )

    assert first.created_count == 4
    assert second.reused_count == 4
    assert [item.observation_id for item in first.items] == [
        item.observation_id for item in second.items
    ]
    assert await db_session.scalar(select(func.count()).select_from(MapFact)) == 0
    observations = list(
        (await db_session.execute(select(MapObservation))).scalars().all()
    )
    assert {item.value_json["proposal_type"] for item in observations} == {
        "character_location",
        "event_location",
        "route_state",
        "boundary",
    }
    assert all(item.map_id is None for item in observations)
    assert all(
        item.source_ref["source"] == "deep_import_typed_map_proposal"
        for item in observations
    )


@pytest.mark.asyncio
async def test_candidate_identity_conflict_fails_closed_without_overwrite(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "抵达青石镇", "status": "canonical"},
    )
    original = _candidate(
        novel_id=novel_id,
        scene_id=scene["id"],
        source_item_key="character-location-0",
        target_name="沈砚",
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location", location_name="青石镇"
        ),
    )
    created = await create_map_observation_candidates(
        db_session, novel_id, candidates=[original]
    )
    observation = await db_session.get(
        MapObservation, uuid.UUID(created.items[0].observation_id)
    )
    observation.target_name = "作者已改名"
    await db_session.flush()

    reused = await create_map_observation_candidates(
        db_session, novel_id, candidates=[original]
    )
    assert reused.reused_count == 1
    assert observation.target_name == "作者已改名"

    changed = original.model_copy(update={"evidence_text": "沈砚仍在旧都。"})
    with pytest.raises(ConflictError) as exc_info:
        await create_map_observation_candidates(
            db_session, novel_id, candidates=[changed]
        )
    assert exc_info.value.code == "map_observation_candidate_payload_conflict"
    assert observation.target_name == "作者已改名"


@pytest.mark.asyncio
async def test_candidate_rejects_authorization_outside_project_scope(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "抵达青石镇", "status": "canonical"},
    )
    candidate = _candidate(
        novel_id=uuid.uuid4().hex,
        scene_id=scene["id"],
        source_item_key="character-location-outside-scope",
        target_name="沈砚",
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location", location_name="青石镇"
        ),
    )

    with pytest.raises(ValidationError) as exc_info:
        await create_map_observation_candidates(
            db_session, novel_id, candidates=[candidate]
        )

    assert exc_info.value.code == "map_observation_candidate_authorization_scope_invalid"
    assert await db_session.scalar(select(func.count()).select_from(MapObservation)) == 0


@pytest.mark.asyncio
async def test_imported_candidate_proposal_type_is_immutable(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    scene = await create_scene(
        db_session,
        novel_id,
        {"scene_index": 7, "title": "抵达青石镇", "status": "canonical"},
    )
    candidate = _candidate(
        novel_id=novel_id,
        scene_id=scene["id"],
        source_item_key="character-location-immutable",
        target_name="沈砚",
        proposal=MapCharacterLocationProposal(
            proposal_type="character_location", location_name="青石镇"
        ),
    )
    created = await create_map_observation_candidates(
        db_session, novel_id, candidates=[candidate]
    )
    observation = await db_session.get(
        MapObservation, uuid.UUID(created.items[0].observation_id)
    )
    assert observation is not None
    assert observation.updated_at is not None

    with pytest.raises(ValidationError) as exc_info:
        await MapDynamicFactService().update_project_observation(
            db_session,
            novel_id,
            observation_id=str(observation.id),
            data=MapObservationAuthorUpdate(
                expected_updated_at=observation.updated_at,
                value_json=MapEventLocationProposal(
                    proposal_type="event_location",
                    location_name="旧都",
                ).model_dump(mode="json"),
            ),
        )

    assert exc_info.value.code == "map_observation_proposal_type_immutable"
    await db_session.refresh(observation)
    assert observation.value_json["proposal_type"] == "character_location"
