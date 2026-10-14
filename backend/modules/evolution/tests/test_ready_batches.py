"""Ready chains use idle slots and wait only for strict prior proposals."""

import asyncio
from copy import deepcopy

import pytest

from modules.evolution.discovery import _finish_ready_batches
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.tests.test_discovery_batch_parallel import batch_scope


async def test_ready_batches_use_free_slot_before_slow_generation(
    db_session, evolution_project_id
):
    store, frozen, source, prepared, plans, generated = await batch_scope(
        db_session, evolution_project_id, budget=100
    )
    plans = [
        (i, {**deepcopy(plans[0][1]), "partition_id": f"batch-{i}"}) for i in range(5)
    ]
    prepared["batches"] = [batch for _, batch in plans]
    frozen.payload["discovery_preparation"] = prepared
    await store.replace_frozen_payload(frozen)
    await db_session.commit()
    release, next_started, review_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    calls, active, peak = [], 0, 0

    class Caller:
        session_gate = asyncio.Lock()
        discovery_parallelism = 2

        async def __call__(self, method, *, inputs):
            nonlocal active, peak
            index = int(inputs["partition_id"].split("-")[1])
            active += 1
            peak = max(peak, active)
            try:
                calls.append((method, index))
                if method == "discover_details":
                    if index == 0:
                        await release.wait()
                    if index == 2:
                        next_started.set()
                    result = generated.model_dump(mode="json")
                else:
                    if index == 1:
                        review_started.set()
                    if "theme_identity_check" in inputs:
                        assert release.is_set()
                        for item in inputs["theme_index"]:
                            if "same_scene_proposal" in item:
                                assert item["same_scene_proposal"]["batch"] < index
                    result = {"verdicts": []}
                return {"result": result, "paid_call_receipt": {"synthetic": True}}
            finally:
                active -= 1

    caller = Caller()
    task = asyncio.create_task(
        _finish_ready_batches(db_session, store, frozen, source, caller, prepared, plans)
    )
    try:
        await asyncio.wait_for(next_started.wait(), 3)
        await asyncio.wait_for(review_started.wait(), 3)
        assert not release.is_set() and peak == 2
        assert ("review_discovery", 1) in calls
        assert all(index < 4 for method, index in calls if method == "discover_details")
    finally:
        release.set()
        result = await asyncio.wait_for(task, 5)
    assert all(
        result.payload[f"scene_discovery_review_{i}"]["stage"] == "sampled"
        for i in range(5)
    )
    before = list(calls)
    await _finish_ready_batches(
        db_session, store, result, source, caller, prepared, plans
    )
    assert calls == before


@pytest.mark.parametrize("cancel", [False, True])
async def test_ready_unknown_or_cancel_stops_admission_and_drains_sent(
    db_session, evolution_project_id, cancel
):
    store, frozen, source, prepared, plans, generated = await batch_scope(
        db_session, evolution_project_id, budget=100
    )
    plans = [
        (i, {**deepcopy(plans[0][1]), "partition_id": f"batch-{i}"}) for i in range(6)
    ]
    release, both = asyncio.Event(), asyncio.Event()
    calls = []

    class Caller:
        session_gate = asyncio.Lock()
        discovery_parallelism = 2

        async def __call__(self, method, *, inputs):
            index = int(inputs["partition_id"].split("-")[1])
            calls.append(index)
            if len(calls) == 2:
                both.set()
            await release.wait()
            if not cancel and index == 0:
                raise SceneCallFailedError(None)
            return {
                "result": generated.model_dump(mode="json"),
                "paid_call_receipt": {"synthetic": True},
            }

    task = asyncio.create_task(
        _finish_ready_batches(
            db_session, store, frozen, source, Caller(), prepared, plans
        )
    )
    await asyncio.wait_for(both.wait(), 3)
    if cancel:
        task.cancel()
        await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError if cancel else SceneCallFailedError):
        await asyncio.wait_for(task, 5)
    assert calls == [0, 1]
    final = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    assert final.payload["scene_discovery_1"]["stage"] == "sampled"
    assert not any(final.payload.get(f"scene_discovery_{i}") for i in range(2, 6))


async def test_frozen_context_drift_is_rejected_before_any_call(
    db_session, evolution_project_id
):
    from core.errors import ConflictError
    from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
    from modules.evolution.discovery import finish_scene_discovery, method_fingerprint
    from modules.evolution.tests.test_discovery_batch_parallel import Batches

    store, frozen, source, prepared, plans, generated = await batch_scope(
        db_session, evolution_project_id
    )
    prepared["method_fingerprint"] = method_fingerprint(2)
    prepared["context_snapshot"] = luna_snapshot()
    frozen.payload.update(discovery_version=2, discovery_preparation=prepared)
    await store.replace_frozen_payload(frozen)
    run = await store.load_run(frozen.run_id)
    run.llm_snapshot_json = {**luna_snapshot(), "context_drift": True}
    await db_session.commit()
    caller = Batches(generated)
    with pytest.raises(ConflictError, match="冻结上下文策略"):
        await finish_scene_discovery(db_session, store, frozen, source, caller)
    assert caller.calls == []
