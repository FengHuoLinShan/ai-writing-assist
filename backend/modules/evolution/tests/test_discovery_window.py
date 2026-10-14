"""A free native slot advances independent work, never a future identity scope."""

import asyncio
from copy import deepcopy

import pytest

from modules.evolution.discovery import _identity_shards, finish_scene_discovery
from modules.evolution.ledger_contracts import DiscoveryOutput
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.store import BudgetExhaustedError
from modules.evolution.tests.test_discovery_batch_parallel import batch_scope, primary


async def four_scope(db, nid, budget=16, count=4):
    scope = await batch_scope(db, nid, budget=budget)
    store, frozen, source, prepared, _, generated = scope
    batches = [
        {**deepcopy(prepared["batches"][0]), "partition_id": f"batch-{i}"}
        for i in range(count)
    ]
    prepared["batches"] = batches
    frozen.payload["discovery_preparation"] = prepared
    await store.replace_frozen_payload(frozen)
    await db.commit()
    return store, frozen, source, prepared, list(enumerate(batches)), generated


class Four:
    def __init__(self, generated, *, parallelism=2, failure=None, empty=False, count=4):
        self.generated = generated
        self.discovery_parallelism = parallelism
        self.session_gate = asyncio.Lock()
        self.failure = failure
        self.empty = empty
        self.active = self.peak = self.cancelled = 0
        self.started = [asyncio.Event() for _ in range(count)]
        self.release = [asyncio.Event() for _ in range(count)]
        self.calls = []

    async def __call__(self, method, *, inputs):
        index = int(inputs["partition_id"].rsplit("-", 1)[1])
        self.calls.append((method, index))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if method == "discover_details":
                self.started[index].set()
                await self.release[index].wait()
                if self.failure == index:
                    raise SceneCallFailedError(None)
                result = (
                    DiscoveryOutput(
                        changes=[], coverage="inspected", coverage_note="合成资料"
                    ).model_dump(mode="json")
                    if self.empty
                    else self.generated.model_dump(mode="json")
                )
            else:
                assert method == "review_discovery"
                result = {"verdicts": []}
            return {
                "result": result,
                "paid_call_receipt": {"synthetic_batch": index, "method": method},
            }
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


async def test_free_slot_advances_third_before_slow_second_finishes(
    db_session, evolution_project_id
):
    scope = await four_scope(db_session, evolution_project_id)
    caller = Four(scope[-1])
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[1].wait(), 2)
    assert not caller.started[2].is_set() and caller.peak == 2
    caller.release[0].set()
    await asyncio.wait_for(caller.started[2].wait(), 2)
    assert not caller.release[1].is_set() and caller.peak == 2
    for event in caller.release:
        event.set()
    result = await job
    assert all(
        result.payload[f"scene_discovery_review_{i}"]["stage"] == "sampled"
        for i in range(4)
    )
    assert (await scope[0].load_run("parallel")).budget_remaining == 8
    # Prefetched later generation cannot enter earlier identity inputs.
    shards = _identity_shards(result, scope[3], 1)
    proposals = [
        entry["same_scene_proposal"]["batch"]
        for shard in shards
        for entry in shard
        if "same_scene_proposal" in entry
    ]
    assert proposals == [0]
    before = list(caller.calls)
    replay = await primary(db_session, (scope[0], result, *scope[2:]), caller)
    assert replay.payload == result.payload and caller.calls == before


async def test_failure_drains_active_peer_and_blocks_waiting_chains(
    db_session, evolution_project_id
):
    scope = await four_scope(db_session, evolution_project_id)
    caller = Four(scope[-1], failure=0)
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[1].wait(), 2)
    caller.release[0].set()
    await asyncio.sleep(0.02)
    assert not job.done() and not caller.started[2].is_set()
    caller.release[1].set()
    with pytest.raises(SceneCallFailedError):
        await job
    saved = await scope[0].load_frozen("parallel", "scope")
    assert (
        saved.payload["scene_discovery_0"]["stage"] == "failed"
        and saved.payload["scene_discovery_1"]["stage"] == "sampled"
    )
    assert (
        caller.calls == [("discover_details", 0), ("discover_details", 1)]
        and caller.cancelled == 0
    )
    assert "scene_discovery_2" not in saved.payload


async def test_shutdown_blocks_waiters_and_drains_active_results(
    db_session, evolution_project_id
):
    scope = await four_scope(db_session, evolution_project_id)
    caller = Four(scope[-1])
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[1].wait(), 2)
    job.cancel()
    await asyncio.sleep(0)
    caller.release[0].set()
    caller.release[1].set()
    with pytest.raises(asyncio.CancelledError):
        await job
    saved = await scope[0].load_frozen("parallel", "scope")
    assert all(
        saved.payload[f"scene_discovery_{i}"]["stage"] == "sampled" for i in (0, 1)
    )
    assert (
        caller.calls == [("discover_details", 0), ("discover_details", 1)]
        and caller.cancelled == 0
    )


