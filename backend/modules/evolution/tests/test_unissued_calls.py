"""Unissued requests return their own claim without altering paid peers."""

import asyncio

import pytest

from infrastructure.llm.errors import LLMAdmissionStoppedError
from infrastructure.llm.tests.test_luna_context_scope import luna_snapshot
from modules.evolution.commit import CommitConflictError
from modules.evolution.pipeline import _return_unissued_scene_call, _run_scene_call
from modules.evolution.tests.test_identity_parallel import identity_scope


async def assert_unissued_claims_returned(db, nid, budget):
    store, frozen, source, *_ = await identity_scope(db, nid)
    run = await store.load_run(frozen.run_id, for_update=True)
    run.budget_total = run.budget_remaining = budget
    if budget is None:
        run.llm_snapshot_json = luna_snapshot()
    run.reading_plan_json = {
        "budget_mode": "confirmed_scope" if budget is None else "bounded",
        "category_rescans": [{"operation_id": "rescan", "calls_remaining": budget}],
    }
    frozen = frozen.model_copy(
        update={"payload": {**frozen.payload, "category_rescan_operation_id": "rescan"}}
    )
    await store.replace_frozen_payload(frozen)
    await db.commit()
    gate, unissued = asyncio.Lock(), asyncio.Event()
    key = "scene_discovery_identity_0_1"
    inputs = {"method": "review_discovery", "part": 1}

    async def queued(**kwargs):
        unissued.set()
        await settled.wait()
        raise LLMAdmissionStoppedError()

    async def sent(**kwargs):
        return {"result": {"verdicts": []}, "paid_call_receipt": {"fixture": "paid"}}

    async def call(journal_key, envelope, provider):
        return await _run_scene_call(
            db,
            store,
            frozen,
            source,
            journal_key=journal_key,
            inputs=envelope,
            call_inputs={"inputs": {"scene_text": "合成资料", "changes": []}},
            call=provider,
            session_gate=gate,
        )

    settled = asyncio.Event()
    peer = asyncio.create_task(call(key, inputs, queued))
    try:
        await asyncio.wait_for(unissued.wait(), 2)
        await call("scene_discovery_identity_0_2", {"part": 2}, sent)
    finally:
        settled.set()
    with pytest.raises(LLMAdmissionStoppedError):
        await peer
    current = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    assert key not in current.payload
    assert current.payload["scene_discovery_identity_0_2"]["paid_call_receipt"] == {
        "fixture": "paid"
    }
    assert current.payload["scene_discovery_0"] == frozen.payload["scene_discovery_0"]
    expected = None if budget is None else budget - 1
    run = await store.load_run(frozen.run_id)
    assert run.budget_remaining == expected
    assert run.reading_plan_json["category_rescans"][0]["calls_remaining"] == expected
    # Repeated cleanup cannot refund a second time or erase the paid journal.
    await _return_unissued_scene_call(db, store, frozen, key, inputs, session_gate=gate)
    assert (await store.load_run(frozen.run_id)).budget_remaining == expected
    with pytest.raises(CommitConflictError, match="unissued claim changed"):
        await _return_unissued_scene_call(
            db,
            store,
            frozen,
            "scene_discovery_identity_0_2",
            {"part": 2},
            session_gate=gate,
        )
    await db.rollback()


@pytest.mark.parametrize("budget", [8, None])
async def test_unissued_claims_returned(db_session, evolution_project_id, budget):
    await assert_unissued_claims_returned(db_session, evolution_project_id, budget)
