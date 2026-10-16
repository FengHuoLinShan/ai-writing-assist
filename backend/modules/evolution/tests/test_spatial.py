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
    def begin_nested(self):
        from contextlib import nullcontext

        return nullcontext()

    async def commit(self):
        return None


class _FakeStore:
    def __init__(self, frozen):
        self.frozen = frozen
        self.run = SimpleNamespace(
            reading_plan_json={
                "optional_step_quotas": {},
                "spatial_method_fingerprint": spatial_method_fingerprint(),
            },
            llm_snapshot_json={},
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
            "fingerprint": "d" * 64,
            "status": "completed",
            "cursor": 1,
            "total_chunks": 1,
            "completed_chunks": 1,
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
    assert run.reading_plan_json["spatial_auto_draft_builds"][0]["status"] == "completed"


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

    class MissingStore:
        async def load_frozen(self, run_key, attempt_id):
            return None

    unresolved = await _unresolved_rescan_scenes(
        MissingStore(),
        "reading-spatial-test",
        {
            "spatial_rescans": [
                {
                    "attempt_ids": [frozen.attempt_id],
                    "from_scene_index": 2,
                    "through_scene_index": 4,
                }
            ]
        },
    )
    assert unresolved == {2, 3, 4}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["missing_run", "missing_entry", "wrong_task", "missing_attempt", "unknown"],
)
async def test_spatial_rescan_handler_fails_closed_before_recovery(monkeypatch, failure):
    import modules.evolution.spatial_rescan as rescan

    operation_id = str(uuid4())
    attempt_id = str(uuid4())
    task_id = str(uuid4())
    frozen = _frozen().model_copy(
        update={
            "attempt_id": attempt_id,
            "payload": {
                **_frozen().payload,
                "spatial_rescan_operation_id": operation_id,
                **(
                    {"scene_spatial_discovery": {"stage": "sampling"}}
                    if failure == "unknown"
                    else {}
                ),
            },
        }
    )
    operation = {
        "operation_id": operation_id,
        "task_id": str(uuid4()) if failure == "wrong_task" else task_id,
        "attempt_ids": [attempt_id],
    }
    run = SimpleNamespace(
        status="active",
        reading_plan_json={
            "spatial_rescans": [] if failure == "missing_entry" else [operation]
        },
        llm_snapshot_json={},
    )
    if failure == "missing_run":
        run = None

    class Store:
        async def load_run(self, run_key):
            return run

        async def load_frozen(self, run_key, requested_attempt_id):
            assert requested_attempt_id == attempt_id
            return None if failure == "missing_attempt" else frozen

    statuses = []

    async def status(_db, _store, _run_key, _operation_id, value):
        statuses.append(value)

    monkeypatch.setattr(rescan, "PostgresAttemptStore", lambda *_: Store())
    monkeypatch.setattr(rescan, "_status", status)
    task = SimpleNamespace(
        id=task_id,
        meta={
            "novel_id": str(frozen.novel_id),
            "run_key": frozen.run_id,
            "operation_id": operation_id,
        },
        result=None,
    )

    with pytest.raises(ConflictError):
        await rescan.handle_spatial_rescan(object(), task)

    assert task.meta["recovery_required"] is False
    assert task.result == {
        "recovery_required": False,
        "recoverable": False,
        "status": "needs_reconciliation",
    }
    expected_statuses = (
        ["needs_reconciliation"] if failure in {"missing_attempt", "unknown"} else []
    )
    assert statuses == expected_statuses


