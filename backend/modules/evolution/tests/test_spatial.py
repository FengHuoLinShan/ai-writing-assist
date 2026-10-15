from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.container import container_scope
from core.errors import ConflictError
from core.service_keys import (
    WORLD_BUILD_MAP_AUTO_DRAFTS,
    WORLD_READ_SPATIAL_DISCOVERY_CONTEXT,
)
from modules.evolution.commit import FrozenAttempt
from modules.evolution.llm_sampler import registered_scene_request
from modules.evolution.pipeline import SceneSourceBinding
from modules.evolution.spatial import (
    SPATIAL_METHOD_ID,
    SPATIAL_REVIEW_METHOD_ID,
    SpatialClueProposal,
    SpatialDiscoveryOutput,
    SpatialReviewOutput,
    SpatialTypeProposal,
    _exact_source_hash,
    _make_clues,
    finish_scene_spatial,
    spatial_method_fingerprint,
)
from modules.evolution.spatial_rescan import (
    _resolve_source_content_mode,
    _unresolved_rescan_scenes,
)
from modules.world.contracts import (
    MapSpatialClueContext,
    VocabularyEvidence,
)

SCENE = "他走进旧城，门在东侧，渡口被封了。"
SOURCE_HASH = "a" * 64


def _source(scene_text=SCENE):
    return SceneSourceBinding(
        draft_id=str(uuid4()),
        chapter_index=1,
        content_hash=SOURCE_HASH,
        start_offset=0,
        end_offset=len(scene_text),
    )


def _frozen(scene_index=1, *, scene_text=SCENE):
    return FrozenAttempt(
        novel_id=str(uuid4()),
        run_id="reading-spatial-test",
        attempt_id=str(uuid4()),
        owner_epoch=1,
        producer_version="test",
        source_manifest_hash="b" * 64,
        payload={
            "stage": "verified",
            "scene_id": str(uuid4()),
            "scene_index": scene_index,
            "scene_text": scene_text,
            "source_content_mode": "working",
            "spatial_version": 1,
            "compiled_observations": [
                {
                    "predicate": "走进旧城",
                    "modality": "event_observed",
                    "quote": "他走进旧城",
                    "mentions": [],
                }
            ],
        },
    )


def _clue_output(*, type_proposal=None):
    return SpatialDiscoveryOutput(
        clues=[
            SpatialClueProposal(
                kind="bearing",
                subject_surface="旧城",
                target_surface="门",
                relation="东侧",
                modality="event_observed",
                quote="门在东侧",
                type=type_proposal,
            )
        ],
        coverage_note="已检查本场明确空间线索。",
    )


def _review(*, type_verdict="supported", evidence_indices=None):
    return SpatialReviewOutput(
        reviews=[
            {
                "clue_index": 0,
                "verdict": "supported",
                "reason": "引文明确支持该关系。",
                "type_verdict": type_verdict,
                "reviewed_evidence_indices": evidence_indices or [0],
            }
        ],
        coverage_note="逐项核对了原文。",
    )


def test_spatial_method_fingerprint_is_method_only_and_registered_contracts_bind():
    assert spatial_method_fingerprint() == spatial_method_fingerprint()
    discovery = registered_scene_request(
        "scene_spatial_discovery", {"inputs": {"scene_text": SCENE}}, model="gpt-6-luna"
    )
    review = registered_scene_request(
        "scene_spatial_review", {"inputs": {"scene_text": SCENE}}, model="gpt-6-luna"
    )
    assert discovery[2] == SPATIAL_METHOD_ID
    assert review[2] == SPATIAL_REVIEW_METHOD_ID
    assert discovery[1] is not review[1]


def test_spatial_quotes_must_match_exactly_once_and_one_source_range():
    source = _source()
    assert _exact_source_hash(SCENE, "门在东侧", source) == SOURCE_HASH
    assert _exact_source_hash(SCENE, "门在西侧", source) is None
    assert _exact_source_hash(SCENE + "门在东侧", "门在东侧", source) is None

    first_hash, second_hash = "c" * 64, "d" * 64
    multi_source = SceneSourceBinding(
        draft_id=str(uuid4()),
        chapter_index=1,
        content_hash=first_hash,
        start_offset=0,
        end_offset=8,
        additional_sources=[
            {
                "draft_id": str(uuid4()),
                "chapter_index": 2,
                "content_hash": second_hash,
                "start_offset": 0,
                "end_offset": len(SCENE) - 8,
            }
        ],
    )
    assert _exact_source_hash(SCENE, SCENE[3:8], multi_source) == first_hash
    assert _exact_source_hash(SCENE, SCENE[7:12], multi_source) is None


