"""Independent frozen batches overlap without changing evidence or replay gates."""

import asyncio
from copy import deepcopy

import pytest

from core.errors import ConflictError
from infrastructure.llm.collaboration import content_hash
from modules.evolution.discovery import (
    _discovery_envelope,
    _finish_primary_batches,
    _identity_shards,
    _require_discovery_journals,
    _review_inputs,
    finish_scene_discovery,
)
from modules.evolution.ledger_contracts import DiscoveryOutput
from modules.evolution.pipeline import SamplePendingReconciliationError
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.store import BudgetExhaustedError
from modules.evolution.tests.test_identity_parallel import identity_scope


async def batch_scope(db, nid, *, budget=8):
    store, frozen, source, prepared, batch, generated = await identity_scope(
        db, nid, budget=budget
    )
    batches = [{**deepcopy(batch), "partition_id": f"batch-{i}"} for i in range(2)]
    prepared.update(
        batches=batches, unsupported_batches=[], coverage={}, themes={}, theme_index=[]
    )
    frozen.payload.pop("scene_discovery_0")
    frozen.payload.update(discovery_version=1, discovery_preparation=prepared)
    await store.replace_frozen_payload(frozen)
    await db.commit()
    return store, frozen, source, prepared, list(enumerate(batches)), generated


class Batches:
    def __init__(self, generated, *, parallelism=2, fail=False, empty=False):
        self.generated = generated
        self.discovery_parallelism = parallelism
        self.session_gate = asyncio.Lock()
        self.fail = fail
        self.empty = empty
        self.release = asyncio.Event()
        self.started = [asyncio.Event(), asyncio.Event()]
        self.first_review = asyncio.Event()
        self.calls = []
        self.active = self.peak = self.cancelled = 0

    async def __call__(self, method, *, inputs):
        index = int(inputs["partition_id"].rsplit("-", 1)[1])
        self.calls.append((method, index))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if method == "discover_details":
                self.started[index].set()
                if self.fail and index == 0:
                    raise SceneCallFailedError(
                        self.fail if isinstance(self.fail, dict) else None
                    )
                await self.release.wait()
                result = (
                    DiscoveryOutput(
                        changes=[], coverage="inspected", coverage_note="合成资料"
                    ).model_dump(mode="json")
                    if self.empty
                    else self.generated.model_dump(mode="json")
                )
            else:
                assert method == "review_discovery"
                self.first_review.set()
                result = {"verdicts": []}
            return {
                "result": result,
                "paid_call_receipt": {"fixture_batch": index, "method": method},
            }
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


async def primary(db, scope, caller):
    store, frozen, source, prepared, plans = scope[:5]
    _require_discovery_journals(frozen, prepared)
    return await _finish_primary_batches(
        db, store, frozen, source, caller, prepared, plans
    )


async def test_primary_batches_overlap_preserve_requests_and_replay(
    db_session, evolution_project_id
):
    scope = await batch_scope(db_session, evolution_project_id)
    caller = Batches(scope[-1])
    expected = deepcopy(scope[3]["batches"])
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[1].wait(), 2)
    assert caller.peak == 2 and not caller.first_review.is_set()
    caller.release.set()
    result = await job
    for i, batch in enumerate(expected):
        generation = result.payload[f"scene_discovery_{i}"]
        review = result.payload[f"scene_discovery_review_{i}"]
        assert generation["input_hash"] == content_hash(
            _discovery_envelope(result, scope[3], batch)
        )
        assert review["input_hash"] == content_hash(
            _discovery_envelope(result, scope[3], _review_inputs(batch, scope[-1]))
        )
        assert generation["stage"] == review["stage"] == "sampled"
        assert generation["paid_call_receipt"]["fixture_batch"] == i
    assert (await scope[0].load_run("parallel")).budget_remaining == 4
    calls = list(caller.calls)
    replayed = await primary(db_session, (scope[0], result, *scope[2:]), caller)
    assert replayed.payload == result.payload and caller.calls == calls
    # A future proposal cannot leak into the earlier batch's identity request.
    before = _identity_shards(result, scope[3], 0)
    later_removed = result.model_copy(deep=True)
    later_removed.payload.pop("scene_discovery_1")
    assert _identity_shards(later_removed, scope[3], 0) == before
    assert _identity_shards(result, scope[3], 1) != before


async def test_unknown_failure_drains_peer_without_starting_its_review(
    db_session, evolution_project_id
):
    scope = await batch_scope(db_session, evolution_project_id)
    caller = Batches(scope[-1], fail=True)
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[1].wait(), 2)
    assert not job.done()
    caller.release.set()
    with pytest.raises(SceneCallFailedError):
        await job
    current = await scope[0].load_frozen("parallel", "scope")
    assert current.payload["scene_discovery_0"]["stage"] == "failed"
    assert current.payload["scene_discovery_1"]["stage"] == "sampled"
    assert caller.calls == [("discover_details", 0), ("discover_details", 1)]
    with pytest.raises(SamplePendingReconciliationError):
        await primary(db_session, (scope[0], current, *scope[2:]), caller)
    assert caller.cancelled == 0