@pytest.mark.asyncio
async def test_cancelled_spatial_rescan_with_unknown_call_is_not_resumable(monkeypatch):
    import asyncio

    import modules.evolution.sampler as sampler
    import modules.evolution.spatial as spatial
    import modules.evolution.spatial_rescan as rescan

    operation_id = str(uuid4())
    task_id = str(uuid4())
    frozen = _frozen().model_copy(
        update={
            "payload": {
                **_frozen().payload,
                "spatial_rescan_operation_id": operation_id,
                "spatial_rescan_status": "pending",
                "source_binding": _source().model_dump(mode="json"),
                "spatial_rescan_origin": {
                    "run_key": "origin-run",
                    "attempt_id": "origin-attempt",
                },
            }
        }
    )
    origin = frozen.model_copy(
        update={"run_id": "origin-run", "attempt_id": "origin-attempt"}
    )
    operation = {
        "operation_id": operation_id,
        "task_id": task_id,
        "attempt_ids": [frozen.attempt_id],
    }
    run = SimpleNamespace(
        status="active",
        reading_plan_json={"spatial_rescans": [operation]},
        llm_snapshot_json={},
    )

    class Store:
        def __init__(self):
            self.current = frozen

        async def load_run(self, run_key):
            return run

        async def load_frozen(self, run_key, attempt_id):
            if run_key == "origin-run":
                return origin
            return self.current if attempt_id == frozen.attempt_id else None

    store = Store()
    statuses = []

    async def status(_db, _store, _run_key, _operation_id, value):
        statuses.append(value)

    async def no_prefix_check(*_args, **_kwargs):
        return None

    async def cancelled_call(*_args, **_kwargs):
        store.current = store.current.model_copy(
            update={
                "payload": {
                    **store.current.payload,
                    "scene_spatial_discovery": {"stage": "sampling"},
                }
            }
        )
        raise asyncio.CancelledError

    class Db:
        async def rollback(self):
            return None

        async def checkpoint_task_progress(self):
            return True

    monkeypatch.setattr(rescan, "PostgresAttemptStore", lambda *_: store)
    monkeypatch.setattr(rescan, "_status", status)
    monkeypatch.setattr(rescan, "require_current_prefix", no_prefix_check)
    monkeypatch.setattr(spatial, "finish_scene_spatial", cancelled_call)
    monkeypatch.setattr(sampler, "SceneMethodCaller", lambda *_args, **_kwargs: object())
    task = SimpleNamespace(
        id=task_id,
        meta={
            "novel_id": str(frozen.novel_id),
            "run_key": frozen.run_id,
            "operation_id": operation_id,
        },
        result=None,
    )

    with pytest.raises(asyncio.CancelledError):
        await rescan.handle_spatial_rescan(Db(), task)

    assert statuses == ["running", "needs_reconciliation"]
    assert task.meta["recovery_required"] is False
    assert task.result["recoverable"] is False


@pytest.mark.parametrize(
    "journal_key", ["scene_spatial_discovery", "scene_spatial_review"]
)
@pytest.mark.parametrize("failure", ["provider", "input_budget"])
async def test_optional_spatial_call_failures_do_not_block_scene(
    monkeypatch, journal_key, failure
):
    import modules.evolution.pipeline as pipeline
    from modules.evolution.commit import CommitConflictError

    frozen = _frozen()
    store = _FakeStore(frozen)
    calls = []

    async def context(*args, **kwargs):
        return MapSpatialClueContext()

    async def execute(db, store, attempt, source, **kwargs):
        key = kwargs["journal_key"]
        calls.append(key)
        if key == journal_key and failure == "input_budget":
            raise CommitConflictError("input_budget_exceeded", "完整输入超过冻结预算")
        if key == journal_key:
            await store.replace_frozen_payload(
                attempt.model_copy(
                    update={"payload": {**attempt.payload, key: {"stage": "failed"}}}
                )
            )
            raise TimeoutError("provider result unknown")
        result = _clue_output().model_dump(mode="json")
        updated = attempt.model_copy(
            update={
                "payload": {
                    **attempt.payload,
                    key: {"stage": "sampled", "result": result},
                }
            }
        )
        await store.replace_frozen_payload(updated)
        return updated

    monkeypatch.setattr(pipeline, "_run_scene_call", execute)
    with container_scope({WORLD_READ_SPATIAL_DISCOVERY_CONTEXT: context}):
        result = await finish_scene_spatial(_FakeDb(), store, frozen, _source(), object())
        replay = await finish_scene_spatial(_FakeDb(), store, result, _source(), object())
    assert calls.count(journal_key) == 1
    discovery = result.payload["spatial_discovery_result"]
    assert discovery["status"] == (
        "unknown"
        if failure == "provider"
        else "not_run"
        if journal_key == "scene_spatial_discovery"
        else "inspected"
    )
    assert discovery["gaps"]
    assert replay == result
    if failure == "provider":
        assert result.payload[journal_key]["stage"] == "failed"