@pytest.mark.asyncio
async def test_legacy_rescan_resolves_canonical_mode_only_after_unique_source_match(
    monkeypatch,
):
    import modules.evolution.workflow as workflow

    source = _source()
    attempted = []

    async def read_step(db, novel_id, step):
        attempted.append(step["source_content_mode"])
        if step["source_content_mode"] == "canonical":
            return source, SCENE
        raise ConflictError("working source does not match")

    monkeypatch.setattr(workflow, "_read_step", read_step)
    mode = await _resolve_source_content_mode(
        object(),
        "novel",
        {"scene_id": "scene", "scene_index": 0},
        source,
        SCENE,
        None,
    )

    assert mode == "canonical"
    assert attempted == ["working", "canonical"]


@pytest.mark.asyncio
async def test_legacy_rescan_refuses_ambiguous_source_mode(monkeypatch):
    import modules.evolution.workflow as workflow

    source = _source()

    async def read_step(db, novel_id, step):
        return source, SCENE

    monkeypatch.setattr(workflow, "_read_step", read_step)
    with pytest.raises(ConflictError, match="无法唯一验证"):
        await _resolve_source_content_mode(
            object(),
            "novel",
            {"scene_id": "scene", "scene_index": 0},
            source,
            SCENE,
            None,
        )


def test_first_scene_type_requires_semantic_review_and_stays_emerging():
    frozen = _frozen(scene_index=0)
    proposed_type = SpatialTypeProposal(
        kind="space", name="封闭街区", description="边界封闭的街区"
    )
    batch, gaps = _make_clues(
        frozen=frozen,
        source=_source(),
        content_mode="working",
        context=MapSpatialClueContext(),
        discovery=_clue_output(type_proposal=proposed_type),
        review=_review(type_verdict="supported"),
        preparation={"endpoint_ref_map": {}, "allowed_endpoints": {}},
    )
    clue = batch.clues[0]
    assert not gaps
    assert clue.type_proposal_draft is not None
    assert clue.type_proposal_draft.proposal_run_id == UUID(frozen.attempt_id)
    assert clue.type_proposal is None
    assert clue.review.proposal_call.journal_key == "scene_spatial_discovery"
    assert clue.review.review_call.journal_key == "scene_spatial_review"
    assert clue.review.proposal_hash != "0" * 64


def test_second_scene_type_review_binds_original_meaning_and_all_fresh_prior_evidence():
    first_scene_id = uuid4()
    first_proposal_id = uuid4()
    type_item = {
        "id": str(uuid4()),
        "revision_id": str(uuid4()),
        "kind": "space",
        "status": "emerging",
        "source": "model",
        "name": "封闭街区",
        "description": "边界封闭的街区",
        "aliases": [],
        "traits": {},
        "evidence": [
            VocabularyEvidence(
                scene_id=first_scene_id,
                quote="旧城被高墙围住",
                source_hash="e" * 64,
            ).model_dump(mode="json")
        ],
        "proposal_run_id": str(first_proposal_id),
    }
    context = MapSpatialClueContext.model_validate({"types": [type_item]})
    frozen = _frozen(scene_index=1)
    batch, gaps = _make_clues(
        frozen=frozen,
        source=_source(),
        content_mode="working",
        context=context,
        discovery=_clue_output(
            type_proposal=SpatialTypeProposal(
                kind="space", name="封闭街区", description="模型改写不得覆盖原义"
            )
        ),
        review=_review(evidence_indices=[0, 1]),
        preparation={"endpoint_ref_map": {}, "allowed_endpoints": {}},
    )
    proposal = batch.clues[0].type_proposal
    assert not gaps
    assert proposal is not None
    assert proposal.name == "封闭街区"
    assert proposal.description == "边界封闭的街区"
    assert [item.quote for item in proposal.evidence] == [
        "旧城被高墙围住",
        "门在东侧",
    ]
    assert proposal.proposal_run_id == first_proposal_id
    assert proposal.independent_review.proposal_run_id == first_proposal_id
    assert proposal.independent_review.reviewer_run_id == UUID(frozen.attempt_id)
    assert proposal.independent_review.verdict == "passed"


def test_type_review_cannot_claim_complete_support_without_all_evidence():
    prior_scene_id = uuid4()
    prior = VocabularyEvidence(
        scene_id=prior_scene_id,
        quote="旧城被高墙围住",
        source_hash="e" * 64,
    )
    context = MapSpatialClueContext.model_validate(
        {
            "types": [
                {
                    "id": str(uuid4()),
                    "revision_id": str(uuid4()),
                    "kind": "space",
                    "status": "emerging",
                    "source": "model",
                    "name": "封闭街区",
                    "description": "边界封闭的街区",
                    "evidence": [prior.model_dump(mode="json")],
                    "proposal_run_id": str(uuid4()),
                }
            ]
        }
    )
    batch, _ = _make_clues(
        frozen=_frozen(scene_index=1),
        source=_source(),
        content_mode="working",
        context=context,
        discovery=_clue_output(
            type_proposal=SpatialTypeProposal(kind="space", name="封闭街区")
        ),
        review=_review(evidence_indices=[1]),
        preparation={"endpoint_ref_map": {}, "allowed_endpoints": {}},
    )
    assert batch.clues[0].type_proposal is not None
    assert batch.clues[0].type_proposal.independent_review.verdict == "failed"
    assert len(batch.clues[0].type_proposal.evidence) == 2


