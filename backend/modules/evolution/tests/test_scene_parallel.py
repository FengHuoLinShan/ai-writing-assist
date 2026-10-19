"""Independent Scene branches overlap I/O while sharing serialized journals."""

import asyncio
import logging
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from infrastructure.llm.errors import LLMAdmissionStoppedError
from infrastructure.llm.limits import require_request_admission, stop_request_admission
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
from modules.evolution import consumer_reuse, enrichment, input_budget, pipeline, world
from modules.evolution.commit import FrozenAttempt
from modules.evolution.state_review import SceneCallFailedError


class Session:
    def __init__(self, gate):
        self.gate = gate
        self.transaction = False
        self.active = self.peak = 0
        self.rolled_back = asyncio.Event()

    async def operation(self):
        assert self.gate.locked(), "shared Session operation escaped its gate"
        self.active += 1
        self.peak = max(self.peak, self.active)
        assert self.active == 1
        self.transaction = True
        try:
            await asyncio.sleep(0)
        finally:
            self.active -= 1

    async def commit(self):
        await self.operation()
        self.transaction = False

    async def rollback(self):
        await self.operation()
        self.transaction = False
        self.rolled_back.set()


class Store:
    novel_id = "synthetic-project"

    def __init__(self, db, frozen, budget):
        self.db, self.frozen = db, frozen
        self.run = SimpleNamespace(
            budget_remaining=budget,
            reading_plan_json={
                "budget_mode": "confirmed_scope" if budget is None else "bounded"
            },
            llm_snapshot_json=luna_snapshot(),
        )

    async def require_project_owner(self, key):
        await self.db.operation()

    async def load_run(self, key, *, for_update=False):
        await self.db.operation()
        return self.run

    async def load_frozen(self, key, attempt):
        await self.db.operation()
        return self.frozen.model_copy(deep=True)

    async def replace_frozen_payload(self, frozen):
        await self.db.operation()
        self.frozen = frozen.model_copy(deep=True)

    async def reserve_budget(self, key, units):
        await self.db.operation()
        if self.run.budget_remaining is not None:
            self.run.budget_remaining -= units


class Caller:
    def __init__(self, *, parallelism=2, failure=None):
        self.session_gate = asyncio.Lock()
        self.discovery_parallelism = parallelism
        self.failure = failure
        self.started = {
            name: asyncio.Event() for name in ("enrich_scene", "execute_world_request")
        }
        self.release = asyncio.Event()
        self.failed = asyncio.Event()
        self.calls = []
        self.active = self.peak = self.cancelled = 0
        self.db = None

    async def __call__(self, method, **inputs):
        require_request_admission()
        assert not self.session_gate.locked() and not self.db.transaction
        self.calls.append((method, deepcopy(inputs)))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if method in self.started:
                self.started[method].set()
                if self.failure == method:
                    await self.started["enrich_scene"].wait()
                    await self.started["execute_world_request"].wait()
                    stop_request_admission()
                    self.failed.set()
                    raise SceneCallFailedError(None)
                await self.release.wait()
            return {
                "result": {"synthetic": method},
                "paid_call_receipt": {"method": method},
            }
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