async def test_spatial_method_change_never_sends_new_request():
    frozen = _frozen()
    store = _FakeStore(frozen)
    store.run.reading_plan_json["spatial_method_fingerprint"] = "0" * 64
    result = await finish_scene_spatial(_FakeDb(), store, frozen, _source(), object())
    assert result.payload["spatial_discovery_result"]["status"] == "stale"
    assert result.payload["spatial_discovery_result"]["gaps"] == [
        {"reason": "spatial_method_authorization_changed"}
    ]
    assert "scene_spatial_discovery" not in result.payload


async def test_spatial_source_conflict_still_blocks_obsolete_scene(monkeypatch):
    import modules.evolution.pipeline as pipeline
    from modules.evolution.commit import CommitConflictError

    frozen = _frozen()
    store = _FakeStore(frozen)

    async def context(*args, **kwargs):
        return MapSpatialClueContext()

    async def stale(*args, **kwargs):
        raise CommitConflictError("source_changed", "source changed")

    monkeypatch.setattr(pipeline, "_run_scene_call", stale)
    with container_scope({WORLD_READ_SPATIAL_DISCOVERY_CONTEXT: context}):
        with pytest.raises(CommitConflictError, match="source_changed"):
            await finish_scene_spatial(_FakeDb(), store, frozen, _source(), object())


async def test_auto_draft_nonterminal_progress_reenters_same_request():
    from contextlib import nullcontext

    from modules.evolution.workflow import _build_spatial_auto_draft_batch

    calls = []
    batch_id, scene_id = uuid4(), uuid4()

    async def build(db, novel_id, request):
        calls.append(request)
        return {
            "batch_id": batch_id,
            "fingerprint": "d" * 64,
            "status": "running" if len(calls) == 1 else "completed",
            "cursor": len(calls),
            "total_chunks": 2,
            "completed_chunks": len(calls),
        }

    class Db:
        def begin_nested(self):
            return nullcontext()

        async def flush(self):
            pass

    run = SimpleNamespace(
        run_key="reading",
        committed_scene_index=1,
        reading_plan_json={
            "steps": [{"scene_index": 1, "scene_id": str(scene_id)}],
        },
    )
    with container_scope({WORLD_BUILD_MAP_AUTO_DRAFTS: build}):
        first = await _build_spatial_auto_draft_batch(
            Db(), "novel", run, build_key="batch"
        )
        second = await _build_spatial_auto_draft_batch(
            Db(), "novel", run, build_key="batch"
        )
        third = await _build_spatial_auto_draft_batch(
            Db(), "novel", run, build_key="batch"
        )
    assert first["status"] == "running"
    assert second["status"] == "completed" and third == second
    assert calls[0] == calls[1] and len(calls) == 2
    assert len(run.reading_plan_json["spatial_auto_draft_builds"]) == 1