class _FakeDb:
    async def commit(self):
        return None


class _FakeStore:
    def __init__(self, frozen):
        self.frozen = frozen
        self.run = SimpleNamespace(
            reading_plan_json={"optional_step_quotas": {}}, llm_snapshot_json={}
        )

    async def require_project_owner(self, run_id):
        assert run_id == self.frozen.run_id

    async def load_run(self, run_id, for_update=False):
        return self.run

    async def load_frozen(self, run_id, attempt_id):
        assert run_id == self.frozen.run_id
        assert attempt_id == self.frozen.attempt_id
        return self.frozen

    async def replace_frozen_payload(self, frozen):
        self.frozen = frozen


@pytest.mark.asyncio
async def test_finish_spatial_freezes_only_prior_context_and_independent_journals(
    monkeypatch,
):
    import modules.evolution.pipeline as pipeline

    frozen = _frozen(scene_index=1)
    prior_clue = {
        "clue_id": str(uuid4()),
        "scene_id": str(uuid4()),
        "scene_index": 0,
        "clue_key": "f" * 64,
        "subject": {"surface": "旧城"},
        "target": {"surface": "桥"},
        "kind": "connection",
        "modality": "event_observed",
        "quote": "旧城连着桥",
        "status": "pending_review",
    }
    future_clue = {**prior_clue, "scene_index": 2}
    context = MapSpatialClueContext.model_validate(
        {"clues": [prior_clue, future_clue], "omitted_types": 2}
    )
    proposal = SpatialDiscoveryOutput(
        clues=[
            SpatialClueProposal(
                kind="bearing",
                subject_surface="旧城",
                target_surface="门",
                relation="东侧",
                modality="event_observed",
                quote="门在东侧",
            )
        ],
        coverage_note="检查完成。",
    )
    review = _review()
    calls = []
    context_reads = []

    async def world_context(*args, **kwargs):
        context_reads.append((args, kwargs))
        return context

    async def caller(method, *, inputs):
        calls.append((method, inputs))
        result = proposal if method == "discover_spatial" else review
        return {"result": result.model_dump(mode="json"), "paid_call_receipt": {}}

    async def fake_run(db, store, attempt, source, **kwargs):
        key = kwargs["journal_key"]
        called = await kwargs["call"](**kwargs["call_inputs"])
        payload = {
            **attempt.payload,
            key: {"stage": "sampled", "result": called["result"]},
        }
        updated = attempt.model_copy(update={"payload": payload})
        await store.replace_frozen_payload(updated)
        return updated

    monkeypatch.setattr(pipeline, "_run_scene_call", fake_run)
    store = _FakeStore(frozen)
    with container_scope({WORLD_READ_SPATIAL_DISCOVERY_CONTEXT: world_context}):
        result = await finish_scene_spatial(_FakeDb(), store, frozen, _source(), caller)

    assert [key for key, _ in calls] == ["discover_spatial", "review_spatial"]
    assert context_reads[0][1]["run_id"] == frozen.run_id
    assert context_reads[0][1]["scene_index"] == 1
    discovery_inputs = calls[0][1]
    assert discovery_inputs["scene_text"] == SCENE
    assert "input_manifest" not in discovery_inputs
    assert [item["scene_index"] for item in discovery_inputs["clues"]] == [0]
    assert discovery_inputs["omitted_clues"] == 1
    assert result.payload["scene_spatial_discovery"]["stage"] == "sampled"
    assert result.payload["scene_spatial_review"]["stage"] == "sampled"
    assert result.payload["spatial_discovery_result"]["status"] == "inspected"
    assert result.payload["spatial_discovery_result"]["consumer_read_set"]
    assert (
        result.payload["spatial_discovery_result"]["batch"]["clues"][0]["quote"]
        == "门在东侧"
    )


