"""Independent-review protocol checks; fixtures are not real-model quality evidence."""

import json
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import select

from modules.evolution.llm_sampler import ProjectLLMSampler
from modules.evolution.pipeline import SamplePendingReconciliationError
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_source_integrity import request, seed
from modules.evolution.workflow import reading_status
from modules.story.continuity.models import MemoryEvent
from modules.world.models.core import CoreEntity
from modules.writing.facade import get_latest_draft_for_chapter


class ReviewClient:
    provider_id = "fixture"
    model = "independent-review"

    def __init__(self, db, verdict, *, fail=False):
        self.db, self.verdict, self.fail = db, verdict, fail
        self.inputs = []

    async def generate_structured(self, request, schema, *, diagnostics, **options):
        assert not self.db.in_transaction()
        assert options == {"max_fix_attempts": 0, "transport_retries": False}
        value = json.loads(request.messages[-1].content)
        self.inputs.append(value)
        diagnostics.append(
            {
                "kind": "structured_usage",
                "status": "succeeded",
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            }
        )
        if self.fail:
            raise ValueError("provider result lost")
        return schema.model_validate(
            {
                "events": [
                    {
                        "event_index": 0,
                        "verdict": self.verdict,
                        "reason": "Fixture verdict for arrival or denial",
                        "quotes": [value["scene_text"]],
                    }
                ]
            }
        )


class Sample:
    def __init__(self, client):
        self.calls = 0
        self.verify_state_events = ProjectLLMSampler(client).verify_state_events

    async def sample(self, *, scene_text, input_manifest):
        self.calls += 1
        return {
            "observations": [
                {
                    "predicate": scene_text,
                    "quote": scene_text,
                    "modality": "event_observed",
                    "mentions": [{"surface": "林舟", "entity_type": "character"}],
                }
            ],
            "scene_events": [
                {
                    "dimension": "locations",
                    "event_type": "entity_moved",
                    "subject_surface": "林舟",
                    "source_observation_indices": [0],
                    "snapshot_after": {"text_state": "青竹镇", "moved_from": "白石城"},
                }
            ],
            "paid_call_receipt": {
                "schema": "fixture.sample",
                "usage": {"total_tokens": 7},
            },
            # A generator cannot self-approve by forging host fields.
            "state_review": {"stage": "sampled", "result": {"events": []}},
        }


async def setup(
    db, nid, *, text="林舟没有离开白石城。", verdict="contradicted", fail=False, budget=2
):
    scene_id = await seed(db, nid, {1: text})
    db.add(
        CoreEntity(
            novel_id=UUID(nid), entity_type="character", name="林舟", status="canonical"
        )
    )
    await db.commit()
    client = ReviewClient(db, verdict, fail=fail)
    sampler = Sample(client)
    register_scene_sampler("state-review-test", lambda db, novel_id: sampler)
    task = request(
        nid,
        scene_id,
        text,
        sampler_provider="state-review-test",
        state_review_version=1,
        budget_total=budget,
    )
    return task, sampler, client, PostgresAttemptStore(db, nid)