async def test_missing_auto_draft_port_is_visible_and_can_recover(monkeypatch):
    from contextlib import nullcontext

    import core.container as di
    from modules.evolution.workflow import _build_spatial_auto_draft_batch

    class Db:
        def begin_nested(self):
            return nullcontext()

        async def flush(self):
            pass

    run = SimpleNamespace(
        run_key="reading",
        committed_scene_index=0,
        reading_plan_json={"steps": [{"scene_index": 0, "scene_id": str(uuid4())}]},
    )
    # An empty override scope retains application services; remove exactly this
    # provider so the fixture exercises the actual missing-key lookup.
    with monkeypatch.context() as missing:
        missing.delitem(di._container, WORLD_BUILD_MAP_AUTO_DRAFTS.name, raising=False)
        result = await _build_spatial_auto_draft_batch(
            Db(), "novel", run, build_key="batch"
        )
    assert result["status"] == "failed" and result["failure_kind"] == "KeyError"
    assert run.reading_plan_json["spatial_auto_draft_builds"] == [result]

    async def restored(db, novel_id, request):
        return {
            "batch_id": uuid4(),
            "fingerprint": "d" * 64,
            "status": "completed",
            "cursor": 1,
            "total_chunks": 1,
            "completed_chunks": 1,
        }

    with container_scope({WORLD_BUILD_MAP_AUTO_DRAFTS: restored}):
        recovered = await _build_spatial_auto_draft_batch(
            Db(), "novel", run, build_key="batch"
        )
    assert recovered["status"] == "completed"
    assert run.reading_plan_json["spatial_auto_draft_builds"] == [recovered]


async def test_density_skipped_rescan_attempt_is_durably_completed(monkeypatch):
    import modules.evolution.spatial_rescan as rescan

    frozen = _frozen()
    frozen = frozen.model_copy(
        update={
            "payload": {
                **frozen.payload,
                "spatial_rescan_status": "pending",
                "spatial_discovery_result": {
                    "status": "inspected",
                    "gaps": [{"reason": "low_spatial_density"}],
                },
            }
        }
    )
    store = _FakeStore(frozen)
    writes = []

    async def project(*args, **kwargs):
        pass

    class Db(_FakeDb):
        async def execute(self, statement):
            writes.append(statement)

    monkeypatch.setattr(rescan, "require_active_project_exclusive", project)
    result = await rescan._stage_rescan_result(Db(), store, frozen)
    assert result.payload["spatial_rescan_status"] == "completed"
    assert len(writes) == 1


async def test_spatial_context_query_failure_rolls_back_savepoint_before_gap():
    from sqlalchemy.exc import SQLAlchemyError

    events = []

    class Savepoint:
        async def __aenter__(self):
            events.append("enter")

        async def __aexit__(self, exc_type, exc, tb):
            events.append("rollback" if exc_type else "release")
            return False

    class Db(_FakeDb):
        def begin_nested(self):
            return Savepoint()

        async def commit(self):
            assert events[-1] == "rollback"
            events.append("gap_committed")

    async def broken_context(*args, **kwargs):
        raise SQLAlchemyError("context query failed")

    frozen = _frozen()
    with container_scope({WORLD_READ_SPATIAL_DISCOVERY_CONTEXT: broken_context}):
        result = await finish_scene_spatial(
            Db(), _FakeStore(frozen), frozen, _source(), object()
        )
    assert events == ["enter", "rollback", "gap_committed"]
    assert result.payload["spatial_discovery_result"]["status"] == "stale"


@pytest.mark.parametrize(
    "field,surface", [("subject_surface", "不存在的城"), ("target_surface", "门 外")]
)
def test_spatial_endpoint_surface_must_be_literal_current_scene_text(field, surface):
    discovery = _clue_output()
    discovery.clues[0] = discovery.clues[0].model_copy(update={field: surface})
    batch, gaps = _make_clues(
        frozen=_frozen(),
        source=_source(),
        content_mode="working",
        context=MapSpatialClueContext(),
        discovery=discovery,
        review=_review(),
        preparation={"endpoint_ref_map": {}, "allowed_endpoints": {}},
    )
    assert batch.clues == []
    assert gaps == [{"reason": "endpoint_surface_not_in_scene", "clue_index": 0}]