def scope(monkeypatch, *, budget=None, parallelism=2, failure=None):
    caller = Caller(parallelism=parallelism, failure=failure)
    db = Session(caller.session_gate)
    caller.db = db
    frozen = FrozenAttempt(
        novel_id=Store.novel_id,
        run_id="synthetic-run",
        attempt_id="attempt",
        owner_epoch=1,
        producer_version="synthetic",
        source_manifest_hash="a" * 64,
        payload={
            "stage": "compiled",
            "scene_index": 0,
            "scene_text": "合成正文。",
            "scene_card": {
                "status": "draft",
                "source": "evolution",
                "structure_meta": {
                    "auto_ingested": True,
                    "semantic_origin": "boundary_only",
                },
            },
            "input_manifest": {},
            "compiled_observations": [],
            "enrichment_version": 1,
            "world_version": 3,
            "optional_stage_version": 1,
        },
    )
    assert enrichment.needs_enrichment(frozen.payload["scene_card"])
    store = Store(db, frozen, budget)
    source = SimpleNamespace(ranges=lambda: [])

    async def verify(db, frozen):
        await db.operation()

    async def parent(*args, **kwargs):
        await db.operation()
        return SimpleNamespace(
            dependency_status="committed",
            previous_scene_attempt_id=None,
            previous_committed_prefix=None,
        )

    async def no_reuse(*args, **kwargs):
        return None

    async def context(*args):
        await db.operation()
        return {"_identity_queries": [], "identity_candidates": [], "_entity_ref_map": {}}

    async def history(*args):
        await db.operation()
        return {}

    async def state_review(db, store, current, source, reviewer):
        assert caller.active == 0
        assert current.payload.get("enrichment_result") and current.payload.get(
            "world_result"
        )
        current.payload["state_review_joined"] = True
        return current

    class Output(BaseModel):
        synthetic: str = "world"

    request = LLMCallRequest(messages=[LLMMessage(role="user", content="合成请求")])
    monkeypatch.setattr(pipeline, "_source_verifier", lambda source: verify)
    monkeypatch.setattr(pipeline, "prepare_scene_input", parent)
    monkeypatch.setattr(consumer_reuse, "find_reusable", no_reuse)
    monkeypatch.setattr(
        consumer_reuse, "read_set", lambda *a, **k: {"synthetic": "proof"}
    )
    monkeypatch.setattr(input_budget, "fits", lambda *a, **k: True)
    monkeypatch.setattr(
        enrichment.imports,
        "prepare_scene_enrichment",
        lambda *a: {"scene_source": "合成正文。"},
    )
    monkeypatch.setattr(
        enrichment.imports,
        "materialize_scene_enrichment",
        lambda *a: {"synthetic": "candidate"},
    )
    monkeypatch.setattr(
        enrichment, "materialize_group_audit", lambda **k: {"status": "passed"}
    )
    monkeypatch.setattr(world.imports, "prepare_scene_world_context", context)
    monkeypatch.setattr(
        world.imports, "build_scene_world_request", lambda *a: (request, Output)
    )
    monkeypatch.setattr(
        world.imports,
        "materialize_scene_world",
        lambda *a: {
            "entities": [{"entity_type": "character", "name": "合成人物"}],
            "delta_events": [],
        },
    )
    monkeypatch.setattr(
        world.imports,
        "prepare_scene_relations_context",
        lambda context, result: {**context, "_new_entity_refs": {}},
    )
    monkeypatch.setattr(world, "relation_history", history)
    monkeypatch.setattr(world, "prepare_world_audit_groups", lambda **k: {"groups": []})
    monkeypatch.setattr(pipeline, "_finish_state_review", state_review)
    return db, store, frozen, source, caller


async def finish(scope):
    db, store, frozen, source, caller = scope
    return await pipeline._finish_scene_results(db, store, frozen, source, None, caller)


async def test_branches_overlap_preserve_peer_journals_and_recover_without_io(
    monkeypatch,
):
    setup = scope(monkeypatch)
    db, store, frozen, _, caller = setup
    task = asyncio.create_task(finish(setup))
    await asyncio.wait_for(caller.started["enrich_scene"].wait(), 2)
    await asyncio.wait_for(caller.started["execute_world_request"].wait(), 2)
    assert caller.peak == 2 and not task.done()
    async with caller.session_gate:
        current = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        current.payload["host_checkpoint"] = "preserved"
        await store.replace_frozen_payload(current)
        await db.commit()
    caller.release.set()
    result = await asyncio.wait_for(task, 2)
    assert db.peak == 1 and result.payload["host_checkpoint"] == "preserved"
    assert result.payload["state_review_joined"]
    assert all(
        result.payload[key]["stage"] == "sampled"
        for key in ("scene_enrichment", "scene_enrichment_review", "scene_world")
    )
    calls = deepcopy(caller.calls)
    await finish((db, store, result, setup[3], caller))
    assert caller.calls == calls and store.run.budget_remaining is None


@pytest.mark.parametrize("failure", ["enrich_scene", "execute_world_request"])
async def test_unknown_stops_new_admission_and_drains_other_branch(monkeypatch, failure):
    setup = scope(monkeypatch, failure=failure)
    caller = setup[-1]
    task = asyncio.create_task(finish(setup))
    await asyncio.wait_for(caller.failed.wait(), 2)
    assert not task.done()
    caller.release.set()
    # A peer's proven-unissued admission stop may precede the original error.
    with pytest.raises((SceneCallFailedError, LLMAdmissionStoppedError)):
        await asyncio.wait_for(task, 2)
    assert caller.active == caller.cancelled == 0
    assert [method for method, _ in caller.calls] == [
        "enrich_scene",
        "execute_world_request",
    ]
    payload = setup[1].frozen.payload
    assert payload["scene_enrichment"]["stage"] == (
        "failed" if failure == "enrich_scene" else "sampled"
    )
    assert payload["scene_world"]["stage"] == (
        "failed" if failure == "execute_world_request" else "sampled"
    )
    assert "scene_enrichment_review" not in payload
    with pytest.raises(pipeline.SamplePendingReconciliationError):
        await finish((setup[0], setup[1], setup[1].frozen, setup[3], caller))
    assert len(caller.calls) == 2


