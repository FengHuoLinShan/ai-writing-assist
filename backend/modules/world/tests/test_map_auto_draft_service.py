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
    MapAutoDraftRedoRequest,
    MapAutoDraftResumeRequest,
    MapAutoDraftTrayPlacementPreviewRequest,
    MapAutoDraftTrayPlacementRequest,
)
from modules.world.map_auto_draft_service import (
    build_map_auto_drafts,
    list_map_auto_drafts,
    place_map_auto_draft_tray_item,
    preview_map_auto_draft_tray_placement,
    redo_map_auto_drafts,
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
from modules.world.map_structure_schemas import (
    MapPoint,
    MapRevisionReview,
    MapSaveRequest,
    SpatialValidity,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity, EntityRelation
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
    effective=None,
    kind="connection",
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
    clue.kind = kind
    clue.attributes.effective = (
        SpatialValidity(start={"kind": "scene", "id": scene.id})
        if effective is True
        else effective
    )
    if kind == "journey":
        clue.attributes.transport_label = "步行"
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
    scene, _start, _end, clue_row = await _stage_bound_clue(db_session, project_novel_id)
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
    original = await db_session.get(MapAtlasRevision, revision.id)
    assert original.status == "rejected"
    with pytest.raises(ConflictError, match="只能恢复已保存"):
        await MapStructureService().review(
            db_session,
            project_novel_id,
            str(original.node_id),
            str(original.id),
            MapRevisionReview(action="restore", base_revision_id=saved.id),
        )


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
    assert new_row.base_revision_id == old_row.id
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
    listed = await list_map_auto_drafts(db_session, project_novel_id)
    assert listed.items[0].node.id == str(new_row.node_id)
    assert listed.items[0].node.current_revision_id is None
    assert listed.items[0].node.status == "provisional"
    assert listed.items[0].node.level == "region"
    assert listed.items[0].review_base_revision_id is None
    view = await MapStructureService().get_map(
        db_session, project_novel_id, str(new_row.node_id)
    )
    assert view.candidates[0].is_auto_draft is True
    assert view.candidates[0].base_revision_id == str(old_row.id)
    assert view.candidates[0].review_base_revision_id is None
    await MapStructureService().review(
        db_session,
        project_novel_id,
        str(new_row.node_id),
        str(new_row.id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift", [None, "source", "verification", "identity", "hierarchy"]
)
async def test_batch_cursor_resumes_long_build_without_truncating_shards(
    db_session, project_novel_id, drift
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
    if drift:
        if drift == "source":
            _draft.content_hash = "f" * 64
        elif drift == "verification":
            row = await db_session.get(MapSpatialClueRecord, staged.accepted[0].clue_id)
            row.status = "pending_verification"
        elif drift == "identity":
            replacement = CoreEntity(
                novel_id=uuid.UUID(project_novel_id),
                entity_type="location",
                name="新的东岸",
                status="canonical",
            )
            db_session.add(replacement)
            await db_session.flush()
            end.status = "merged"
            end.content_json = {"merged_into": str(replacement.id)}
        else:
            db_session.add(
                EntityRelation(
                    novel_id=uuid.UUID(project_novel_id),
                    source_id=end.id,
                    target_id=start.id,
                    relation_kind="spatial",
                    relation_type="located_at",
                    status="canonical",
                )
            )
        await db_session.flush()
        resumed = await resume_map_auto_drafts(
            db_session,
            project_novel_id,
            str(first.batch_id),
            MapAutoDraftResumeRequest(
                expected_fingerprint=first.fingerprint, confirmed=True
            ),
        )
        assert resumed.status == "stale"
        assert resumed.cursor == 20
        assert len(resumed.revisions) == 20
        return
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
    first_page = await list_map_auto_drafts(db_session, project_novel_id, limit=10)
    last_page = await list_map_auto_drafts(
        db_session, project_novel_id, limit=10, offset=20
    )
    assert first_page.total_count == last_page.total_count == 21
    assert first_page.truncated is True
    assert last_page.truncated is False
    assert len(last_page.items) == 1
    assert not (
        {item.revision_id for item in first_page.items}
        & {item.revision_id for item in last_page.items}
    )


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
@pytest.mark.parametrize("kind", ["connection", "journey", "tray"])
async def test_drafts_keep_effective_range_and_exact_citation(
    db_session, project_novel_id, kind
):
    scene, _start, _end, clue_row = await _stage_bound_clue(
        db_session,
        project_novel_id,
        effective=True,
        kind="connection" if kind == "tray" else kind,
        modality="character_statement" if kind == "tray" else "event_observed",
    )
    validity = SpatialValidity(start={"kind": "scene", "id": scene.id})
    draft = await db_session.get(
        WritingDraft, uuid.UUID(clue_row.source_binding["draft_id"])
    )
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue_row)
    )
    ref = result.revisions[0]
    if kind == "tray":
        tray = result.tray_items[0]
        ref = next(item for item in result.revisions if item.node_id == tray.node_id)
        args = (
            db_session,
            project_novel_id,
            str(result.batch_id),
            str(tray.node_id),
            str(ref.revision_id),
            str(tray.item_id),
        )
        request = MapAutoDraftTrayPlacementPreviewRequest(
            expected_fingerprint=tray.fingerprint,
            point=MapPoint(x=110, y=120),
        )
        preview = await preview_map_auto_draft_tray_placement(*args, request)
        placed = await place_map_auto_draft_tray_item(
            *args,
            MapAutoDraftTrayPlacementRequest(
                **request.model_dump(),
                preview_fingerprint=preview.preview_fingerprint,
                confirmed=True,
            ),
        )
        ref = placed
    revision = await db_session.get(MapAtlasRevision, ref.revision_id)
    features = [item for item in revision.document["features"] if item["entity_id"]]
    assert features
    for feature in features:
        assert feature["effective"] == validity.model_dump(mode="json")
        assert feature["modality"] == (
            "character_statement" if kind == "tray" else "event_observed"
        )
        assert feature["sources"][0]["quote"] == QUOTE_ONE
        assert feature["sources"][0]["source_hash"] == draft.content_hash
    if kind != "tray":
        relations = revision.document["journeys" if kind == "journey" else "constraints"]
        assert relations[0]["effective"] == validity.model_dump(mode="json")


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


@pytest.mark.asyncio
async def test_working_candidate_place_never_becomes_restorable_saved_content(
    db_session, project_novel_id
):
    scene, _start, _end, clue = await _stage_bound_clue(
        db_session, project_novel_id, mode="working", entity_status="candidate"
    )
    result = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue)
    )
    ref = result.revisions[0]
    adopted = await MapStructureService().review(
        db_session,
        project_novel_id,
        str(ref.node_id),
        str(ref.revision_id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )
    assert adopted.document.features == []
    original = await db_session.get(MapAtlasRevision, ref.revision_id)
    assert original.status == "rejected"
    saved_rows = (
        await db_session.scalars(
            select(MapAtlasRevision).where(
                MapAtlasRevision.node_id == ref.node_id,
                MapAtlasRevision.status == "saved",
            )
        )
    ).all()
    assert len(saved_rows) == 1
    assert saved_rows[0].document["features"] == []


@pytest.mark.asyncio
async def test_incremental_adoption_preserves_author_label_point_and_lock(
    db_session, project_novel_id
):
    scene, start, end, clue = await _stage_bound_clue(db_session, project_novel_id)
    first = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue)
    )
    ref = first.revisions[0]
    service = MapStructureService()
    adopted = await service.review(
        db_session,
        project_novel_id,
        str(ref.node_id),
        str(ref.revision_id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )
    document = adopted.document.model_copy(deep=True)
    feature = next(item for item in document.features if item.entity_id == start.id)
    feature.label = "作者命名的码头"
    feature.points = [MapPoint(x=90, y=95)]
    feature.locked = True
    saved = await service.save(
        db_session,
        project_novel_id,
        str(ref.node_id),
        MapSaveRequest(base_revision_id=adopted.id, document=document),
    )
    scene2, clue2 = await _stage_related_clue(
        db_session,
        project_novel_id,
        scene_index=2,
        start=start,
        end=end,
    )
    built = await build_map_auto_drafts(
        db_session,
        project_novel_id,
        MapAutoDraftBuildRequest(
            run_id=clue.run_id,
            build_key="incremental-label",
            through_scene_id=scene2.id,
            through_scene_index=scene2.scene_index,
            clue_ids=[clue.id, clue2.id],
        ),
    )
    next_ref = built.revisions[0]
    adopted2 = await service.review(
        db_session,
        project_novel_id,
        str(next_ref.node_id),
        str(next_ref.revision_id),
        MapRevisionReview(action="adopt", base_revision_id=saved.id),
    )
    kept = next(item for item in adopted2.document.features if item.entity_id == start.id)
    assert kept.label == feature.label
    assert kept.points == feature.points
    assert kept.locked is True


@pytest.mark.asyncio
async def test_long_build_key_can_redo_and_old_batches_remain_reachable(
    db_session, project_novel_id
):
    scene, _start, _end, clue = await _stage_bound_clue(db_session, project_novel_id)
    request = _build_request(scene, clue)
    request.build_key = "x" * 120
    first = await build_map_auto_drafts(db_session, project_novel_id, request)
    rebuilt = await redo_map_auto_drafts(
        db_session,
        project_novel_id,
        str(first.batch_id),
        MapAutoDraftRedoRequest(
            expected_fingerprint=first.fingerprint,
            reason="author_requested",
            confirmed=True,
        ),
    )
    assert rebuilt.batch_id != first.batch_id
    assert rebuilt.revisions[0].revision_id != first.revisions[0].revision_id
    for index in range(201):
        db_session.add(
            MapAutoDraftBatchRecord(
                novel_id=uuid.UUID(project_novel_id),
                run_id=clue.run_id,
                build_key=f"empty-batch-{index}",
                through_scene_id=str(scene.id),
                through_scene_index=scene.scene_index,
                input_fingerprint="a" * 64,
                method_fingerprint="b" * 64,
                status="completed",
                cursor=0,
                plan_json={},
                result_refs=[],
                tray_items=[],
                conflicts=[],
            )
        )
    await db_session.flush()
    listed = await list_map_auto_drafts(db_session, project_novel_id, limit=1)
    second = await list_map_auto_drafts(db_session, project_novel_id, limit=1, offset=1)
    assert listed.total_count == second.total_count == 2
    assert listed.batches_truncated is True
    assert listed.truncated is True
    assert second.truncated is False
    assert listed.items[0].batch_id == rebuilt.batch_id
    assert second.items[0].batch_id == first.batch_id


@pytest.mark.asyncio
async def test_g8a_saved_map_with_only_journey_sources_is_a_consumer(
    db_session, project_novel_id
):
    scene, _start, _end, clue = await _stage_bound_clue(
        db_session, project_novel_id, kind="journey"
    )
    built = await build_map_auto_drafts(
        db_session, project_novel_id, _build_request(scene, clue)
    )
    ref = built.revisions[0]
    service = MapStructureService()
    adopted = await service.review(
        db_session,
        project_novel_id,
        str(ref.node_id),
        str(ref.revision_id),
        MapRevisionReview(action="adopt", base_revision_id=None),
    )
    document = adopted.document.model_copy(deep=True)
    for feature in document.features:
        feature.sources = []
    assert document.journeys[0].sources
    saved = await service.save(
        db_session,
        project_novel_id,
        str(ref.node_id),
        MapSaveRequest(base_revision_id=adopted.id, document=document),
    )
    report = await read_map_chapter_consumers(
        db_session,
        project_novel_id,
        chapter_index=1,
        current_draft_id=str(uuid.uuid4()),
        current_source_hash="f" * 64,
    )
    assert [item["revision_id"] for item in report["maps"]] == [saved.id]
