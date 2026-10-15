"""Real Scene/manuscript boundary, vocabulary projection and HTTP regressions."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import select

from core.errors import ValidationError
from modules.story.outline_state.models import Scene, SceneSpan
from modules.story.outline_state.scene_facade import validate_scene_source_ranges
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClueDecisionRequest,
    MapSpatialClueSourceBinding,
)
from modules.world.map_spatial_clue_service import (
    _evidence_is_current,
    read_spatial_discovery_context,
    review_spatial_clue,
    stage_spatial_discovery,
)
from modules.world.project_vocabulary_models import ProjectVocabularyTerm
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyReviewReceipt,
    VocabularyTermCreate,
    VocabularyTermUpdate,
    vocabulary_evidence_hash,
    vocabulary_proposal_hash,
)
from modules.world.project_vocabulary_service import (
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    persist_reviewed_model_vocabulary_proposal,
    update_project_vocabulary_term,
)
from modules.world.tests.test_map_spatial_clues import QUOTE_ONE, _batch, _clue
from modules.writing.models import WritingDraft


async def _source(db, novel_id, *, index=1, chapter=1, mode="canonical", scene=None):
    text = f"前文。{QUOTE_ONE}后文。"
    digest = hashlib.sha256(text.encode()).hexdigest()
    if scene is None:
        scene = Scene(
            novel_id=uuid.UUID(novel_id),
            scene_index=index,
            status="draft",
            chapter_ids=[str(chapter)],
        )
        db.add(scene)
        await db.flush()
    draft = WritingDraft(
        novel_id=uuid.UUID(novel_id),
        chapter_index=chapter,
        content=text,
        content_hash=digest,
        status="published" if mode == "canonical" else "canonical",
        version_number=1 if mode == "canonical" else 2,
    )
    db.add(draft)
    await db.flush()
    start = text.index(QUOTE_ONE)
    end = start + len(QUOTE_ONE)
    span = SceneSpan(
        novel_id=uuid.UUID(novel_id),
        scene_id=scene.id,
        chapter_index=chapter,
        content_mode=mode,
        source_draft_id=draft.id,
        source_content_hash=digest,
        start_offset=start,
        end_offset=end,
        part_no=0,
        mapping_status="exact",
        status="draft",
    )
    db.add(span)
    await db.flush()
    binding = MapSpatialClueSourceBinding(
        draft_id=str(draft.id),
        chapter_index=chapter,
        content_hash=digest,
        start_offset=start,
        end_offset=end,
        range_hash=hashlib.sha256(QUOTE_ONE.encode()).hexdigest(),
        content_mode=mode,
    )
    evidence = VocabularyEvidence(scene_id=scene.id, quote=QUOTE_ONE, source_hash=digest)
    return scene, draft, span, binding, evidence


def _bound_batch(novel_id, scene, binding, evidence, *, key="a", proposal=None):
    clue = _clue(
        scene_id=str(scene.id), clue_key=key * 64, quote=QUOTE_ONE, type_proposal=proposal
    )
    clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
    batch = _batch(novel_id, str(scene.id), scene.scene_index, [clue])
    batch.source_binding = binding
    return batch


@pytest.mark.parametrize("mode", ["canonical", "working"])
async def test_exact_mode_binding_and_legacy_working_overlay(
    db_session, project_novel_id, mode
):
    canonical = await _source(db_session, project_novel_id)
    working = await _source(
        db_session, project_novel_id, mode="working", scene=canonical[0]
    )
    scene, _, _, binding, evidence = canonical if mode == "canonical" else working
    result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(project_novel_id, scene, binding, evidence),
    )
    assert len(result.accepted) == 1, result.diagnostics
    await validate_scene_source_ranges(
        db_session,
        project_novel_id,
        str(scene.id),
        scene.scene_index,
        [working[3].ranges()[0].model_dump()],
    )
    with pytest.raises(ValidationError, match="revision changed"):
        await validate_scene_source_ranges(
            db_session,
            project_novel_id,
            str(scene.id),
            scene.scene_index,
            [canonical[3].ranges()[0].model_dump()],
        )


@pytest.mark.parametrize(
    "mutation",
    ["outside_span", "wrong_mode", "wrong_range_hash", "forged_canonical_span"],
)
async def test_stage_rejects_forged_bindings(db_session, project_novel_id, mutation):
    scene, _, span, binding, evidence = await _source(
        db_session, project_novel_id, mode="working"
    )
    if mutation == "forged_canonical_span":
        span.content_mode = "canonical"
        binding.content_mode = "canonical"
        await db_session.flush()
    elif mutation == "outside_span":
        binding.start_offset = 0
    elif mutation == "wrong_mode":
        binding.content_mode = "canonical"
    else:
        binding.range_hash = "0" * 64
    result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(project_novel_id, scene, binding, evidence),
    )
    assert not result.result_refs
    assert result.rejected[0].code == "source_binding_invalid"


async def test_type_evidence_rejects_future_scenes_and_unreviewed_boundaries(
    db_session, project_novel_id
):
    scene, _, _, binding, evidence = await _source(db_session, project_novel_id)
    future, _, _, _, future_evidence = await _source(
        db_session, project_novel_id, index=3, chapter=2
    )
    fields = VocabularyTermCreate(kind="relation", name="潮汐暗道")
    run_id = uuid.uuid4()
    proposal = ModelVocabularyProposal(
        **fields.model_dump(),
        proposal_run_id=run_id,
        evidence=[evidence, future_evidence],
        independent_review=VocabularyReviewReceipt(
            reviewer_run_id=uuid.uuid4(),
            proposal_run_id=run_id,
            proposal_hash=vocabulary_proposal_hash("relation", fields),
            evidence_hash=vocabulary_evidence_hash([evidence, future_evidence]),
            verdict="passed",
        ),
    )
    result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(project_novel_id, scene, binding, evidence, proposal=proposal),
    )
    assert not result.result_refs
    assert await db_session.scalar(select(ProjectVocabularyTerm.id)) is None
    future.structure_meta = {"phase1a_fallback": True}
    await db_session.flush()
    assert not await _evidence_is_current(db_session, project_novel_id, future_evidence)


async def test_context_preserves_author_confirmed_types_and_archive_tombstones(
    db_session, project_novel_id
):
    scene, _, _, _, evidence = await _source(db_session, project_novel_id)
    current, _, _, _, _ = await _source(db_session, project_novel_id, index=3, chapter=2)
    proposed = await persist_reviewed_model_vocabulary_proposal(
        db_session,
        project_novel_id,
        ModelVocabularyProposal(
            kind="relation",
            name="潮汐暗道",
            proposal_run_id=uuid.uuid4(),
            evidence=[evidence],
        ),
    )
    adopted = await update_project_vocabulary_term(
        db_session,
        project_novel_id,
        str(proposed["item"].id),
        VocabularyTermUpdate(
            name="作者确认的暗道", expected_revision_id=proposed["item"].revision_id
        ),
    )
    tombstone = await create_project_vocabulary_term(
        db_session,
        project_novel_id,
        VocabularyTermCreate(kind="relation", name="作者拒绝的暗道"),
    )
    await archive_project_vocabulary_term(
        db_session, project_novel_id, str(tombstone.id), tombstone.revision_id
    )
    scene.status = "deleted"
    await db_session.flush()
    context = await read_spatial_discovery_context(
        db_session,
        project_novel_id,
        scene_id=str(current.id),
        scene_index=current.scene_index,
        endpoint_ids=[],
        endpoint_surfaces=["作者拒绝的暗道"],
        type_limit=64,
        clue_limit=128,
    )
    types = {item.id: item for item in context.types}
    assert types[adopted.id].status == "active"
    assert types[adopted.id].evidence == []
    assert types[tombstone.id].status == "archived"
    assert context.types[0].id == tombstone.id


async def test_http_status_query_filters_and_validation(
    db_session, project_novel_id, async_client
):
    scene, _, _, binding, evidence = await _source(db_session, project_novel_id)
    result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(project_novel_id, scene, binding, evidence),
    )
    clue_id = result.accepted[0].clue_id
    row = await db_session.get(MapSpatialClueRecord, clue_id)
    await review_spatial_clue(
        db_session,
        project_novel_id,
        str(clue_id),
        MapSpatialClueDecisionRequest(
            action="reject", expected_fingerprint=row.fingerprint, confirmed=True
        ),
    )
    path = f"/api/world/map-atlas/{project_novel_id}/spatial-clues"
    pending = await async_client.get(path, params={"status": "pending_review"})
    assert pending.status_code == 200, pending.text
    assert pending.json()["total_count"] == 0
    rejected = await async_client.get(path, params={"status": "rejected"})
    assert rejected.json()["total_count"] == 1
    invalid = await async_client.get(path, params={"status": "not-a-status"})
    assert invalid.status_code == 422


@pytest.mark.parametrize("verdict", ["passed", "failed"])
async def test_type_promotion_rechecks_all_evidence_and_failed_review_writes_no_type(
    db_session, project_novel_id, verdict
):
    from modules.world.map_spatial_clue_schemas import MapSpatialClueTypeProposalDraft
    from modules.world.map_spatial_clue_service import spatial_clue_review_hash

    previous, _, _, first_binding, first_evidence = await _source(
        db_session, project_novel_id
    )
    current, _, _, binding, evidence = await _source(
        db_session, project_novel_id, index=2, chapter=2
    )
    fields = VocabularyTermCreate(kind="relation", name="潮汐暗道")
    run_id = uuid.uuid4()
    prior_ref = None
    if verdict == "passed":
        first_batch = _bound_batch(
            project_novel_id, previous, first_binding, first_evidence
        )
        first_clue = first_batch.clues[0]
        first_clue.type_proposal_draft = MapSpatialClueTypeProposalDraft(
            **fields.model_dump(), proposal_run_id=run_id
        )
        first_clue.review.proposal_hash = spatial_clue_review_hash(first_clue)
        first = await stage_spatial_discovery(db_session, project_novel_id, first_batch)
        prior_ref = first.accepted[0]
    proposal = ModelVocabularyProposal(
        **fields.model_dump(),
        proposal_run_id=run_id,
        evidence=[first_evidence, evidence],
        independent_review=VocabularyReviewReceipt(
            reviewer_run_id=uuid.uuid4(),
            proposal_run_id=run_id,
            proposal_hash=vocabulary_proposal_hash("relation", fields),
            evidence_hash=vocabulary_evidence_hash([first_evidence, evidence]),
            verdict=verdict,
        ),
    )
    result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(
            project_novel_id, current, binding, evidence, key="b", proposal=proposal
        ),
    )
    term = await db_session.scalar(select(ProjectVocabularyTerm))
    if verdict == "failed":
        assert result.pending[0].status == "pending_verification"
        assert term is None
    else:
        assert len(result.accepted) == 1, result.diagnostics
        assert term.status == "active"
        source = await db_session.get(MapSpatialClueRecord, prior_ref.clue_id)
        target = await db_session.get(MapSpatialClueRecord, result.accepted[0].clue_id)
        merged = await review_spatial_clue(
            db_session,
            project_novel_id,
            str(source.id),
            MapSpatialClueDecisionRequest(
                action="merge",
                expected_fingerprint=source.fingerprint,
                confirmed=True,
                target_clue_id=target.id,
                target_fingerprint=target.fingerprint,
            ),
        )
        assert merged.status == "superseded"


async def test_adopt_revalidates_source_and_does_not_touch_map_heads(
    db_session, project_novel_id
):
    from sqlalchemy import func

    from modules.world.map_atlas_models import MapAtlasRevision

    scene, draft, _, binding, evidence = await _source(db_session, project_novel_id)
    result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(project_novel_id, scene, binding, evidence),
    )
    row = await db_session.get(MapSpatialClueRecord, result.accepted[0].clue_id)
    draft.content = "来源已经改写。"
    draft.content_hash = hashlib.sha256(draft.content.encode()).hexdigest()
    await db_session.flush()
    adopted = await review_spatial_clue(
        db_session,
        project_novel_id,
        str(row.id),
        MapSpatialClueDecisionRequest(
            action="adopt", expected_fingerprint=row.fingerprint, confirmed=True
        ),
    )
    assert adopted.status == "pending_verification"
    assert (
        await db_session.scalar(select(func.count()).select_from(MapAtlasRevision)) == 0
    )


async def test_http_spatial_review_and_list_hide_other_owner_project(
    db_session, project_novel_id, async_client
):
    from modules.account.models import Account
    from modules.project.models import Project

    scene, _, _, binding, evidence = await _source(db_session, project_novel_id)
    staged = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _bound_batch(project_novel_id, scene, binding, evidence),
    )
    row = await db_session.get(MapSpatialClueRecord, staged.accepted[0].clue_id)
    owner = Account(support_code=f"MAP-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.flush()
    project = await db_session.get(Project, uuid.UUID(project_novel_id))
    project.owner_id = owner.id
    await db_session.flush()
    path = f"/api/world/map-atlas/{project_novel_id}/spatial-clues"
    hidden = await async_client.get(path)
    assert hidden.status_code == 404
    denied = await async_client.post(
        f"{path}/{row.id}/review",
        json={
            "action": "reject",
            "expected_fingerprint": row.fingerprint,
            "confirmed": True,
        },
    )
    assert denied.status_code == 404
    await db_session.refresh(row)
    assert row.status == "pending_review"


def test_one_endpoint_identity_cannot_claim_two_states():
    from pydantic import ValidationError as SchemaValidationError

    from modules.world.map_spatial_clue_schemas import MapSpatialClue

    scene_id, entity_id = str(uuid.uuid4()), str(uuid.uuid4())
    clue = _clue(scene_id=scene_id, clue_key="e" * 64, quote=QUOTE_ONE).model_dump(
        mode="json"
    )
    clue["subject"] = {"entity_id": entity_id, "state": "canonical"}
    clue["target"] = {"entity_id": entity_id, "state": "candidate"}
    with pytest.raises(SchemaValidationError, match="conflicting states"):
        MapSpatialClue.model_validate(clue)


@pytest.mark.parametrize("field", ["transport_type", "traveler_type"])
def test_journey_attribute_type_kind_matches_its_semantic_role(field):
    from pydantic import ValidationError as SchemaValidationError

    from modules.world.map_spatial_clue_schemas import MapSpatialClueAttributes

    with pytest.raises(SchemaValidationError, match="vocabulary kind"):
        MapSpatialClueAttributes.model_validate(
            {
                field: {
                    "type_ref": uuid.uuid4(),
                    "type_revision_id": uuid.uuid4(),
                    "kind": "level",
                }
            }
        )


@pytest.mark.parametrize("outside_quote", ["前文。", "后文。"])
async def test_type_quote_never_uses_paragraph_context_outside_the_scene(
    db_session, project_novel_id, outside_quote
):
    _, _, _, _, evidence = await _source(db_session, project_novel_id)
    evidence.quote = outside_quote
    assert not await _evidence_is_current(
        db_session, project_novel_id, evidence, content_mode="canonical"
    )
