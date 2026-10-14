"""Real journals survive bounded, out-of-order independent identity reviews."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.evolution.commit import FrozenAttempt
from modules.evolution.discovery import _finish_identity_reviews, method_fingerprint
from modules.evolution.ledger_contracts import DiscoveryOutput
from modules.evolution.pipeline import (
    SamplePendingReconciliationError,
    SceneSourceBinding,
    compute_scene_manifest_hash,
    prepare_scene_input,
)
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore
from modules.evolution.tasks import _SceneMethodCaller
from modules.writing.facade import create_draft_only


async def identity_scope(db, nid, *, budget=8):
    store = PostgresAttemptStore(db, nid)
    await store.register_run("parallel", mode="bootstrap", budget_total=budget)
    text = "甲紧张地摸戒指。"
    draft = await create_draft_only(db, nid, 1, "第一章", text)
    source = SceneSourceBinding(
        draft_id=draft.id,
        chapter_index=1,
        content_hash=draft.content_hash,
        start_offset=0,
        end_offset=len(text),
    )
    manifest = compute_scene_manifest_hash("parallel", 0, text, source)
    parent = await prepare_scene_input(
        store, run_key="parallel", scene_index=0, source_manifest_hash=manifest
    )
    generated = DiscoveryOutput.model_validate(
        {
            "changes": [
                {
                    "action": "new",
                    "category": "conditional_behavior",
                    "label": "摸戒指",
                    "statement": "甲紧张时摸戒指。",
                    "confidence": 0.7,
                    "evidence": [
                        {
                            "observation_id": "current",
                            "purpose": "occurrence",
                            "occurrence_kind": "event",
                        }
                    ],
                }
            ],
            "coverage": "inspected",
            "coverage_note": "合成测试资料",
        }
    )
    batch = {
        "scene_text": text,
        "current_observation_ids": ["current"],
        "current_observations": [],
        "historical_context": [],
        "allow_new_themes": True,
    }
    prepared = {
        "batches": [batch],
        "theme_index_shards": [
            [],
            [{"theme": {"entry_id": "one"}}],
            [{"theme": {"entry_id": "two"}}],
        ],
        "observations": {},
        "method_fingerprint": method_fingerprint(),
    }
    frozen = FrozenAttempt(
        novel_id=nid,
        run_id="parallel",
        attempt_id="scope",
        owner_epoch=1,
        producer_version="fixture",
        source_manifest_hash=manifest,
        previous_receipt=parent.previous_scene_attempt_id,
        previous_committed_prefix=parent.previous_committed_prefix,
        payload={
            "stage": "compiled",
            "scene_index": 0,
            "source_binding": source.model_dump(mode="json"),
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": generated.model_dump(mode="json"),
            },
        },
    )
    await store.save_frozen(frozen)
    await db.commit()
    return store, frozen, source, prepared, batch, generated


class ControlledReviews:
    def __init__(self, *, parallelism=2, failure=None, reverse=False):
        self.session_gate = asyncio.Lock()
        self.discovery_parallelism = parallelism
        self.failure = failure
        self.reverse = reverse
        self.finished = {i: asyncio.Event() for i in (1, 2)}
        self.started = {i: asyncio.Event() for i in (1, 2)}
        self.release = asyncio.Event()
        self.calls = []
        self.active = self.peak = self.cancelled = 0

    async def __call__(self, method, *, inputs):
        assert method == "review_discovery"
        index = inputs["theme_identity_check"]["shard_index"]
        self.calls.append(index)
        self.active += 1
        self.peak = max(self.active, self.peak)
        self.started[index].set()
        try:
            if self.failure == index:
                raise SceneCallFailedError(None)
            await self.release.wait()
            if self.reverse and index == 1:
                await self.finished[2].wait()
            self.finished[index].set()
            return {
                "result": {"verdicts": []},
                "paid_call_receipt": {"fixture_shard": index},
            }
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


async def finish(db, scope, caller):
    store, frozen, source, prepared, batch, generated = scope
    return await _finish_identity_reviews(
        db, store, frozen, source, caller, prepared, 0, batch, generated
    )


async def test_parallel_preserves_both_results_and_replays_without_io(
    db_session, evolution_project_id
):
    scope = await identity_scope(db_session, evolution_project_id)
    caller = ControlledReviews(reverse=True)
    job = asyncio.create_task(finish(db_session, scope, caller))
    await asyncio.wait_for(caller.started[2].wait(), 2)
    assert caller.peak == 2
    # A different host field written while both providers wait must survive.
    async with caller.session_gate:
        store, frozen = scope[:2]
        current = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        await store.replace_frozen_payload(
            current.model_copy(
                update={"payload": {**current.payload, "host_checkpoint": "retained"}}
            )
        )
        await db_session.commit()
    caller.release.set()
    frozen = await job
    assert frozen.payload["host_checkpoint"] == "retained"
    for index in (1, 2):
        journal = frozen.payload[f"scene_discovery_identity_0_{index}"]
        assert journal["stage"] == "sampled"
        assert journal["paid_call_receipt"] == {"fixture_shard": index}
    assert (await scope[0].load_run("parallel")).budget_remaining == 6
    prior = frozen.payload
    replay = await finish(db_session, (scope[0], frozen, *scope[2:]), caller)
    assert replay.payload == prior and caller.calls == [1, 2]


async def test_failure_waits_for_started_peer_then_unknown_blocks_replay(
    db_session, evolution_project_id
):
    scope = await identity_scope(db_session, evolution_project_id)
    caller = ControlledReviews(failure=1)
    job = asyncio.create_task(finish(db_session, scope, caller))
    await asyncio.wait_for(caller.started[2].wait(), 2)
    assert not job.done()
    caller.release.set()
    with pytest.raises(SceneCallFailedError):
        await job
    frozen = await scope[0].load_frozen("parallel", "scope")
    assert frozen.payload["scene_discovery_identity_0_1"]["stage"] == "failed"
    assert frozen.payload["scene_discovery_identity_0_2"]["stage"] == "sampled"
    with pytest.raises(SamplePendingReconciliationError):
        await finish(db_session, (scope[0], frozen, *scope[2:]), caller)
    assert caller.calls == [1, 2] and caller.cancelled == 0


async def test_shutdown_drains_results_without_cancelling_providers(
    db_session, evolution_project_id
):
    scope = await identity_scope(db_session, evolution_project_id)
    caller = ControlledReviews()
    job = asyncio.create_task(finish(db_session, scope, caller))
    await asyncio.wait_for(caller.started[2].wait(), 2)
    job.cancel()
    await asyncio.sleep(0)
    assert not job.done()
    caller.release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    frozen = await scope[0].load_frozen("parallel", "scope")
    assert all(
        frozen.payload[f"scene_discovery_identity_0_{i}"]["stage"] == "sampled"
        for i in (1, 2)
    )
    assert caller.cancelled == 0


@pytest.mark.parametrize("budget, expected_calls", [(0, []), (1, [1])])
async def test_budget_failure_never_cancels_or_reissues_authorized_peer(
    db_session, evolution_project_id, budget, expected_calls
):
    scope = await identity_scope(db_session, evolution_project_id, budget=budget)
    caller = ControlledReviews()
    caller.release.set()
    with pytest.raises(BudgetExhaustedError):
        await finish(db_session, scope, caller)
    frozen = await scope[0].load_frozen("parallel", "scope")
    assert caller.calls == expected_calls and caller.cancelled == 0
    assert "scene_discovery_identity_0_2" not in frozen.payload
    if expected_calls:
        assert frozen.payload["scene_discovery_identity_0_1"]["stage"] == "sampled"


async def test_serial_mode_retains_single_provider_path(db_session, evolution_project_id):
    scope = await identity_scope(db_session, evolution_project_id)
    caller = ControlledReviews(parallelism=1)
    caller.release.set()
    await finish(db_session, scope, caller)
    assert caller.calls == [1, 2] and caller.peak == 1


@pytest.mark.parametrize(
    "snapshot, expected",
    [
        (None, 1),
        ({"profile": {"provider_id": "deepseek"}}, 1),
        ({"profile": {"provider_id": "codex"}}, 2),
    ],
)
def test_only_native_codex_enables_bounded_identity_parallelism(snapshot, expected):
    assert _SceneMethodCaller(None, None, snapshot).discovery_parallelism == expected


async def test_connection_setup_serialized_and_contexts_closed(
    db_session, evolution_project_id
):
    provider = "parallel-setup-" + evolution_project_id
    active = peak = closed = 0
    ready = asyncio.Event()
    release = asyncio.Event()
    opened = 0

    class Sampler:
        async def review_discovery(self, **inputs):
            await release.wait()
            return inputs

    @asynccontextmanager
    async def factory(db, novel_id):
        nonlocal active, peak, closed, opened
        active += 1
        peak = max(peak, active)
        await db.execute(select(1))
        await asyncio.sleep(0)
        active -= 1
        opened += 1
        if opened == 2:
            ready.set()
        try:
            yield Sampler()
        finally:
            closed += 1

    register_scene_sampler(provider, factory)
    caller = _SceneMethodCaller(
        db_session,
        SimpleNamespace(sampler_provider=provider, novel_id=evolution_project_id),
        None,
    )
    group = asyncio.gather(
        caller("review_discovery", ordinal=1), caller("review_discovery", ordinal=2)
    )
    await asyncio.wait_for(ready.wait(), 2)
    release.set()
    assert await group == [{"ordinal": 1}, {"ordinal": 2}]
    assert peak == 1 and closed == 2


@pytest.mark.parametrize("cap", [3, 4, 6, 8])
def test_native_caller_uses_configured_cap_without_parallelizing_api(monkeypatch, cap):
    from core.config import get_settings

    monkeypatch.setenv("CODEX_TEXT_MAX_CONCURRENT_REQUESTS", str(cap))
    get_settings.cache_clear()
    try:
        assert (
            _SceneMethodCaller(
                None, None, {"profile": {"provider_id": "codex"}}
            ).discovery_parallelism
            == cap
        )
        assert (
            _SceneMethodCaller(
                None, None, {"profile": {"provider_id": "deepseek"}}
            ).discovery_parallelism
            == 1
        )
    finally:
        get_settings.cache_clear()