@pytest.mark.parametrize(
    "text,verdict,count",
    [
        ("林舟没有离开白石城。", "contradicted", 0),
        ("林舟从白石城出发，到达青竹镇。", "supported", 1),
        ("林舟想从白石城去青竹镇。", "unverifiable", 0),
    ],
)
async def test_independent_result_controls_actual_story_writes_and_free_replay(
    db_session, evolution_project_id, text, verdict, count
):
    db, nid = db_session, evolution_project_id
    task, sampler, client, store = await setup(db, nid, text=text, verdict=verdict)
    result = await handle_evolution_scene_step(db, task)
    events = list(
        await db.scalars(select(MemoryEvent).where(MemoryEvent.novel_id == UUID(nid)))
    )
    assert len(events) == count
    assert client.inputs[0]["scene_text"] == text
    assert client.inputs[0]["events"][0]["snapshot_after"]["text_state"] == "青竹镇"
    frozen = await store.load_frozen(task.meta["run_key"], result["attempt_id"])
    assert len(frozen.payload["gated_scene_events"]) == 1 - count
    assert frozen.payload["state_review"]["result"]["events"][0]["verdict"] == verdict
    receipt = await store.load_receipt(task.meta["run_key"], result["attempt_id"])
    assert len(receipt.paid_call_receipts) == 2
    assert (await store.load_run(task.meta["run_key"])).budget_remaining == 0
    assert (await handle_evolution_scene_step(db, task))["attempt_id"] == result[
        "attempt_id"
    ]
    assert sampler.calls == len(client.inputs) == 1

    if count:
        from modules.evolution.state_review import reviewed_events

        for mutation in (
            {"owner_epoch": frozen.owner_epoch + 1},
            {"source_manifest_hash": "f" * 64},
            {"previous_receipt": "e" * 32},
            {"payload": {**frozen.payload, "scene_text": "不同来源"}},
        ):
            assert not reviewed_events(frozen.model_copy(update=mutation))[0]
        journal = frozen.payload["state_review"]
        verdict = journal["result"]["events"][0]
        for invalid in (
            [],
            [verdict, verdict],
            [{**verdict, "event_index": 1}],
            [{**verdict, "quotes": ["不是原文"]}],
        ):
            altered = frozen.model_copy(
                update={
                    "payload": {
                        **frozen.payload,
                        "state_review": {**journal, "result": {"events": invalid}},
                    }
                }
            )
            assert not reviewed_events(altered)[0]


async def test_review_budget_pause_retains_sample_then_recovers_only_review(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    task, sampler, client, store = await setup(db, nid, budget=1)
    run = await store.register_run(task.meta["run_key"], mode="append", budget_total=1)
    draft = await get_latest_draft_for_chapter(db, nid, 1)
    run.reading_plan_json = {
        "steps": [
            {
                "scene_index": 0,
                "source_binding": {
                    "chapter_index": 1,
                    "draft_id": str(draft.id),
                    "content_hash": draft.content_hash,
                },
            }
        ]
    }
    await db.commit()
    result = await handle_evolution_scene_step(db, task)
    assert not result["reading_complete"]
    state = (await reading_status(db, nid, task.meta["run_key"]))["run"]
    assert state["status"] == "needs_budget" and state["completed_scenes"] == 0
    frozen = await store.load_pending_frozen(task.meta["run_key"], 0)
    assert frozen.payload["stage"] == "compiled" and not client.inputs
    # Emulate the persisted outcome of a separate, explicit budget authorization.
    run = await store.load_run(task.meta["run_key"])
    run.budget_total += 1
    run.budget_remaining += 1
    run.reading_plan_json = None
    await db.commit()
    recovered = await handle_evolution_scene_step(db, task)
    assert recovered["attempt_id"] == frozen.attempt_id
    assert sampler.calls == len(client.inputs) == 1


async def test_review_failure_preserves_paid_receipt_and_never_retries(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    task, sampler, client, store = await setup(db, nid, fail=True)
    with pytest.raises(SceneCallFailedError):
        await handle_evolution_scene_step(db, task)
    await db.rollback()
    frozen = await store.load_pending_frozen(task.meta["run_key"], 0)
    assert (
        frozen.payload["state_review"]["paid_call_receipt"]["outcome"] == "failed_final"
    )
    assert (await store.load_run(task.meta["run_key"])).committed_scene_index == -1
    with pytest.raises(SamplePendingReconciliationError):
        await handle_evolution_scene_step(db, task)
    assert sampler.calls == len(client.inputs) == 1


async def test_domain_failure_replays_frozen_review_without_model_connection(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    task, sampler, client, store = await setup(
        db, nid, text="林舟从白石城出发，到达青竹镇。", verdict="supported"
    )
    with patch(
        "modules.story.facade.replace_scene_memory_events",
        autospec=True,
        side_effect=RuntimeError("domain failed"),
    ):
        with pytest.raises(RuntimeError, match="domain failed"):
            await handle_evolution_scene_step(db, task)
    await db.rollback()
    frozen = await store.load_pending_frozen(task.meta["run_key"], 0)
    assert frozen.payload["stage"] == "verified"
    task.meta["sampler_provider"] = "unavailable-on-recovery"
    recovered = await handle_evolution_scene_step(db, task)
    assert recovered["attempt_id"] == frozen.attempt_id
    assert sampler.calls == len(client.inputs) == 1
    assert (await store.load_run(task.meta["run_key"])).budget_remaining == 0