async def test_shutdown_drains_batch_calls_then_propagates(
    db_session, evolution_project_id
):
    scope = await batch_scope(db_session, evolution_project_id)
    caller = Batches(scope[-1])
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[1].wait(), 2)
    job.cancel()
    await asyncio.sleep(0)
    assert not job.done()
    caller.release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    current = await scope[0].load_frozen("parallel", "scope")
    assert all(
        current.payload[f"scene_discovery_{i}"]["stage"] == "sampled" for i in range(2)
    )
    assert caller.calls == [("discover_details", 0), ("discover_details", 1)]
    assert caller.cancelled == 0


@pytest.mark.parametrize("budget", [0, 1])
async def test_primary_budget_atomic_before_io(db_session, evolution_project_id, budget):
    scope = await batch_scope(db_session, evolution_project_id, budget=budget)
    caller = Batches(scope[-1], empty=True)
    caller.release.set()
    with pytest.raises(BudgetExhaustedError):
        await primary(db_session, scope, caller)
    assert len(caller.calls) == budget
    assert (await scope[0].load_run("parallel")).budget_remaining == 0


@pytest.mark.parametrize("journal", ["scene_discovery_1", "scene_discovery_identity_1_1"])
async def test_preexisting_unknown_blocks_all_new_batches(
    db_session, evolution_project_id, journal
):
    scope = await batch_scope(db_session, evolution_project_id)
    scope[1].payload[journal] = {"stage": "sampling", "input_hash": "original"}
    caller = Batches(scope[-1])
    with pytest.raises(SamplePendingReconciliationError):
        await primary(db_session, scope, caller)
    assert caller.calls == []


async def test_existing_changed_generation_blocks_new_peer(
    db_session, evolution_project_id
):
    scope = await batch_scope(db_session, evolution_project_id)
    scope[1].payload["scene_discovery_1"] = {
        "stage": "sampled",
        "input_hash": "drift",
        "result": scope[-1].model_dump(mode="json"),
    }
    caller = Batches(scope[-1])
    with pytest.raises(ConflictError):
        await primary(db_session, scope, caller)
    assert caller.calls == []


@pytest.mark.parametrize("parallelism", [1, 2])
async def test_full_empty_discovery_keeps_compiler_and_serial_provider_path(
    db_session, evolution_project_id, parallelism
):
    scope = await batch_scope(db_session, evolution_project_id)
    caller = Batches(scope[-1], parallelism=parallelism, empty=True)
    caller.release.set()
    result = await finish_scene_discovery(
        db_session, scope[0], scope[1], scope[2], caller
    )
    assert result.payload["discovery_result"]["changes"] == []
    assert len(caller.calls) == 2 and caller.peak <= parallelism
    assert (await scope[0].load_run("parallel")).budget_remaining == 6


async def test_known_output_failure_keeps_peer_review_and_reuses_failure(
    db_session, evolution_project_id
):
    scope = await batch_scope(db_session, evolution_project_id)
    receipt = {
        "outcome": "failed_final",
        "usage": {"usage_complete": True, "unknown_attempts": 0},
        "attempts_detail": [{"status": "failed", "error_kind": "invalid_json"}],
    }
    caller = Batches(scope[-1], fail=receipt)
    caller.release.set()
    current = await primary(db_session, scope, caller)
    assert current.payload["scene_discovery_0"]["stage"] == "failed"
    assert current.payload["scene_discovery_review_1"]["stage"] == "sampled"
    calls = list(caller.calls)
    replay = await primary(db_session, (scope[0], current, *scope[2:]), caller)
    assert replay.payload == current.payload and caller.calls == calls


async def test_stale_identity_scope_blocks_new_primary_peer(
    db_session, evolution_project_id
):
    scope = await batch_scope(db_session, evolution_project_id)
    batch = scope[3]["batches"][1]
    scope[1].payload["scene_discovery_1"] = {
        "stage": "sampled",
        "input_hash": content_hash(_discovery_envelope(scope[1], scope[3], batch)),
        "result": scope[-1].model_dump(mode="json"),
    }
    scope[1].payload["scene_discovery_identity_1_1"] = {
        "stage": "sampled",
        "input_hash": "drift",
        "result": {"verdicts": []},
    }
    caller = Batches(scope[-1])
    with pytest.raises(ConflictError, match="主题身份审查"):
        await primary(db_session, scope, caller)
    assert caller.calls == []