@pytest.mark.asyncio
async def test_unknown_spatial_call_is_recorded_and_never_reissued(monkeypatch):
    import modules.evolution.pipeline as pipeline

    frozen = _frozen(scene_index=1)
    calls = 0

    async def world_context(*args, **kwargs):
        return MapSpatialClueContext()

    async def fake_run(db, store, attempt, source, **kwargs):
        nonlocal calls
        calls += 1
        payload = {
            **attempt.payload,
            kwargs["journal_key"]: {"stage": "sampling", "input_hash": "c" * 64},
        }
        updated = attempt.model_copy(update={"payload": payload})
        await store.replace_frozen_payload(updated)
        raise pipeline.SamplePendingReconciliationError(
            kwargs["journal_key"], "result unknown"
        )

    monkeypatch.setattr(pipeline, "_run_scene_call", fake_run)
    store = _FakeStore(frozen)
    with container_scope({WORLD_READ_SPATIAL_DISCOVERY_CONTEXT: world_context}):
        first = await finish_scene_spatial(_FakeDb(), store, frozen, _source(), object())
        second = await finish_scene_spatial(_FakeDb(), store, first, _source(), object())

    assert calls == 1
    assert second.payload["spatial_discovery_result"]["status"] == "unknown"
    assert second.payload["optional_step_coverage"]["spatial"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_auto_draft_builder_runs_once_at_aggregate_scene_cutoff():
    import modules.evolution.workflow as workflow

    calls = []
    through_scene_id = uuid4()

    async def build(db, novel_id, request):
        calls.append((novel_id, request))
        return {
            "batch_id": str(uuid4()),
            "status": "running",
            "cursor": 0,
            "total_chunks": 1,
            "completed_chunks": 0,
        }

    class Savepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    class Db:
        def begin_nested(self):
            return Savepoint()

        async def flush(self):
            return None

    run = SimpleNamespace(
        run_key="reading-spatial-test",
        committed_scene_index=5,
        reading_plan_json={
            "spatial_version": 1,
            "steps": [{"scene_index": 5, "scene_id": str(through_scene_id)}],
        },
    )
    with container_scope({WORLD_BUILD_MAP_AUTO_DRAFTS: build}):
        first = await workflow._build_spatial_auto_draft_batch(
            Db(),
            "novel",
            run,
            build_key="evolution-spatial-v1-through-5",
        )
        second = await workflow._build_spatial_auto_draft_batch(
            Db(),
            "novel",
            run,
            build_key="evolution-spatial-v1-through-5",
        )

    assert len(calls) == 1
    assert calls[0][0] == "novel"
    request = calls[0][1]
    assert request.run_id == run.run_key
    assert request.build_key == "evolution-spatial-v1-through-5"
    assert request.through_scene_id == through_scene_id
    assert request.through_scene_index == 5
    assert request.clue_ids is None
    assert first == second
    assert run.reading_plan_json["spatial_auto_draft_builds"][0]["status"] == "running"


def test_rescan_confirmation_requires_true_and_unknown_journals_block_reissue():
    from modules.evolution.spatial_rescan import SpatialRescanStart, _unknown_spatial_call

    base = {
        "operation_id": str(uuid4()),
        "from_scene_index": 0,
        "through_scene_index": 1,
        "expected_fingerprint": "a" * 64,
    }
    with pytest.raises(ValidationError):
        SpatialRescanStart(**{**base, "authorization_confirmed": False})
    assert _unknown_spatial_call({"scene_spatial_discovery": {"stage": "sampling"}})
    assert _unknown_spatial_call({"scene_spatial_review": {"stage": "failed"}})
    assert not _unknown_spatial_call(
        {
            "scene_spatial_discovery": {
                "stage": "failed",
                "paid_call_receipt": {
                    "outcome": "failed_final",
                    "usage": {"usage_complete": True, "unknown_attempts": 0},
                    "attempts_detail": [
                        {"status": "failed", "error_kind": "invalid_json"}
                    ],
                },
            }
        }
    )


@pytest.mark.parametrize(
    ("remaining", "reserve", "calls", "expected"),
    [
        (10, 7, 2, 0),
        (7, 7, 2, 2),
        (5, 7, 2, 4),
        (None, 7, 2, 0),
    ],
)
def test_rescan_budget_fills_mandatory_reserve_before_optional_calls(
    remaining, reserve, calls, expected
):
    from modules.evolution.spatial_rescan import _additional_budget

    assert _additional_budget(remaining, reserve, calls) == expected


@pytest.mark.asyncio
async def test_unknown_rescan_attempt_blocks_a_new_operation_for_its_scene():
    origin = _frozen(scene_index=3)
    frozen = origin.model_copy(
        update={
            "payload": {
                **origin.payload,
                "scene_spatial_review": {"stage": "sampling"},
                "spatial_rescan_origin": {
                    "run_key": "reading-spatial-test",
                    "attempt_id": str(uuid4()),
                },
            }
        }
    )

    class Store:
        async def load_frozen(self, run_key, attempt_id):
            assert run_key == "reading-spatial-test"
            assert attempt_id == frozen.attempt_id
            return frozen

    unresolved = await _unresolved_rescan_scenes(
        Store(),
        "reading-spatial-test",
        {"spatial_rescans": [{"attempt_ids": [frozen.attempt_id]}]},
    )
    assert unresolved == {3}
