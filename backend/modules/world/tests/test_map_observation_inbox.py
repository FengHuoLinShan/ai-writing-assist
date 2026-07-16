"""Project map inbox, proposal and optimistic-review tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapObservation
from modules.world.map_schemas import MapObservationProposalV1
from modules.world.tests.helpers import _create_entity, _create_project


@pytest.mark.parametrize(
    "payload",
    [
        {
            "payload_kind": "proposal",
            "schema_version": 1,
            "proposal_type": "character_location",
            "location_name": "东门",
        },
        {
            "payload_kind": "proposal",
            "schema_version": 1,
            "proposal_type": "event_location",
            "location_name": "王城广场",
        },
        {
            "payload_kind": "proposal",
            "schema_version": 1,
            "proposal_type": "route_state",
            "path_name": "北境古道",
            "state": "blocked",
        },
        {
            "payload_kind": "proposal",
            "schema_version": 1,
            "proposal_type": "boundary",
            "controller_name": "中央议会",
            "area_description": "中州周边",
        },
    ],
)
def test_first_four_map_proposals_are_explicit_unions(payload: dict) -> None:
    parsed = TypeAdapter(MapObservationProposalV1).validate_python(payload)

    assert parsed.payload_kind == "proposal"
    assert parsed.schema_version == 1


def test_map_proposal_rejects_freeform_fields() -> None:
    with pytest.raises(PydanticValidationError):
        TypeAdapter(MapObservationProposalV1).validate_python(
            {
                "payload_kind": "proposal",
                "schema_version": 1,
                "proposal_type": "character_location",
                "location_name": "东门",
                "value_json": {"anything": True},
            }
        )


@pytest.mark.asyncio
async def test_project_inbox_assignment_author_patch_and_confirm_flow(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    character = await _create_entity(
        db_session,
        novel_id,
        entity_type="character",
        name="沈砚",
        status="canonical",
    )
    map_response = await async_client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": "九州",
            "map_type": "world",
            "grid_width": 8,
            "grid_height": 8,
        },
    )
    map_id = map_response.json()["id"]
    created_response = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "沈砚",
            "target_entity_type": "character",
            "dynamic_type": "location",
            "time_anchor": {"kind": "initial_state"},
            "value_json": {
                "payload_kind": "proposal",
                "schema_version": 1,
                "proposal_type": "character_location",
                "location_name": "东门",
            },
            "source_ref": {"source": "manual_baseline"},
            "evidence_text": "沈砚在东门等待。",
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["proposal_type"] == "character_location"
    assert created["normalization_state"] == "untyped"
    assert created["eligibility"]["can_confirm"] is False

    unassigned_response = await async_client.post(
        f"/api/world/maps/project-observations/{created['id']}/assign",
        params={"novel_id": novel_id},
        json={"map_id": None, "expected_updated_at": created["updated_at"]},
    )
    assert unassigned_response.status_code == 200, unassigned_response.text
    unassigned = unassigned_response.json()

    inbox_response = await async_client.get(
        "/api/world/maps/project-observations/inbox",
        params={"novel_id": novel_id, "limit": 20},
    )
    assert inbox_response.status_code == 200, inbox_response.text
    assert inbox_response.json()["total"] == 1
    assert inbox_response.json()["has_more"] is False
    assert inbox_response.json()["items"][0]["id"] == created["id"]

    dashboard_response = await async_client.get(
        f"/api/world/maps/{map_id}/dashboard",
        params={"novel_id": novel_id},
    )
    assert dashboard_response.status_code == 200, dashboard_response.text
    assert dashboard_response.json()["dynamic_queue"] == []

    assigned_response = await async_client.post(
        f"/api/world/maps/project-observations/{created['id']}/assign",
        params={"novel_id": novel_id},
        json={"map_id": map_id, "expected_updated_at": unassigned["updated_at"]},
    )
    assert assigned_response.status_code == 200, assigned_response.text
    assigned = assigned_response.json()

    source_mutation = await async_client.patch(
        f"/api/world/maps/{map_id}/observations/{created['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_updated_at": assigned["updated_at"],
            "source_ref": {"source": "forged"},
        },
    )
    assert source_mutation.status_code == 422

    patched_response = await async_client.patch(
        f"/api/world/maps/{map_id}/observations/{created['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_updated_at": assigned["updated_at"],
            "target_entity_id": str(character.id),
            "spatial_anchor": {"hex_q": 2, "hex_r": 3},
            "value_json": {
                "schema_version": 1,
                "type": "location",
                "movement_mode": "walk",
                "state": "present",
            },
        },
    )
    assert patched_response.status_code == 200, patched_response.text
    patched = patched_response.json()
    assert patched["eligibility"]["can_confirm"] is True

    confirmed_response = await async_client.post(
        f"/api/world/maps/{map_id}/observations/{created['id']}/confirm",
        params={"novel_id": novel_id},
        json={"expected_updated_at": patched["updated_at"]},
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    fact = confirmed_response.json()

    retried_response = await async_client.post(
        f"/api/world/maps/{map_id}/observations/{created['id']}/confirm",
        params={"novel_id": novel_id},
        json={"expected_updated_at": patched["updated_at"]},
    )
    assert retried_response.status_code == 200, retried_response.text
    assert retried_response.json()["id"] == fact["id"]


@pytest.mark.asyncio
async def test_project_assignment_uses_revision_cas(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_response = await async_client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": "九州",
            "map_type": "world",
            "grid_width": 4,
            "grid_height": 4,
        },
    )
    map_id = map_response.json()["id"]
    created_response = await async_client.post(
        f"/api/world/maps/{map_id}/observations",
        params={"novel_id": novel_id},
        json={
            "target_name": "北境古道",
            "dynamic_type": "route_state",
            "time_anchor": {"kind": "initial_state"},
            "value_json": {
                "payload_kind": "proposal",
                "schema_version": 1,
                "proposal_type": "route_state",
                "path_name": "北境古道",
                "state": "blocked",
            },
        },
    )
    created = created_response.json()
    first = await async_client.post(
        f"/api/world/maps/project-observations/{created['id']}/assign",
        params={"novel_id": novel_id},
        json={"map_id": None, "expected_updated_at": created["updated_at"]},
    )
    assert first.status_code == 200, first.text

    stale = await async_client.post(
        f"/api/world/maps/project-observations/{created['id']}/assign",
        params={"novel_id": novel_id},
        json={"map_id": map_id, "expected_updated_at": created["updated_at"]},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"] == "map_observation_revision_conflict"
    assert "context" in stale.json(), stale.text
    assert stale.json()["context"]["latest"]["map_id"] is None


async def _create_test_map(async_client: AsyncClient, novel_id: str) -> dict:
    response = await async_client.post(
        "/api/world/maps",
        params={"novel_id": novel_id},
        json={
            "name": "收件箱测试地图",
            "map_type": "world",
            "grid_width": 8,
            "grid_height": 8,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_test_path(
    async_client: AsyncClient,
    novel_id: str,
    map_id: str,
) -> str:
    response = await async_client.post(
        f"/api/world/maps/{map_id}/editor/apply",
        params={"novel_id": novel_id},
        json={
            "expected_revision": 0,
            "commands": [
                {
                    "type": "path_layer_create",
                    "client_id": "inbox-path-layer",
                    "leaf_client_id": "inbox-path-leaf",
                    "display_name": "测试线路",
                    "category": "transport",
                },
                {
                    "type": "path_create",
                    "client_id": "inbox-path",
                    "data": {
                        "layer_ref": {"client_id": "inbox-path-layer"},
                        "name": "王都大道",
                        "path_type": "major_road",
                        "nodes": [{"q": 1.0, "r": 1.0}, {"q": 3.0, "r": 2.0}],
                    },
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["client_id_map"]["inbox-path"]


@pytest.mark.asyncio
async def test_location_proposal_subtypes_keep_target_and_space_rules(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    character = await _create_entity(
        db_session, novel_id, entity_type="character", name="沈砚", status="canonical"
    )
    event = await _create_entity(
        db_session, novel_id, entity_type="event", name="城门会盟", status="canonical"
    )
    map_data = await _create_test_map(async_client, novel_id)
    path_id = await _create_test_path(async_client, novel_id, map_data["id"])

    async def create_and_patch(
        proposal_type: str,
        target_id: str,
        value_json: dict,
        spatial_anchor: dict,
    ) -> dict:
        created = await async_client.post(
            f"/api/world/maps/{map_data['id']}/observations",
            params={"novel_id": novel_id},
            json={
                "dynamic_type": "location",
                "time_anchor": {"kind": "initial_state"},
                "value_json": {
                    "payload_kind": "proposal",
                    "schema_version": 1,
                    "proposal_type": proposal_type,
                    "location_name": "东门",
                },
            },
        )
        assert created.status_code == 201, created.text
        patched = await async_client.patch(
            f"/api/world/maps/{map_data['id']}/observations/{created.json()['id']}",
            params={"novel_id": novel_id},
            json={
                "expected_updated_at": created.json()["updated_at"],
                "target_entity_id": target_id,
                "spatial_anchor": spatial_anchor,
                "value_json": value_json,
            },
        )
        assert patched.status_code == 200, patched.text
        return patched.json()

    wrong_character_target = await create_and_patch(
        "character_location",
        str(event.id),
        {"schema_version": 1, "type": "location", "state": "present"},
        {"hex_q": 2, "hex_r": 2},
    )
    assert wrong_character_target["proposal_type"] == "character_location"
    assert "target_entity_type" in wrong_character_target["eligibility"]["missing_items"]

    event_path_only = await create_and_patch(
        "event_location",
        str(event.id),
        {
            "schema_version": 1,
            "type": "location",
            "path_id": path_id,
            "state": "occurred",
        },
        {},
    )
    assert event_path_only["proposal_type"] == "event_location"
    assert "location" in event_path_only["eligibility"]["missing_items"]

    for item in (wrong_character_target, event_path_only):
        confirmed = await async_client.post(
            f"/api/world/maps/{map_data['id']}/observations/{item['id']}/confirm",
            params={"novel_id": novel_id},
            json={"expected_updated_at": item["updated_at"]},
        )
        assert confirmed.status_code == 422, confirmed.text
        assert confirmed.json()["error"] == "map_observation_not_eligible"

    assert str(character.id) != str(event.id)


@pytest.mark.asyncio
async def test_author_patch_rejects_null_state_and_rederives_target_metadata(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    character = await _create_entity(
        db_session, novel_id, entity_type="character", name="沈砚", status="canonical"
    )
    map_data = await _create_test_map(async_client, novel_id)
    created = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
        json={
            "target_entity_id": str(character.id),
            "dynamic_type": "status",
            "time_anchor": {"kind": "initial_state"},
            "value_json": {
                "schema_version": 1,
                "type": "status",
                "field_key": "guard",
                "value": "ready",
            },
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()

    for path in (
        f"/api/world/maps/project-observations/{item['id']}",
        f"/api/world/maps/{map_data['id']}/observations/{item['id']}",
    ):
        rejected = await async_client.patch(
            path,
            params={"novel_id": novel_id},
            json={"expected_updated_at": item["updated_at"], "review_state": None},
        )
        assert rejected.status_code == 422, rejected.text

    forged = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/observations/{item['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_updated_at": item["updated_at"],
            "target_entity_type": "event",
            "target_name": "伪造名称",
        },
    )
    assert forged.status_code == 200, forged.text
    assert forged.json()["target_entity_type"] == "character"
    assert forged.json()["target_name"] == "沈砚"


@pytest.mark.asyncio
async def test_project_inbox_filters_aliases_and_full_result_before_pagination(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    nid = uuid.UUID(novel_id)
    for index in range(21):
        db_session.add(
            MapObservation(
                novel_id=nid,
                map_id=None,
                target_name=f"候选 {index}",
                dynamic_type="position_change",
                time_anchor={"kind": "initial_state"},
                value_json={
                    "payload_kind": "proposal",
                    "schema_version": 1,
                    "proposal_type": "character_location",
                    "location_name": "东门",
                },
                confidence=0.2 if index == 20 else 0.9,
                review_state="candidate",
                source_ref={"source": "late-source" if index == 20 else "common"},
            )
        )
    await db_session.flush()

    response = await async_client.get(
        "/api/world/maps/project-observations/inbox",
        params={
            "novel_id": novel_id,
            "dynamic_type": "location",
            "source": "late-source",
            "confidence": "low",
            "eligibility": "missing",
            "skip": 0,
            "limit": 20,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["has_more"] is False
    assert [item["target_name"] for item in response.json()["items"]] == ["候选 20"]


@pytest.mark.asyncio
async def test_stale_patch_and_mixed_batch_leave_every_item_unmodified(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4().hex
    await _create_project(db_session, novel_id)
    map_data = await _create_test_map(async_client, novel_id)

    async def create_status(name: str) -> dict:
        response = await async_client.post(
            f"/api/world/maps/{map_data['id']}/observations",
            params={"novel_id": novel_id},
            json={
                "target_name": name,
                "dynamic_type": "status",
                "time_anchor": {"kind": "initial_state"},
                "value_json": {
                    "schema_version": 1,
                    "type": "status",
                    "field_key": "state",
                    "value": "ready",
                },
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = await create_status("第一条")
    second = await create_status("第二条")
    bumped = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/observations/{second['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_updated_at": second["updated_at"],
            "target_name": "第二条新版",
        },
    )
    assert bumped.status_code == 200, bumped.text

    stale_patch = await async_client.patch(
        f"/api/world/maps/{map_data['id']}/observations/{second['id']}",
        params={"novel_id": novel_id},
        json={
            "expected_updated_at": second["updated_at"],
            "target_name": "不应写入",
        },
    )
    assert stale_patch.status_code == 409, stale_patch.text
    assert stale_patch.json()["context"]["latest"]["target_name"] == "第二条新版"

    batch = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations/batch-review",
        params={"novel_id": novel_id},
        json={
            "items": [
                {
                    "observation_id": first["id"],
                    "expected_updated_at": first["updated_at"],
                },
                {
                    "observation_id": second["id"],
                    "expected_updated_at": second["updated_at"],
                },
            ],
            "action": "confirm",
        },
    )
    assert batch.status_code == 409, batch.text

    observations = await async_client.get(
        f"/api/world/maps/{map_data['id']}/observations",
        params={"novel_id": novel_id},
    )
    by_id = {item["id"]: item for item in observations.json()["items"]}
    assert by_id[first["id"]]["review_state"] == "candidate"
    assert by_id[second["id"]]["review_state"] == "candidate"
    facts = await async_client.get(
        f"/api/world/maps/{map_data['id']}/facts",
        params={"novel_id": novel_id},
    )
    assert facts.json()["total"] == 0


@pytest.mark.asyncio
async def test_project_observation_endpoints_isolate_novels_and_reject_archived_map(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_a = uuid.uuid4().hex
    novel_b = uuid.uuid4().hex
    await _create_project(db_session, novel_a)
    await _create_project(db_session, novel_b)
    map_a = await _create_test_map(async_client, novel_a)
    created = await async_client.post(
        f"/api/world/maps/{map_a['id']}/observations",
        params={"novel_id": novel_a},
        json={
            "target_name": "跨项目不可见",
            "dynamic_type": "status",
            "time_anchor": {"kind": "initial_state"},
            "value_json": {
                "schema_version": 1,
                "type": "status",
                "field_key": "state",
                "value": "ready",
            },
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()

    hidden_inbox = await async_client.get(
        "/api/world/maps/project-observations/inbox",
        params={"novel_id": novel_b},
    )
    assert hidden_inbox.status_code == 200
    assert hidden_inbox.json()["items"] == []

    for method, suffix, payload in (
        (
            "patch",
            "",
            {"expected_updated_at": item["updated_at"], "target_name": "不可写入"},
        ),
        (
            "post",
            "/assign",
            {"expected_updated_at": item["updated_at"], "map_id": None},
        ),
        (
            "post",
            "/ignore",
            {"expected_updated_at": item["updated_at"]},
        ),
    ):
        response = await async_client.request(
            method,
            f"/api/world/maps/project-observations/{item['id']}{suffix}",
            params={"novel_id": novel_b},
            json=payload,
        )
        assert response.status_code == 404, response.text

    unassigned = await async_client.post(
        f"/api/world/maps/project-observations/{item['id']}/assign",
        params={"novel_id": novel_a},
        json={"expected_updated_at": item["updated_at"], "map_id": None},
    )
    assert unassigned.status_code == 200, unassigned.text
    archived = await async_client.post(
        f"/api/world/maps/{map_a['id']}/archive",
        params={"novel_id": novel_a},
    )
    assert archived.status_code == 200, archived.text
    rejected_assignment = await async_client.post(
        f"/api/world/maps/project-observations/{item['id']}/assign",
        params={"novel_id": novel_a},
        json={
            "expected_updated_at": unassigned.json()["updated_at"],
            "map_id": map_a["id"],
        },
    )
    assert rejected_assignment.status_code == 404, rejected_assignment.text
    assert rejected_assignment.json()["error"] == "map_not_found"
