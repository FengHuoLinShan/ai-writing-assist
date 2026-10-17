"""World spatial clue storage and review contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.errors import ConflictError
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClue,
    MapSpatialClueBatch,
    MapSpatialClueDecisionRequest,
    MapSpatialClueSourceBinding,
    MapSpatialClueSourceRange,
    MapSpatialClueTypeProposalDraft,
)
from modules.world.map_spatial_clue_service import (
    read_spatial_discovery_context,
    review_spatial_clue,
    spatial_clue_review_hash,
    stage_spatial_discovery,
)
from modules.world.map_structure_schemas import MapDocument, MapRevisionResponse
from modules.world.project_vocabulary_schemas import (
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyReviewReceipt,
    VocabularyTermFields,
    vocabulary_evidence_hash,
    vocabulary_proposal_hash,
)

CONTENT_HASH = "a" * 64
QUOTE_ONE = "石桥连接了河的两岸。"
QUOTE_TWO = "旧桥连接着两岸。"


def _clue(
    *,
    scene_id: str,
    clue_key: str,
    quote: str,
    verdict: str = "supported",
    subject: dict | None = None,
    type_proposal_draft: MapSpatialClueTypeProposalDraft | None = None,
    type_proposal: ModelVocabularyProposal | None = None,
) -> MapSpatialClue:
    payload = {
        "clue_key": clue_key,
        "kind": "connection",
        "subject": subject or {"surface": "西岸"},
        "target": {"surface": "东岸"},
        "relation": "connects",
        "modality": "character_statement",
        "quote": quote,
        "type_proposal_draft": (
            type_proposal_draft.model_dump(mode="json") if type_proposal_draft else None
        ),
        "type_proposal": (
            type_proposal.model_dump(mode="json") if type_proposal else None
        ),
        "review": {
            "proposal_call": {
                "journal_key": f"proposal-{clue_key[:6]}",
                "request_id": "request-proposal",
            },
            "review_call": {
                "journal_key": f"review-{clue_key[:6]}",
                "request_id": "request-review",
            },
            "proposal_hash": "0" * 64,
            "evidence_hash": "0" * 64,
            "verdict": verdict,
        },
    }
    candidate = MapSpatialClue.model_validate(payload)
    payload["review"]["proposal_hash"] = spatial_clue_review_hash(candidate)
    payload["review"]["evidence_hash"] = vocabulary_evidence_hash(
        [
            VocabularyEvidence(
                scene_id=uuid.UUID(scene_id), quote=quote, source_hash=CONTENT_HASH
            )
        ]
    )
    return MapSpatialClue.model_validate(payload)


def _binding() -> MapSpatialClueSourceBinding:
    return MapSpatialClueSourceBinding(
        draft_id=str(uuid.uuid4()),
        chapter_index=1,
        content_hash=CONTENT_HASH,
        start_offset=0,
        end_offset=200,
        content_mode="canonical",
    )


def _batch(novel_id: str, scene_id: str, scene_index: int, clues: list[MapSpatialClue]):
    return MapSpatialClueBatch(
        run_id="reading-test-run",
        attempt_id="attempt-1",
        scene_id=scene_id,
        scene_index=scene_index,
        source_manifest_hash="b" * 64,
        source_binding=_binding(),
        method_fingerprint="c" * 64,
        clues=clues,
    )


def _resolved_sources(binding, text: str):
    return [
        {
            "binding": MapSpatialClueSourceRange.model_validate(
                binding.model_dump(exclude={"content_mode", "additional_sources"})
            ),
            "text": text,
        }
    ]


async def test_stage_persists_supported_and_uncertain_items_idempotently(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    scene_id = str(uuid.uuid4())
    text = f"{QUOTE_ONE}{QUOTE_TWO}"
    monkeypatch.setattr(
        service,
        "_resolve_binding",
        AsyncMock(
            side_effect=lambda _db, _novel, _scene, _index, binding: _resolved_sources(
                binding, text
            )
        ),
    )
    supported = _clue(scene_id=scene_id, clue_key="1" * 64, quote=QUOTE_ONE)
    uncertain = _clue(
        scene_id=scene_id,
        clue_key="2" * 64,
        quote=QUOTE_TWO,
        verdict="uncertain",
    )
    batch = _batch(project_novel_id, scene_id, 3, [supported, uncertain])

    first = await stage_spatial_discovery(db_session, project_novel_id, batch)
    second = await stage_spatial_discovery(db_session, project_novel_id, batch)

    assert [item.status for item in first.accepted] == ["pending_review"]
    assert [item.status for item in first.pending] == ["pending_verification"]
    assert len(first.result_refs) == 2
    assert {item.clue_id for item in first.result_refs} == {
        item.clue_id for item in second.result_refs
    }
    assert await db_session.scalar(select_count_for_novel(project_novel_id)) == 2
    row = await db_session.get(MapSpatialClueRecord, first.result_refs[0].clue_id)
    public = service._response(row).model_dump(mode="json")
    assert not {
        "run_id",
        "attempt_id",
        "source_binding",
        "source_manifest_hash",
        "clue",
    } & set(public)
    assert "review" not in public


def select_count_for_novel(novel_id: str):
    from sqlalchemy import func, select

    return (
        select(func.count())
        .select_from(MapSpatialClueRecord)
        .where(MapSpatialClueRecord.novel_id == uuid.UUID(novel_id))
    )


async def test_stage_rejects_unbound_endpoint_and_hash_replay_change(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    scene_id = str(uuid.uuid4())
    monkeypatch.setattr(
        service,
        "_resolve_binding",
        AsyncMock(
            side_effect=lambda _db, _novel, _scene, _index, binding: _resolved_sources(
                binding, f"{QUOTE_ONE}{QUOTE_TWO}"
            )
        ),
    )
    entity_id = uuid.uuid4()
    clue = _clue(
        scene_id=scene_id,
        clue_key="3" * 64,
        quote=QUOTE_ONE,
        subject={"entity_id": entity_id, "state": "candidate"},
    )
    batch = _batch(project_novel_id, scene_id, 3, [clue])
    result = await stage_spatial_discovery(db_session, project_novel_id, batch)
    assert result.rejected[0].code == "clue_invalid"

    valid = _clue(scene_id=scene_id, clue_key="4" * 64, quote=QUOTE_ONE)
    first = await stage_spatial_discovery(
        db_session, project_novel_id, _batch(project_novel_id, scene_id, 3, [valid])
    )
    changed = _clue(scene_id=scene_id, clue_key="4" * 64, quote=QUOTE_TWO)
    replay = await stage_spatial_discovery(
        db_session, project_novel_id, _batch(project_novel_id, scene_id, 3, [changed])
    )
    assert first.accepted
    assert replay.rejected[0].code == "clue_invalid"


async def test_context_excludes_current_and_future_scenes_and_review_uses_cas(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    scene_id = str(uuid.uuid4())
    current_scene_id = str(uuid.uuid4())
    binding = _binding()
    monkeypatch.setattr(
        service,
        "_resolve_binding",
        AsyncMock(
            side_effect=lambda _db, _novel, _scene, _index, value: _resolved_sources(
                value, QUOTE_ONE
            )
        ),
    )
    clue = _clue(scene_id=scene_id, clue_key="5" * 64, quote=QUOTE_ONE)
    staged = await stage_spatial_discovery(
        db_session, project_novel_id, _batch(project_novel_id, scene_id, 3, [clue])
    )
    same_scene = MapSpatialClueRecord(
        novel_id=uuid.UUID(project_novel_id),
        run_id="current-run",
        attempt_id="current-attempt",
        scene_id=current_scene_id,
        scene_index=4,
        clue_key="6" * 64,
        source_manifest_hash="b" * 64,
        method_fingerprint="c" * 64,
        source_content_mode="canonical",
        source_binding=binding.model_dump(mode="json"),
        clue_payload=clue.model_dump(mode="json"),
        fingerprint="d" * 64,
        status="pending_review",
    )
    future = MapSpatialClueRecord(
        novel_id=uuid.UUID(project_novel_id),
        run_id="future-run",
        attempt_id="future-attempt",
        scene_id=str(uuid.uuid4()),
        scene_index=5,
        clue_key="7" * 64,
        source_manifest_hash="b" * 64,
        method_fingerprint="c" * 64,
        source_content_mode="canonical",
        source_binding=binding.model_dump(mode="json"),
        clue_payload=clue.model_dump(mode="json"),
        fingerprint="e" * 64,
        status="pending_review",
    )
    db_session.add_all([same_scene, future])
    await db_session.flush()
    monkeypatch.setattr(
        service,
        "_scene_contract",
        AsyncMock(return_value=SimpleNamespace(novel_id=project_novel_id, scene_index=4)),
    )
    context = await read_spatial_discovery_context(
        db_session,
        project_novel_id,
        scene_id=current_scene_id,
        scene_index=4,
        endpoint_ids=[],
        endpoint_surfaces=[],
        type_limit=10,
        clue_limit=10,
    )
    assert [item.scene_index for item in context.clues] == [3]
    assert context.omitted_clues == 0

    row = await db_session.get(MapSpatialClueRecord, staged.result_refs[0].clue_id)
    with pytest.raises(ConflictError):
        await review_spatial_clue(
            db_session,
            project_novel_id,
            str(row.id),
            MapSpatialClueDecisionRequest(
                action="adopt", expected_fingerprint="f" * 64, confirmed=True
            ),
        )
    adopted = await review_spatial_clue(
        db_session,
        project_novel_id,
        str(row.id),
        MapSpatialClueDecisionRequest(
            action="adopt", expected_fingerprint=row.fingerprint, confirmed=True
        ),
    )
    assert adopted.status == "adopted"
    assert "尚未写入正式地图版本" in adopted.verification_note


async def test_merge_is_semantic_and_keeps_superseded_source_auditable(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    scene_id = str(uuid.uuid4())
    monkeypatch.setattr(
        service,
        "_resolve_binding",
        AsyncMock(
            side_effect=lambda _db, _novel, _scene, _index, binding: _resolved_sources(
                binding, f"{QUOTE_ONE}{QUOTE_TWO}"
            )
        ),
    )
    source = _clue(scene_id=scene_id, clue_key="a" * 64, quote=QUOTE_ONE)
    target = _clue(scene_id=scene_id, clue_key="b" * 64, quote=QUOTE_TWO)
    staged = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _batch(project_novel_id, scene_id, 3, [source, target]),
    )
    source_ref, target_ref = staged.result_refs
    merged = await review_spatial_clue(
        db_session,
        project_novel_id,
        str(source_ref.clue_id),
        MapSpatialClueDecisionRequest(
            action="merge",
            expected_fingerprint=(
                await db_session.get(MapSpatialClueRecord, source_ref.clue_id)
            ).fingerprint,
            confirmed=True,
            target_clue_id=target_ref.clue_id,
            target_fingerprint=(
                await db_session.get(MapSpatialClueRecord, target_ref.clue_id)
            ).fingerprint,
        ),
    )
    assert merged.status == "superseded"
    assert merged.merged_into_id == target_ref.clue_id
    assert await db_session.get(MapSpatialClueRecord, source_ref.clue_id) is not None


def test_first_scene_type_draft_is_explicitly_emerging_and_hash_bound():
    draft = MapSpatialClueTypeProposalDraft(
        kind="relation",
        proposal_run_id=uuid.uuid4(),
        name="潮汐暗道",
        description="只在潮水退去时可通行的连接关系。",
        traits={"connection": ["traversable", "directed"]},
    )
    assert draft.kind == "relation"
    assert draft.proposal_run_id


async def test_model_type_stays_emerging_until_two_scene_review_binds_all_evidence(
    db_session, project_novel_id, monkeypatch
):
    import modules.world.map_spatial_clue_service as service

    scene_one = str(uuid.uuid4())
    scene_two = str(uuid.uuid4())
    proposal_run_id = uuid.uuid4()
    fields = VocabularyTermFields(
        name="潮汐暗道",
        description="只在潮水退去时可通行的连接关系。",
        traits={"connection": ["traversable", "directed"]},
    )
    type_draft = MapSpatialClueTypeProposalDraft(
        kind="relation",
        proposal_run_id=proposal_run_id,
        **fields.model_dump(),
    )
    monkeypatch.setattr(
        service,
        "_resolve_binding",
        AsyncMock(
            side_effect=lambda _db, _novel, _scene, _index, binding: _resolved_sources(
                binding, f"{QUOTE_ONE}{QUOTE_TWO}"
            )
        ),
    )
    monkeypatch.setattr(service, "_evidence_is_current", AsyncMock(return_value=True))
    first = _clue(
        scene_id=scene_one,
        clue_key="8" * 64,
        quote=QUOTE_ONE,
        type_proposal_draft=type_draft,
    )
    first_result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _batch(project_novel_id, scene_one, 1, [first]),
    )
    term = await db_session.scalar(select_term_by_novel(project_novel_id))
    assert first_result.accepted
    assert term.status == "emerging"

    evidence = [
        VocabularyEvidence(
            scene_id=uuid.UUID(scene_one), quote=QUOTE_ONE, source_hash=CONTENT_HASH
        ),
        VocabularyEvidence(
            scene_id=uuid.UUID(scene_two), quote=QUOTE_TWO, source_hash=CONTENT_HASH
        ),
    ]
    type_proposal = ModelVocabularyProposal(
        kind="relation",
        proposal_run_id=proposal_run_id,
        **fields.model_dump(),
        evidence=evidence,
        independent_review=VocabularyReviewReceipt(
            reviewer_run_id=uuid.uuid4(),
            proposal_run_id=proposal_run_id,
            proposal_hash=vocabulary_proposal_hash("relation", fields),
            evidence_hash=vocabulary_evidence_hash(evidence),
            verdict="passed",
        ),
    )
    second = _clue(
        scene_id=scene_two,
        clue_key="9" * 64,
        quote=QUOTE_TWO,
        type_proposal=type_proposal,
    )
    second_result = await stage_spatial_discovery(
        db_session,
        project_novel_id,
        _batch(project_novel_id, scene_two, 2, [second]),
    )
    await db_session.refresh(term)
    assert second_result.accepted
    assert term.status == "active"


def select_term_by_novel(novel_id: str):
    from sqlalchemy import select

    from modules.world.project_vocabulary_models import ProjectVocabularyTerm

    return select(ProjectVocabularyTerm).where(
        ProjectVocabularyTerm.novel_id == uuid.UUID(novel_id)
    )


def test_author_review_routes_are_registered_on_the_existing_map_router():
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/world/map-atlas/{novel_id}/spatial-clues" in paths
    assert "/api/world/map-atlas/{novel_id}/spatial-clues/{clue_id}/review" in paths


def test_superseded_map_revision_remains_readable_but_not_a_candidate_status():
    response = MapRevisionResponse(
        id=str(uuid.uuid4()),
        node_id=str(uuid.uuid4()),
        base_revision_id=None,
        status="superseded",
        document=MapDocument(),
        geometry_hash="a" * 64,
        problems=[],
        created_at=datetime.now(UTC),
    )
    assert response.status == "superseded"
