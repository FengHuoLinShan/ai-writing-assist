"""Deterministic map draft construction and adoption boundaries."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from core.errors import ConflictError
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_schemas import (
    MapAutoDraftBuildRequest,
    MapAutoDraftResumeRequest,
    MapAutoDraftTrayPlacementPreviewRequest,
    MapAutoDraftTrayPlacementRequest,
)
from modules.world.map_auto_draft_service import (
    build_map_auto_drafts,
    list_map_auto_drafts,
    place_map_auto_draft_tray_item,
    preview_map_auto_draft_tray_placement,
    resume_map_auto_drafts,
)
from modules.world.map_source_consumption import read_map_chapter_consumers
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClueBatch,
    MapSpatialClueDecisionRequest,
    MapSpatialClueEndpoint,
    MapSpatialClueEndpointIdentity,
)
from modules.world.map_spatial_clue_service import (
    review_spatial_clue,
    spatial_clue_review_hash,
    stage_spatial_discovery,
)
from modules.world.map_structure_schemas import MapPoint, MapRevisionReview
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity
from modules.world.project_vocabulary_schemas import vocabulary_evidence_hash
from modules.world.tests.test_map_spatial_clue_boundaries import _bound_batch, _source
from modules.world.tests.test_map_spatial_clues import QUOTE_ONE, _clue
from modules.writing.models import WritingDraft


async def _stage_bound_clue(
    db,
    novel_id: str,
    *,
    mode: str = "canonical",
    modality: str = "event_observed",
    entity_status: str = "canonical",
    scene=None,
):
    scene, _draft, _span, binding, evidence = await _source(
        db, novel_id, mode=mode, scene=scene
    )
    start = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="西岸",
        status=entity_status,
    )
    end = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="东岸",
        status=entity_status,
    )
    db.add_all([start, end])
    await db.flush()
    clue = _clue(
        scene_id=str(scene.id),
        clue_key=uuid.uuid4().hex * 2,
        quote=QUOTE_ONE,
        subject={
            "entity_id": str(start.id),
            "state": "canonical" if entity_status == "canonical" else "candidate",
        },
    )
    clue.target = MapSpatialClueEndpoint(
        entity_id=end.id,
        state="canonical" if entity_status == "canonical" else "candidate",
    )
    clue.modality = modality
    clue.review.proposal_hash = spatial_clue_review_hash(clue)
    clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
    batch = _bound_batch(novel_id, scene, binding, evidence, key=uuid.uuid4().hex[:1])
    batch.clues = [clue]
    batch.allowed_endpoint_ids = [
        MapSpatialClueEndpointIdentity(entity_id=start.id, state=clue.subject.state),
        MapSpatialClueEndpointIdentity(entity_id=end.id, state=clue.target.state),
    ]
    staged = await stage_spatial_discovery(db, novel_id, batch)
    assert len(staged.accepted) == 1, staged.diagnostics
    row = await db.get(MapSpatialClueRecord, staged.accepted[0].clue_id)
    return scene, start, end, row


async def _adopt_clue(db, novel_id: str, row: MapSpatialClueRecord):
    return await review_spatial_clue(
        db,
        novel_id,
        str(row.id),
        MapSpatialClueDecisionRequest(
            action="adopt",
            expected_fingerprint=row.fingerprint,
            confirmed=True,
        ),
    )


async def _stage_related_clue(
    db,
    novel_id: str,
    *,
    scene_index: int,
    start: CoreEntity,
    end: CoreEntity,
):
    scene, _draft, _span, binding, evidence = await _source(
        db,
        novel_id,
        index=scene_index,
        chapter=scene_index,
    )
    clue = _clue(
        scene_id=str(scene.id),
        clue_key=uuid.uuid4().hex * 2,
        quote=QUOTE_ONE,
        subject={"entity_id": str(start.id), "state": "canonical"},
    )
    clue.target = MapSpatialClueEndpoint(entity_id=end.id, state="canonical")
    clue.modality = "event_observed"
    clue.review.proposal_hash = spatial_clue_review_hash(clue)
    clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
    batch = MapSpatialClueBatch(
        run_id="reading-test-run",
        attempt_id=f"attempt-{scene_index}",
        scene_id=str(scene.id),
        scene_index=scene.scene_index,
        source_manifest_hash="b" * 64,
        source_binding=binding,
        method_fingerprint="c" * 64,
        allowed_endpoint_ids=[
            MapSpatialClueEndpointIdentity(entity_id=start.id, state="canonical"),
            MapSpatialClueEndpointIdentity(entity_id=end.id, state="canonical"),
        ],
        clues=[clue],
    )
    staged = await stage_spatial_discovery(db, novel_id, batch)
    assert len(staged.accepted) == 1, staged.diagnostics
    return scene, await db.get(MapSpatialClueRecord, staged.accepted[0].clue_id)


def _build_request(scene, row):
    return MapAutoDraftBuildRequest(
        run_id=row.run_id,
        build_key=f"auto-draft-{uuid.uuid4()}",
        through_scene_id=scene.id,
        through_scene_index=scene.scene_index,
        clue_ids=[row.id],
    )


@pytest.mark.asyncio
async def test_build_aggregates_to_one_deterministic_candidate_and_is_idempotent(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(db_session, project_novel_id)
    await _adopt_clue(db_session, project_novel_id, clue_row)
    request = _build_request(scene, clue_row)

    first = await build_map_auto_drafts(db_session, project_novel_id, request)
    replay = await build_map_auto_drafts(db_session, project_novel_id, request)

    assert first.batch_id == replay.batch_id
    assert first.status == "completed"
    assert len(first.revisions) == 1
    assert first.revisions[0].status == "candidate"
    assert first.revisions[0].feature_count == 3
    revision = await db_session.get(MapAtlasRevision, first.revisions[0].revision_id)
    node = await db_session.get(MapAtlasNode, revision.node_id)
    assert revision.status == "candidate"
    assert revision.task_id is not None
    assert node.current_revision_id is None
    assert len(revision.document["features"]) == 3
    assert all(feature["points"] for feature in revision.document["features"])
    assert (
        len(
            (
                await db_session.scalars(
                    select(MapAtlasRevision).where(
                        MapAtlasRevision.node_id == node.id,
                        MapAtlasRevision.status == "candidate",
                    )
                )
            ).all()
        )
        == 1
    )


@pytest.mark.asyncio
async def test_pending_verification_clue_has_no_map_or_tray_effect(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(
        db_session, project_novel_id
    )
    clue_row.status = "pending_verification"
    await db_session.flush()

    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )

    assert result.status == "completed"
    assert result.revisions == []
    assert result.tray_items == []


@pytest.mark.asyncio
async def test_non_event_modality_is_tray_only_and_working_source_cannot_be_adopted(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(
        db_session,
        project_novel_id,
        mode="working",
        modality="character_statement",
    )
    await _adopt_clue(db_session, project_novel_id, clue_row)
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )

    assert result.status == "completed"
    assert len(result.revisions) == 2
    for item in result.revisions:
        revision = await db_session.get(MapAtlasRevision, item.revision_id)
        assert not revision.document["features"]
    assert len(result.tray_items) == 2
    assert {item.reason for item in result.tray_items} == {"non_event_modality"}


@pytest.mark.asyncio
async def test_auto_candidate_adoption_uses_normal_gate_and_updates_batch_status(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(db_session, project_novel_id)
    await _adopt_clue(db_session, project_novel_id, clue_row)
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )
    revision_ref = result.revisions[0]
    revision = await db_session.get(MapAtlasRevision, revision_ref.revision_id)

    adopted = await MapStructureService().review(
        db_session,
        project_novel_id,
        str(revision.node_id),
        str(revision.id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )
    assert adopted.status == "saved"
    batch = await db_session.get(MapAutoDraftBatchRecord, result.batch_id)
    assert batch.result_refs[0]["status"] == "saved"
    saved = await db_session.get(MapAtlasRevision, uuid.UUID(adopted.id))
    assert saved.status == "saved"
    assert (await list_map_auto_drafts(db_session, project_novel_id)).items == []


@pytest.mark.asyncio
async def test_auto_adoption_keeps_candidate_world_place_as_text_until_canonical(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(
        db_session,
        project_novel_id,
        entity_status="candidate",
    )
    # Candidate identities remain pending review, and adoption must reduce them
    # to text placeholders rather than canonical map facts.
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )
    assert result.status == "completed"
    revision = await db_session.get(MapAtlasRevision, result.revisions[0].revision_id)
    adopted = await MapStructureService().review(
        db_session,
        project_novel_id,
        str(revision.node_id),
        str(revision.id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )
    saved = await db_session.get(MapAtlasRevision, uuid.UUID(adopted.id))
    features = saved.document["features"]
    assert len(features) == 2
    assert all(item["entity_id"] is None and item["points"] == [] for item in features)
    assert all("待核" in item["note"] for item in features)


@pytest.mark.asyncio
async def test_incremental_batch_supersedes_candidate_and_preserves_positions(
    db_session, project_novel_id
):
    scene, start, end, first_clue = await _stage_bound_clue(db_session, project_novel_id)
    first_result = await build_map_auto_drafts(
        db_session,
        project_novel_id,
        _build_request(scene, first_clue),
    )
    first_revision_ref = first_result.revisions[0]
    first_revision = await db_session.get(
        MapAtlasRevision, first_revision_ref.revision_id
    )
    old_points = {
        item["entity_id"]: item["points"]
        for item in first_revision.document["features"]
        if item["entity_id"]
    }

    next_scene, next_clue = await _stage_related_clue(
        db_session,
        project_novel_id,
        scene_index=2,
        start=start,
        end=end,
    )
    next_request = MapAutoDraftBuildRequest(
        run_id=first_clue.run_id,
        build_key=f"aggregate-{uuid.uuid4()}",
        through_scene_id=next_scene.id,
        through_scene_index=next_scene.scene_index,
        clue_ids=[first_clue.id, next_clue.id],
    )

    updated = await build_map_auto_drafts(db_session, project_novel_id, next_request)
    assert updated.status == "completed"
    assert len(updated.revisions) == 1
    old_row = await db_session.get(MapAtlasRevision, first_revision.id)
    new_row = await db_session.get(MapAtlasRevision, updated.revisions[0].revision_id)
    assert old_row.status == "superseded"
    assert new_row.task_id != first_revision.task_id
    new_points = {
        item["entity_id"]: item["points"]
        for item in new_row.document["features"]
        if item["entity_id"]
    }
    assert new_points == old_points
    pending = (
        await db_session.scalars(
            select(MapAtlasRevision).where(
                MapAtlasRevision.node_id == old_row.node_id,
                MapAtlasRevision.status == "candidate",
            )
        )
    ).all()
    assert len(pending) == 1
    first_batch = await db_session.get(MapAutoDraftBatchRecord, first_result.batch_id)
    assert first_batch.result_refs[0]["status"] == "superseded"


@pytest.mark.asyncio
async def test_batch_cursor_resumes_long_build_without_truncating_shards(
    db_session, project_novel_id
):
    scene, _draft, _span, binding, evidence = await _source(db_session, project_novel_id)
    clues = []
    allowed = []
    for index in range(21):
        start = CoreEntity(
            novel_id=uuid.UUID(project_novel_id),
            entity_type="location",
            name=f"西岸{index:02d}",
            status="canonical",
        )
        end = CoreEntity(
            novel_id=uuid.UUID(project_novel_id),
            entity_type="location",
            name=f"东岸{index:02d}",
            status="canonical",
        )
        db_session.add_all([start, end])
        await db_session.flush()
        clue = _clue(
            scene_id=str(scene.id),
            clue_key=uuid.uuid4().hex * 2,
            quote=QUOTE_ONE,
            subject={"entity_id": str(start.id), "state": "canonical"},
        )
        clue.target = MapSpatialClueEndpoint(entity_id=end.id, state="canonical")
        clue.modality = "event_observed"
        clue.review.proposal_hash = spatial_clue_review_hash(clue)
        clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
        clues.append(clue)
        allowed.extend(
            [
                MapSpatialClueEndpointIdentity(entity_id=start.id, state="canonical"),
                MapSpatialClueEndpointIdentity(entity_id=end.id, state="canonical"),
            ]
        )
    staged = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        MapSpatialClueBatch(
            run_id="reading-test-run",
            attempt_id="attempt-long-run",
            scene_id=str(scene.id),
            scene_index=scene.scene_index,
            source_manifest_hash="b" * 64,
            source_binding=binding,
            method_fingerprint="c" * 64,
            allowed_endpoint_ids=allowed,
            clues=clues,
        ),
    )
    request = MapAutoDraftBuildRequest(
        run_id="reading-test-run",
        build_key=f"long-{uuid.uuid4()}",
        through_scene_id=scene.id,
        through_scene_index=scene.scene_index,
        clue_ids=[item.clue_id for item in staged.accepted],
    )

    first = await build_map_auto_drafts(db_session, project_novel_id, request)

    assert first.status == "running"
    assert first.cursor == 20
    assert first.total_chunks == 21
    assert len(first.revisions) == 20
    resumed = await build_map_auto_drafts(db_session, project_novel_id, request)
    assert resumed.status == "completed"
    replay = await resume_map_auto_drafts(
        db_session,
        project_novel_id,
        str(first.batch_id),
        MapAutoDraftResumeRequest(
            expected_fingerprint=first.fingerprint,
            confirmed=True,
        ),
    )
    assert replay.status == "completed"
    assert replay.batch_id == resumed.batch_id
    assert resumed.cursor == 21
    assert len(resumed.revisions) == 21
    revisions = (
        await db_session.scalars(
            select(MapAtlasRevision).where(
                MapAtlasRevision.context_fingerprint.like(
                    f"auto-draft:{first.batch_id}:%"
                ),
                MapAtlasRevision.status == "candidate",
            )
        )
    ).all()
    assert len(revisions) == 21
    assert len({revision.task_id for revision in revisions}) == 21


@pytest.mark.asyncio
async def test_tray_place_requires_preview_and_is_idempotent(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(
        db_session,
        project_novel_id,
        modality="character_statement",
    )
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )
    tray = result.tray_items[0]
    ref = next(item for item in result.revisions if item.node_id == tray.node_id)
    point = MapPoint(x=120, y=180)
    preview_request = MapAutoDraftTrayPlacementPreviewRequest(
        expected_fingerprint=tray.fingerprint,
        base_revision_id=None,
        space_id="main",
        point=point,
    )
    preview = await preview_map_auto_draft_tray_placement(
        db_session,
        project_novel_id,
        str(result.batch_id),
        str(tray.node_id),
        str(ref.revision_id),
        str(tray.item_id),
        preview_request,
    )
    place_request = MapAutoDraftTrayPlacementRequest(
        **preview_request.model_dump(),
        preview_fingerprint=preview.preview_fingerprint,
        confirmed=True,
    )

    placed = await place_map_auto_draft_tray_item(
        db_session,
        project_novel_id,
        str(result.batch_id),
        str(tray.node_id),
        str(ref.revision_id),
        str(tray.item_id),
        place_request,
    )
    replay = await place_map_auto_draft_tray_item(
        db_session,
        project_novel_id,
        str(result.batch_id),
        str(tray.node_id),
        str(ref.revision_id),
        str(tray.item_id),
        place_request,
    )

    assert placed.revision_id == replay.revision_id
    old_revision = await db_session.get(MapAtlasRevision, ref.revision_id)
    assert old_revision.status == "superseded"
    new_revision = await db_session.get(MapAtlasRevision, placed.revision_id)
    feature = next(
        item
        for item in new_revision.document["features"]
        if item["id"] == placed.placed_feature_id
    )
    assert feature["points"] == [point.model_dump(mode="json")]
    assert feature["locked"] is True
    updated_batch = await db_session.get(MapAutoDraftBatchRecord, result.batch_id)
    assert (
        next(
            item
            for item in updated_batch.tray_items
            if item["item_id"] == str(tray.item_id)
        )["placed_feature_id"]
        == placed.placed_feature_id
    )


@pytest.mark.asyncio
async def test_g8a_reports_only_matching_auto_draft_source_mode(
    db_session, project_novel_id
):
    scene, _start, _end, canonical_clue = await _stage_bound_clue(
        db_session, project_novel_id
    )
    canonical_build = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, canonical_clue)
    )
    canonical_change = await read_map_chapter_consumers(
        db_session,
        project_novel_id,
        chapter_index=1,
        current_draft_id="a-different-canonical-draft",
        current_source_hash="d" * 64,
        content_mode="canonical",
    )

    assert canonical_change["maps"] == []
    assert len(canonical_change["auto_drafts"]) == 1
    assert canonical_change["auto_drafts"][0]["kind"] == "auto_draft"
    assert canonical_change["auto_drafts"][0]["status"] == "candidate"
    assert canonical_change["auto_draft_unverified"] == 0

    _same_scene, _start, _end, working_clue = await _stage_bound_clue(
        db_session,
        project_novel_id,
        mode="working",
        scene=scene,
    )
    await build_map_auto_drafts(
        db_session,
        project_novel_id,
        _build_request(scene, working_clue),
    )
    working_change = await read_map_chapter_consumers(
        db_session,
        project_novel_id,
        chapter_index=1,
        current_draft_id="a-different-working-draft",
        current_source_hash="e" * 64,
        content_mode="working",
    )
    canonical_only = await read_map_chapter_consumers(
        db_session,
        project_novel_id,
        chapter_index=1,
        current_draft_id="a-different-canonical-draft",
        current_source_hash="d" * 64,
        content_mode="canonical",
    )

    assert working_change["maps"] == []
    assert len(working_change["auto_drafts"]) == 1
    assert working_change["auto_draft_unverified"] == 0
    assert len(canonical_only["auto_drafts"]) == 1
    assert (
        canonical_only["auto_drafts"][0]["revision_id"]
        == canonical_build.revisions[0].revision_id.__str__()
    )


@pytest.mark.asyncio
async def test_source_change_marks_auto_draft_stale_and_blocks_adoption(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(db_session, project_novel_id)
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )
    revision = await db_session.get(MapAtlasRevision, result.revisions[0].revision_id)
    draft = await db_session.get(
        WritingDraft, uuid.UUID(clue_row.source_binding["draft_id"])
    )
    draft.content_hash = "f" * 64
    await db_session.flush()

    listed = await list_map_auto_drafts(db_session, project_novel_id)

    assert listed.items[0].stale is True
    assert any("来源" in item for item in listed.items[0].warnings)
    with pytest.raises(ConflictError, match="来源、端点或复核已变化"):
        await MapStructureService().review(
            db_session,
            project_novel_id,
            str(revision.node_id),
            str(revision.id),
            MapRevisionReview(action="adopt", base_revision_id=None),
        )


@pytest.mark.asyncio
async def test_rejecting_source_clue_stales_dependent_auto_draft(
    db_session, project_novel_id
):
    scene, _start, _end, clue_row = await _stage_bound_clue(db_session, project_novel_id)
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )
    rejected = await review_spatial_clue(
        db_session,
        project_novel_id,
        str(clue_row.id),
        MapSpatialClueDecisionRequest(
            action="reject",
            expected_fingerprint=clue_row.fingerprint,
            confirmed=True,
        ),
    )

    assert rejected.status == "rejected"
    batch = await db_session.get(MapAutoDraftBatchRecord, result.batch_id)
    assert batch.status == "stale"
    listed = await list_map_auto_drafts(db_session, project_novel_id)
    assert listed.items[0].stale is True


@pytest.mark.asyncio
async def test_http_list_exposes_resume_progress_and_candidate_preview(
    db_session, project_novel_id, async_client
):
    scene, _start, _end, clue_row = await _stage_bound_clue(db_session, project_novel_id)
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )

    response = await async_client.get(
        f"/api/world/map-atlas/{project_novel_id}/auto-drafts"
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    batch = next(
        item for item in payload["batches"] if item["batch_id"] == str(result.batch_id)
    )
    assert batch["status"] == "completed"
    assert batch["cursor"] == batch["total_chunks"] == 1
    assert payload["items"][0]["revision_id"] == str(result.revisions[0].revision_id)