async def test_cancellation_drains_sent_calls_without_cancelling_providers(monkeypatch):
    setup = scope(monkeypatch)
    caller = setup[-1]
    task = asyncio.create_task(finish(setup))
    for started in caller.started.values():
        await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    caller.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert caller.cancelled == caller.active == 0
    assert all(
        setup[1].frozen.payload[key]["stage"] == "sampled"
        for key in ("scene_enrichment", "scene_world")
    )
    assert "scene_enrichment_review" not in setup[1].frozen.payload


async def test_preparation_failure_releases_transaction_while_sent_peer_drains(
    monkeypatch,
):
    setup = scope(monkeypatch)
    db, store, _, _, caller = setup

    async def changed_source(*args):
        await caller.started["enrich_scene"].wait()
        await db.operation()
        raise pipeline.CommitConflictError("source_changed", "synthetic source changed")

    monkeypatch.setattr(world.imports, "prepare_scene_world_context", changed_source)
    task = asyncio.create_task(finish(setup))
    await asyncio.wait_for(db.rolled_back.wait(), 2)
    assert not task.done() and not db.transaction and not caller.session_gate.locked()
    caller.release.set()
    with pytest.raises((pipeline.CommitConflictError, LLMAdmissionStoppedError)):
        await asyncio.wait_for(task, 2)
    assert [method for method, _ in caller.calls] == ["enrich_scene"]
    assert store.frozen.payload["scene_enrichment"]["stage"] == "sampled"
    assert "world_preparation" not in store.frozen.payload
    assert not db.transaction and db.peak == 1


@pytest.mark.parametrize("budget,parallelism", [(8, 2), (None, 1)])
async def test_finite_budget_and_serial_caller_keep_original_order(
    monkeypatch, budget, parallelism
):
    setup = scope(monkeypatch, budget=budget, parallelism=parallelism)
    caller = setup[-1]
    caller.release.set()
    result = await finish(setup)
    assert [method for method, _ in caller.calls] == [
        "enrich_scene",
        "review_scene_enrichment",
        "execute_world_request",
    ]
    assert caller.peak == 1 and result.payload["state_review_joined"]
    assert setup[1].run.budget_remaining == (5 if budget == 8 else None)


@pytest.mark.parametrize(
    "key",
    [
        "scene_enrichment",
        "scene_enrichment_review",
        "scene_world",
        "scene_relations",
        "scene_world_review_group_old",
    ],
)
@pytest.mark.parametrize("stage", ["sampling", "failed", "unknown"])
async def test_prior_unreconciled_either_branch_blocks_all_new_io(
    monkeypatch, key, stage
):
    setup = scope(monkeypatch)
    setup[1].frozen.payload[key] = {"stage": stage}
    with pytest.raises(pipeline.SamplePendingReconciliationError):
        await finish(setup)
    assert setup[-1].calls == []


async def test_stage_wall_is_safe_log_only_and_labels_failure(monkeypatch, caplog):
    frozen = scope(monkeypatch)[2].model_copy(
        update={"novel_id": "6dbed354-2582-43fd-925f-67a4d14894a6"}
    )
    prior = frozen.model_dump()
    values = iter([10.0, 10.25])
    monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: next(values)))

    async def failed():
        raise ValueError("PRIVATE manuscript and secret")

    with caplog.at_level(logging.INFO, logger=pipeline.__name__):
        with pytest.raises(ValueError):
            await pipeline._scene_stage_wall(frozen, "world", failed, reused=False)
    assert "wall_ms=250.000" in caplog.text and "status=failed" in caplog.text
    assert f"novel_id={frozen.novel_id}" in caplog.text
    assert "run_id=synthetic-run attempt_id=attempt scene_index=0" in caplog.text
    assert "PRIVATE" not in caplog.text
    assert frozen.model_dump() == prior


async def test_disabled_stage_and_invalid_identifiers_are_explicit(monkeypatch, caplog):
    frozen = scope(monkeypatch)[2].model_copy(
        update={
            "novel_id": "PRIVATE manuscript",
            "run_id": "PRIVATE\nrun",
            "attempt_id": "PRIVATE attempt",
            "payload": {"scene_index": True},
        }
    )

    async def disabled():
        return frozen

    with caplog.at_level(logging.INFO, logger=pipeline.__name__):
        assert (
            await pipeline._scene_stage_wall(
                frozen, "enrichment", disabled, reused=False, enabled=False
            )
        ) is frozen
    assert "novel_id=<invalid> run_id=<invalid> attempt_id=<invalid>" in caplog.text
    assert "scene_index=<invalid>" in caplog.text
    assert "status=not_run enabled=False reused=False" in caplog.text
    assert "PRIVATE" not in caplog.text