async def test_one_budget_never_admits_waiting_work(db_session, evolution_project_id):
    scope = await four_scope(db_session, evolution_project_id, budget=1)
    caller = Four(scope[-1], empty=True)
    for event in caller.release:
        event.set()
    with pytest.raises(BudgetExhaustedError):
        await primary(db_session, scope, caller)
    assert (
        caller.calls == [("discover_details", 0)]
        and (await scope[0].load_run("parallel")).budget_remaining == 0
    )


@pytest.mark.parametrize("parallelism", [1, 2, 3, 4, 6, 8])
async def test_full_discovery_uses_window_without_changing_serial_provider(
    db_session, evolution_project_id, parallelism
):
    count = max(4, parallelism * 2)
    scope = await four_scope(db_session, evolution_project_id, count=count)
    caller = Four(scope[-1], parallelism=parallelism, empty=True, count=count)
    if parallelism == 1:
        for event in caller.release:
            event.set()
    job = asyncio.create_task(
        finish_scene_discovery(db_session, scope[0], scope[1], scope[2], caller)
    )
    if parallelism > 1:
        await asyncio.wait_for(caller.started[parallelism - 1].wait(), 2)
        caller.release[0].set()
        await asyncio.wait_for(caller.started[parallelism].wait(), 2)
        for event in caller.release:
            event.set()
    result = await job
    assert (
        result.payload["discovery_result"]["changes"] == [] and caller.peak == parallelism
    )


async def test_sparse_no_action_positions_do_not_strand_native_slots(
    db_session, evolution_project_id
):
    scope = await four_scope(db_session, evolution_project_id, count=6)
    for index in (1, 2, 3):
        scope[3]["batches"][index].update(allow_new_themes=False, historical_context=[])
    await scope[0].replace_frozen_payload(scope[1])
    await db_session.commit()
    caller = Four(scope[-1], empty=True, count=6)
    job = asyncio.create_task(
        finish_scene_discovery(db_session, scope[0], scope[1], scope[2], caller)
    )
    await asyncio.wait_for(caller.started[4].wait(), 2)
    assert caller.started[0].is_set() and caller.peak == 2
    assert not any(caller.started[i].is_set() for i in (1, 2, 3))
    caller.release[4].set()
    await asyncio.wait_for(caller.started[5].wait(), 2)
    assert not caller.release[0].is_set()
    for event in caller.release:
        event.set()
    result = await job
    assert result.payload["discovery_result"]["coverage"]["no_action_batches"] == [
        1,
        2,
        3,
    ]
    assert caller.calls == [
        ("discover_details", 0),
        ("discover_details", 4),
        ("discover_details", 5),
    ]
    assert (await scope[0].load_run("parallel")).budget_remaining == 13
    for i in (1, 2, 3):
        assert result.payload[f"discovery_no_action_{i}"]["model_called"] is False
        assert f"scene_discovery_{i}" not in result.payload
    before = list(caller.calls)
    replay = await finish_scene_discovery(db_session, scope[0], result, scope[2], caller)
    assert replay.payload == result.payload and caller.calls == before


@pytest.mark.parametrize("parallelism", [3, 6])
@pytest.mark.parametrize("abort", ["unknown", "shutdown"])
async def test_higher_parallelism_drains_peers_without_admitting_waiters(
    db_session, evolution_project_id, parallelism, abort
):
    count = parallelism * 2
    scope = await four_scope(db_session, evolution_project_id, budget=32, count=count)
    caller = Four(
        scope[-1],
        parallelism=parallelism,
        failure=0 if abort == "unknown" else None,
        empty=True,
        count=count,
    )
    job = asyncio.create_task(primary(db_session, scope, caller))
    await asyncio.wait_for(caller.started[parallelism - 1].wait(), 2)
    if abort == "shutdown":
        job.cancel()
    caller.release[0].set()
    await asyncio.sleep(0.02)
    assert not job.done() and not caller.started[parallelism].is_set()
    for event in caller.release[1:parallelism]:
        event.set()
    with pytest.raises(
        SceneCallFailedError if abort == "unknown" else asyncio.CancelledError
    ):
        await job
    saved = await scope[0].load_frozen("parallel", "scope")
    assert caller.cancelled == 0 and caller.peak == parallelism
    assert len(caller.calls) == parallelism
    assert all(
        saved.payload[f"scene_discovery_{i}"]["stage"] == "sampled"
        for i in range(1, parallelism)
    )
    assert f"scene_discovery_{parallelism}" not in saved.payload
