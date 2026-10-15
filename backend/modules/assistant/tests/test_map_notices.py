"""Normal product writes produce bounded notices; no model or queue is involved."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from modules.assistant import map_notices, proactive
from modules.assistant.models import AssistantNotice, AssistantRun
from modules.assistant.schemas import NoticeDecision, ProactivePolicy
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.map_spatial_clue_schemas import MapSpatialClueTypeProposalDraft
from modules.world.map_spatial_clue_service import (
    spatial_clue_review_hash,
    stage_spatial_discovery,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapSaveRequest,
    SpatialValidity,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
    _stage_related_clue,
)
from modules.world.tests.test_map_spatial_advisory_integration import seed
from modules.world.tests.test_map_spatial_clue_boundaries import _bound_batch, _source
from modules.world.tests.test_map_spatial_clues import QUOTE_ONE, _clue
from modules.writing.models import WritingDraft


@pytest.fixture
def map_settings(monkeypatch):
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        map_spatial_enabled_capabilities=("assistant.turn",),
    )
    monkeypatch.setattr(map_notices, "get_settings", lambda: settings)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)
    return settings


async def _authorize(db, nid, **kwargs):
    await proactive.save_policy(
        db, nid, ProactivePolicy(enabled=True, categories=["world"], **kwargs)
    )


@pytest.mark.asyncio
async def test_product_batch_default_off_and_no_authorization_do_not_create_notices(
    db_session, test_project_id, map_settings, monkeypatch
):
    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert await db_session.scalar(select(func.count()).select_from(AssistantNotice)) == 0
    await _authorize(db_session, test_project_id)
    monkeypatch.setattr(
        map_notices,
        "get_settings",
        lambda: replace(map_settings, map_spatial_enabled_capabilities=()),
    )
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
    assert await db_session.scalar(select(func.count()).select_from(AssistantRun)) == 0


@pytest.mark.asyncio
async def test_product_tray_batch_coalesces_and_revalidates_source_and_revocation(
    db_session, test_project_id, map_settings, monkeypatch
):
    await _authorize(db_session, test_project_id)
    scene, _a, _b, clue = await _stage_bound_clue(
        db_session, test_project_id, modality="character_statement"
    )
    request = _build_request(scene, clue)
    first = await build_map_auto_drafts(db_session, test_project_id, request)
    visible = (await proactive.list_notices(db_session, test_project_id))["items"]
    assert len(visible) == 1
    assert "待放置地点" in visible[0]["summary"] and "待审核草图" in visible[0]["summary"]
    assert visible[0]["source"] == {
        "type": "map_changes",
        "page": "map",
        "automatic_adoption": False,
        "provider_requests": 0,
    }
    # Idempotent delivery and another normal build keep a single daily notice.
    await proactive.mark_changed(
        db_session, test_project_id, "map_auto_draft_batch", str(first.batch_id)
    )
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert await db_session.scalar(select(func.count()).select_from(AssistantNotice)) == 1
    assert await db_session.scalar(select(func.count()).select_from(AssistantRun)) == 0
    assert (
        await db_session.get(MapAtlasNode, first.revisions[0].node_id)
    ).current_revision_id is None
    assert not await db_session.scalar(
        select(func.count())
        .select_from(MapAtlasRevision)
        .where(MapAtlasRevision.status == "saved")
    )
    # A source edit invalidates the old notice instead of presenting stale detail.
    draft = await db_session.get(WritingDraft, UUID(clue.source_binding["draft_id"]))
    original = draft.content
    draft.content += "来源变更"
    await db_session.flush()
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
    draft.content = original
    await db_session.flush()
    assert (await proactive.list_notices(db_session, test_project_id))["items"]
    # Expiry and revocation are checked again on every listing.
    clock = proactive._now() + timedelta(hours=25)
    with monkeypatch.context() as context:
        context.setattr(proactive, "_now", lambda: clock)
        assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
    await proactive.save_policy(
        db_session, test_project_id, ProactivePolicy(enabled=False)
    )
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
async def test_map_notice_rechecks_exclusions_and_preserves_dismissal(
    db_session, test_project_id, map_settings
):
    await _authorize(db_session, test_project_id)
    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    result = await build_map_auto_drafts(
        db_session, test_project_id, _build_request(scene, clue)
    )
    notice = (await proactive.list_notices(db_session, test_project_id))["items"][0]
    await proactive.decide_notice(
        db_session, notice["id"], NoticeDecision(novel_id=test_project_id, action="read")
    )
    await proactive.mark_changed(
        db_session, test_project_id, "map_auto_draft_batch", str(result.batch_id)
    )
    assert (await proactive.list_notices(db_session, test_project_id))["items"][0][
        "status"
    ] == "read"
    scene2, clue2 = await _stage_related_clue(
        db_session, test_project_id, scene_index=2, start=_a, end=_b
    )
    await build_map_auto_drafts(
        db_session, test_project_id, _build_request(scene2, clue2)
    )
    assert (await proactive.list_notices(db_session, test_project_id))["items"][0][
        "status"
    ] == "unread"
    await proactive.decide_notice(
        db_session,
        notice["id"],
        NoticeDecision(novel_id=test_project_id, action="ignore"),
    )
    await proactive.mark_changed(
        db_session, test_project_id, "map_auto_draft_batch", str(result.batch_id)
    )
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
    await _authorize(
        db_session,
        test_project_id,
        excluded_targets=[f"writing_draft:{clue.source_binding['draft_id']}"],
    )
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["canonical", "working"])
async def test_product_model_type_emergence_is_source_bound(
    db_session, test_project_id, map_settings, mode
):
    await _authorize(db_session, test_project_id)
    scene, draft, _span, binding, evidence = await _source(
        db_session, test_project_id, mode=mode
    )
    clue = _clue(
        scene_id=str(scene.id),
        clue_key="f" * 64,
        quote=QUOTE_ONE,
        type_proposal_draft=MapSpatialClueTypeProposalDraft(
            kind="relation",
            name="雾桥",
            description="本作中的桥型",
            proposal_run_id=uuid4(),
        ),
    )
    batch = _bound_batch(test_project_id, scene, binding, evidence, key="d")
    batch.clues = [clue]
    clue.review.proposal_hash = spatial_clue_review_hash(clue)
    from modules.world.project_vocabulary_schemas import vocabulary_evidence_hash

    clue.review.evidence_hash = vocabulary_evidence_hash([evidence])
    result = await stage_spatial_discovery(db_session, test_project_id, batch)
    assert result.accepted
    if mode == "working":
        assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
        return
    visible = (await proactive.list_notices(db_session, test_project_id))["items"]
    assert len(visible) == 1 and "新空间类型" in visible[0]["summary"]
    assert "雾桥" not in visible[0]["summary"] and QUOTE_ONE not in visible[0]["summary"]
    draft.content += "新内容"
    await db_session.flush()
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
async def test_product_saved_map_with_explicit_scene_reports_author_safe_spatial_findings(
    db_session, test_project_id, map_settings
):
    await _authorize(db_session, test_project_id)
    scene, node, revision, places, _ = await seed(db_session, test_project_id)
    document = MapDocument.model_validate(revision.document)
    for constraint in document.constraints:
        constraint.effective = SpatialValidity(start={"kind": "scene", "id": scene.id})
    saved = await MapStructureService().save(
        db_session,
        test_project_id,
        str(node.id),
        MapSaveRequest(base_revision_id=revision.id, document=document),
    )
    visible = (await proactive.list_notices(db_session, test_project_id))["items"]
    assert len(visible) == 1 and "空间提醒" in visible[0]["summary"]
    assert node.current_revision_id == UUID(saved.id)
    assert await db_session.scalar(select(func.count()).select_from(AssistantRun)) == 0
    places[1].status = "candidate"
    await db_session.flush()
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
async def test_map_notice_respects_shared_daily_ceiling(
    db_session, test_project_id, map_settings
):
    await _authorize(db_session, test_project_id, daily_limit=1)
    db_session.add(
        AssistantNotice(
            novel_id=UUID(test_project_id),
            fingerprint="a" * 64,
            title="原有提醒",
            summary="当天额度已使用",
            result_ref_json={},
        )
    )
    await db_session.flush()
    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert await db_session.scalar(select(func.count()).select_from(AssistantNotice)) == 1


@pytest.mark.asyncio
async def test_map_notice_owner_and_generation_are_checked_again(
    db_session, test_project_id, map_settings
):
    from modules.assistant.models import AssistantWatch

    await _authorize(db_session, test_project_id)
    scene, _a, _b, clue = await _stage_bound_clue(db_session, test_project_id)
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert (await proactive.list_notices(db_session, test_project_id))["items"]
    watch = await db_session.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(test_project_id))
    )
    original = dict(watch.policy_json)
    watch.policy_json = {**original, "owner_id": str(uuid4())}
    await db_session.flush()
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
    watch.policy_json = original
    await _authorize(db_session, test_project_id)
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
async def test_map_save_without_explicit_scene_does_not_guess_spatial_findings(
    db_session, test_project_id, map_settings
):
    await _authorize(db_session, test_project_id)
    _scene, node, revision, _places, _ = await seed(db_session, test_project_id)
    await MapStructureService().save(
        db_session,
        test_project_id,
        str(node.id),
        MapSaveRequest(
            base_revision_id=revision.id,
            document=MapDocument.model_validate(revision.document),
        ),
    )
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("excluded_kind", ["scene", "writing_draft", "world_entity"])
async def test_normal_batch_event_honors_original_source_exclusions(
    db_session, test_project_id, map_settings, excluded_kind
):
    scene, start, _end, clue = await _stage_bound_clue(db_session, test_project_id)
    identity = {
        "scene": str(scene.id),
        "writing_draft": clue.source_binding["draft_id"],
        "world_entity": str(start.id),
    }[excluded_kind]
    await _authorize(
        db_session, test_project_id, excluded_targets=[f"{excluded_kind}:{identity}"]
    )
    await build_map_auto_drafts(db_session, test_project_id, _build_request(scene, clue))
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []


@pytest.mark.asyncio
async def test_real_two_scene_activation_still_notifies_until_author_takes_ownership(
    db_session, test_project_id, map_settings
):
    from modules.world.project_vocabulary_models import ProjectVocabularyTerm
    from modules.world.project_vocabulary_schemas import (
        ModelVocabularyProposal,
        VocabularyReviewReceipt,
        VocabularyTermCreate,
        VocabularyTermUpdate,
        vocabulary_evidence_hash,
        vocabulary_proposal_hash,
    )
    from modules.world.project_vocabulary_service import update_project_vocabulary_term

    await _authorize(db_session, test_project_id)
    first, _draft, _span, first_binding, first_evidence = await _source(
        db_session, test_project_id
    )
    current, _draft, _span, binding, evidence = await _source(
        db_session, test_project_id, index=2, chapter=2
    )
    fields = VocabularyTermCreate(kind="relation", name="潮汐暗道")
    run_id = uuid4()
    first_batch = _bound_batch(test_project_id, first, first_binding, first_evidence)
    first_clue = first_batch.clues[0]
    first_clue.type_proposal_draft = MapSpatialClueTypeProposalDraft(
        **fields.model_dump(), proposal_run_id=run_id
    )
    first_clue.review.proposal_hash = spatial_clue_review_hash(first_clue)
    result = await stage_spatial_discovery(db_session, test_project_id, first_batch)
    assert result.accepted
    term = await db_session.scalar(
        select(ProjectVocabularyTerm).where(
            ProjectVocabularyTerm.novel_id == UUID(test_project_id)
        )
    )
    assert term.status == "emerging"
    notice = (await proactive.list_notices(db_session, test_project_id))["items"][0]
    await proactive.decide_notice(
        db_session, notice["id"], NoticeDecision(novel_id=test_project_id, action="read")
    )
    proposal = ModelVocabularyProposal(
        **fields.model_dump(),
        proposal_run_id=run_id,
        evidence=[first_evidence, evidence],
        independent_review=VocabularyReviewReceipt(
            reviewer_run_id=uuid4(),
            proposal_run_id=run_id,
            proposal_hash=vocabulary_proposal_hash("relation", fields),
            evidence_hash=vocabulary_evidence_hash([first_evidence, evidence]),
            verdict="passed",
        ),
    )
    result = await stage_spatial_discovery(
        db_session,
        test_project_id,
        _bound_batch(
            test_project_id, current, binding, evidence, key="b", proposal=proposal
        ),
    )
    assert result.accepted and term.status == "active" and not term.author_confirmed
    visible = (await proactive.list_notices(db_session, test_project_id))["items"]
    assert len(visible) == 1 and "新空间类型" in visible[0]["summary"]
    assert visible[0]["id"] == notice["id"] and visible[0]["status"] == "unread"
    await update_project_vocabulary_term(
        db_session,
        test_project_id,
        str(term.id),
        VocabularyTermUpdate(
            expected_revision_id=term.current_revision_id, name="作者确认的暗道"
        ),
    )
    assert term.author_confirmed
    assert (await proactive.list_notices(db_session, test_project_id))["items"] == []
    assert await db_session.scalar(select(func.count()).select_from(AssistantNotice)) == 1
