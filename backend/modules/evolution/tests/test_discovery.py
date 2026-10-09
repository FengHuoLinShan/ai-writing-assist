"""Actual Scene handler: long-range evidence, exceptions, replay and paid recovery."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.evolution.discovery import CONDITIONS_SEMANTICS
from modules.evolution.ledger import list_ledger, read_ledger_entry, save_ledger_decision
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.pipeline import SamplePendingReconciliationError
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.store import BudgetExhaustedError, PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import (
    empty_world_response,
    request_start,
    seed,
    structure_response,
)
from modules.evolution.workflow import start_reading
from modules.story.facade import get_scenes_by_novel


def generated(inputs, *, first_occurrence=None):
    text = inputs["scene_text"]
    current = inputs["current_observation_ids"][0]
    themes = [unit["theme"] for unit in inputs["historical_context"] if "theme" in unit]
    if "摸了摸" not in text and "没有摸" not in text and "第一次" not in text:
        return {
            "changes": [],
            "coverage": "inspected",
            "coverage_note": "本场观察未发现新的相关证据。",
        }
    change = {
        "category": "conditional_behavior",
        "label": "紧张时摸戒指",
        "statement": "甲在已知紧张场景中出现摸戒指行为，仍有例外。",
        "conditions": ["紧张"],
        "confidence": 0.6,
        "evidence": [
            {
                "observation_id": current,
                "purpose": "occurrence",
                "occurrence_kind": "event",
            }
        ],
        "action": "new",
    }
    if themes:
        theme = themes[0]
        change.update(
            action="enhance",
            target_entry_id=theme["entry_id"],
            expected_revision=theme["revision"],
        )
    if "没有摸" in text:
        change["action"] = "exception"
        change["evidence"][0]["role"] = "counterevidence"
        change["statement"] = "同样紧张时也有明确不摸戒指的例外，不能概括为必然行为。"
    if "第一次" in text:
        change["evidence"][0].update(
            occurrence_kind="recall", same_occurrence_as=first_occurrence
        )
    return {
        "changes": [change],
        "coverage": "inspected",
        "coverage_note": "本次给定观察已检查，未召回范围不作不存在判断。",
    }


class DiscoverySampler:
    def __init__(self, *, fail_review=False):
        self.calls = []
        self.first_occurrence = None
        self.fail_review = fail_review

    async def sample(self, *, scene_text, input_manifest):
        self.calls.append("sample")
        return {
            "observations": [
                {
                    "predicate": scene_text,
                    "quote": scene_text,
                    "modality": "character_statement"
                    if "第一次" in scene_text
                    else "event_observed",
                    "mentions": [{"surface": "甲", "entity_type": "character"}],
                }
            ],
            "paid_call_receipt": {"provider": "fixture", "usage": {"total_tokens": 1}},
        }

    async def discover_details(self, *, inputs):
        self.calls.append(("discover", inputs))
        assert inputs["conditions_semantics"] == CONDITIONS_SEMANTICS
        assert all(
            item["conditions_semantics"] == CONDITIONS_SEMANTICS
            for item in inputs["theme_index"]
        )
        if inputs["scene_index"] == 0:
            self.first_occurrence = inputs["current_observations"][0][
                "event_occurrence_id"
            ]
        return {
            "result": generated(inputs, first_occurrence=self.first_occurrence),
            "paid_call_receipt": {"provider": "fixture", "usage": {"total_tokens": 2}},
        }

    async def review_discovery(self, *, inputs):
        self.calls.append("review")
        assert [item["change_index"] for item in inputs["changes"]] == list(
            range(len(inputs["changes"]))
        )
        for change in inputs["changes"]:
            target = change["target_theme"]
            if change["target_entry_id"]:
                assert target["entry_id"] == change["target_entry_id"]
                assert target["revision"] == change["expected_revision"]
                assert target["label"] == "紧张时摸戒指"
                theme = next(
                    unit["theme"]
                    for unit in inputs["historical_context"]
                    if unit.get("theme", {}).get("entry_id") == target["entry_id"]
                )
                assert (
                    target["evidence_observation_ids"]
                    == theme["evidence_observation_ids"]
                )
                assert target["modality"] == theme["modality"]
                assert target["occurrences"] == theme["occurrences"]
                assert target["evidence_uses"] == theme["evidence_uses"]
                assert target["conditions_semantics"] == theme["conditions_semantics"]
                assert target["conditions_semantics"] == CONDITIONS_SEMANTICS
                assert any(
                    use["role"] == "support"
                    and use["purpose"] == "occurrence"
                    and use["occurrence_kind"] == "event"
                    and use["occurrence_id"] == self.first_occurrence
                    for use in target["evidence_uses"]
                )
            else:
                assert target is None
        if self.fail_review:
            raise SceneCallFailedError(
                {
                    "outcome": "failed_final",
                    "provider": "fixture",
                    "usage": {"total_tokens": 3},
                }
            )
        return {
            "result": {
                "verdicts": [
                    {
                        "change_index": index,
                        "verdict": "supported",
                        "reason": "合成场景原句支持该项，未把缺描写当反例。",
                        "occurrence_observation_ids": [
                            item["observation_id"]
                            for item in change["evidence"]
                            if item.get("purpose") == "occurrence"
                            and item.get("role", "support") == "support"
                        ],
                        "recall_identity_reviews": [
                            {
                                "observation_id": item["observation_id"],
                                "occurrence_id": item["same_occurrence_as"],
                                "verdict": "supported",
                                "original_observation_ids": next(
                                    occurrence["observation_ids"]
                                    for occurrence in change["target_theme"][
                                        "occurrences"
                                    ]
                                    if occurrence["occurrence_id"]
                                    == item["same_occurrence_as"]
                                ),
                                "identity_observation_ids": [item["observation_id"]],
                                "reason": "本合成原句明确指认同一次原动作。",
                            }
                            for item in change["evidence"]
                            if item.get("occurrence_kind") == "recall"
                            and item.get("same_occurrence_as")
                        ],
                        "counterevidence_observation_ids": [
                            item["observation_id"]
                            for item in change["evidence"]
                            if item.get("role") == "counterevidence"
                        ],
                    }
                    for index, change in enumerate(inputs["changes"])
                ]
            },
            "paid_call_receipt": {"provider": "fixture", "usage": {"total_tokens": 3}},
        }


async def task_for(db, nid, index, text, *, provider, budget=100, discovery=True):
    await seed(db, nid, index + 1, text)
    scene = (await get_scenes_by_novel(db, nid))[index]
    return SimpleNamespace(
        meta={
            "novel_id": nid,
            "scene_id": scene["id"],
            "scene_index": index,
            "scene_text": text,
            "chapter_index": index + 1,
            "run_key": "discovery-test",
            "sampler_provider": provider,
            "budget_total": budget,
            "discovery_version": int(discovery),
        }
    )


async def test_continuous_discovery_keeps_long_range_sources_decisions_and_occurrences(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    sampler = DiscoverySampler()
    provider = "discovery-" + nid
    register_scene_sampler(provider, lambda db, novel_id: sampler)
    texts = [
        "甲紧张地摸了摸戒指。",
        *["甲安静地等候。"] * 4,
        "甲同样紧张，双手垂着，没有摸戒指。",
        "乙说，甲第一次紧张时摸了摸戒指。",
    ]
    entry_id = None
    for index, text in enumerate(texts):
        task = await task_for(db, nid, index, text, provider=provider)
        result = await handle_evolution_scene_step(db, task)
        await db.commit()
        if index == 0:
            entry_id = (await list_ledger(db, nid, through_scene_index=0))["items"][0][
                "entry_id"
            ]
            await save_ledger_decision(
                db,
                nid,
                entry_id,
                {
                    "operation_id": uuid4(),
                    "expected_revision": 1,
                    "decision": "corrected",
                    "corrected_statement": "只当作观察，不能认定为固定习惯。",
                },
            )
            await db.commit()
        if index == 5:
            last = [call[1] for call in sampler.calls if isinstance(call, tuple)][-1]
            assert any(
                "摸了摸" in unit.get("observation", {}).get("predicate", "")
                for unit in last["historical_context"]
            )
    before = len(sampler.calls)
    replay = await handle_evolution_scene_step(db, task)
    assert replay["attempt_id"] == result["attempt_id"] and len(sampler.calls) == before
    entry = await read_ledger_entry(db, nid, entry_id)
    assert entry["revision"] == 4 and entry["source_status"] == "current"
    assert (
        entry["counts"]["occurrences"] == 1
        and entry["counts"]["counter_occurrences"] == 1
        and entry["counts"]["observations"] == 3
    )
    assert entry["current_author_decision"]["decision"] == "corrected"
    assert any(item["role"] == "counterevidence" for item in entry["claim"]["evidence"])
    assert entry["claim"]["modality"] == "hypothesis"


@pytest.mark.parametrize("failure", ["budget", "review"])
async def test_discovery_reservation_frozen_recovery_and_unknown_call_are_distinct(
    db_session, evolution_project_id, failure
):
    db, nid = db_session, evolution_project_id
    sampler = DiscoverySampler(fail_review=failure == "review")
    provider = "discovery-recovery-" + nid
    register_scene_sampler(provider, lambda db, novel_id: sampler)
    task = await task_for(
        db,
        nid,
        0,
        "甲紧张地摸了摸戒指。",
        provider=provider,
        budget=2 if failure == "budget" else 4,
    )
    with pytest.raises(
        BudgetExhaustedError if failure == "budget" else SceneCallFailedError
    ):
        await handle_evolution_scene_step(db, task)
    await db.rollback()
    store = PostgresAttemptStore(db, nid)
    assert await store.load_head_receipt("discovery-test") is None
    assert (await list_ledger(db, nid, through_scene_index=0))["total"] == 0
    pending = await store.load_pending_frozen("discovery-test", 0)
    assert pending.payload["scene_discovery_0"]["stage"] == "sampled"
    if failure == "review":
        count = len(sampler.calls)
        with pytest.raises(SamplePendingReconciliationError):
            await handle_evolution_scene_step(db, task)
        assert len(sampler.calls) == count
        return
    run = await store.load_run("discovery-test")
    run.budget_total += 1
    run.budget_remaining += 1
    await db.commit()
    await handle_evolution_scene_step(db, task)
    assert sampler.calls.count("sample") == 1
    assert len([item for item in sampler.calls if isinstance(item, tuple)]) == 1
    assert sampler.calls.count("review") == 1
    receipt = await store.load_head_receipt("discovery-test")
    assert len(receipt.paid_call_receipts) == 3


@pytest.mark.parametrize("quarantine", [False, True])
async def test_project_llm_reading_plan_executes_real_discovery_adapter(
    db_session, evolution_project_id, account_llm_connection, monkeypatch, quarantine
):
    db, nid = db_session, evolution_project_id
    await seed(db, nid, 1, "甲紧张地摸了摸戒指。")
    schemas = []

    async def provider(self, request, *, complete_stream=False):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])["title"]
        schemas.append(schema)
        if response := empty_world_response(request):
            return response
        if response := structure_response(request):
            return response
        if schema == "SceneSample":
            result = {
                "observations": [
                    {"predicate": "甲摸了戒指。", "quote": "甲紧张地摸了摸戒指。"}
                ]
            }
        else:
            inputs = json.loads(
                next(
                    message.content
                    for message in request.messages
                    if message.role == "user"
                )
            )
            if schema == "DiscoveryOutput":
                result = generated(inputs)
                if quarantine:
                    result["changes"].append(
                        {**result["changes"][0], "action": "enhance"}
                    )
            else:
                assert schema == "DiscoveryReview"
                result = {
                    "verdicts": [
                        {
                            "change_index": 0,
                            "verdict": "supported",
                            "reason": "原句支持。",
                            "occurrence_observation_ids": inputs[
                                "current_observation_ids"
                            ],
                        }
                    ]
                }
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    run = (
        await start_reading(
            db, nid, await request_start(db, nid, end_chapter=1, discover_details=True)
        )
    )["run"]
    assert run["discovery_enabled"]
    task = await db.get(AsyncTask, UUID(run["task_id"]))
    result = await handle_evolution_scene_step(db, task)
    await db.commit()
    assert "DiscoveryOutput" in schemas and "DiscoveryReview" in schemas
    entry = (await list_ledger(db, nid, through_scene_index=0))["items"][0]
    assert entry["source_status"] == "current" and entry["counts"]["occurrences"] == 1
    frozen = await db.scalar(
        select(EvolutionFrozenAttempt).where(
            EvolutionFrozenAttempt.novel_id == UUID(nid),
            EvolutionFrozenAttempt.attempt_key == result["attempt_id"],
        )
    )
    assert frozen.payload_json["discovery_materialization"]["applied"]
    if quarantine:
        discovery = frozen.payload_json["discovery_result"]
        assert discovery["inspected"][0]["coverage"] == "partial"
        assert any(
            item["reason"] == "invalid_changes_quarantined"
            for item in discovery["pending"]
        )


@pytest.mark.parametrize("review_failure", [False, True])
async def test_settled_discovery_output_failure_is_partial_without_resending(
    db_session, evolution_project_id, review_failure
):
    from modules.evolution.ledger import read_discovery_coverage

    class InvalidOutputSampler(DiscoverySampler):
        def fail_output(self):
            raise SceneCallFailedError(
                {
                    "provider": "fixture",
                    "outcome": "failed_final",
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 5,
                        "total_tokens": 8,
                        "usage_complete": True,
                        "unknown_attempts": 0,
                    },
                    "attempts_detail": [
                        {"status": "failed", "error_kind": "schema_validation"}
                    ],
                }
            )

        async def discover_details(self, *, inputs):
            if not review_failure:
                self.calls.append("failed-generation")
                self.fail_output()
            return await super().discover_details(inputs=inputs)

        async def review_discovery(self, *, inputs):
            self.calls.append("failed-review")
            self.fail_output()

    db, nid = db_session, evolution_project_id
    sampler = InvalidOutputSampler()
    provider = "settled-output-" + nid
    register_scene_sampler(provider, lambda db, novel_id: sampler)
    task = await task_for(db, nid, 0, "甲紧张地摸了摸戒指。", provider=provider)
    await handle_evolution_scene_step(db, task)
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    receipt = await store.load_head_receipt("discovery-test")
    assert receipt is not None
    frozen = await store.load_frozen("discovery-test", receipt.attempt_id)
    key = "scene_discovery_review_0" if review_failure else "scene_discovery_0"
    assert frozen.payload[key]["stage"] == "failed"
    assert frozen.payload[key]["paid_call_receipt"]["outcome"] == "failed_final"
    assert frozen.payload["discovery_result"]["coverage"]["failed_batches"] == [0]
    assert (await list_ledger(db, nid, through_scene_index=0))["total"] == 0
    coverage = await read_discovery_coverage(db, nid, task.meta["scene_id"])
    assert coverage["status"] == "partial" and coverage["inspected_batches"] == 0
    before = len(sampler.calls)
    assert (await handle_evolution_scene_step(db, task))["recovered"]
    assert len(sampler.calls) == before


async def test_settled_failed_batch_allows_budget_resume_without_repeating_paid_call(
    db_session, evolution_project_id, monkeypatch
):
    from modules.evolution import discovery
    from modules.evolution.workflow import reading_status

    class TwoObservationFailureSampler(DiscoverySampler):
        async def sample(self, *, scene_text, input_manifest):
            self.calls.append("sample")
            return {
                "observations": [
                    {"predicate": "甲摸戒指。", "quote": "甲紧张地摸了摸戒指。"},
                    {"predicate": "乙站着。", "quote": "乙静静站着。"},
                ]
            }

        async def discover_details(self, *, inputs):
            self.calls.append(tuple(inputs["current_observation_ids"]))
            raise SceneCallFailedError(
                {
                    "outcome": "failed_final",
                    "usage": {"usage_complete": True, "unknown_attempts": 0},
                    "attempts_detail": [
                        {"status": "failed", "error_kind": "invalid_json"}
                    ],
                }
            )

    db, nid = db_session, evolution_project_id
    sampler = TwoObservationFailureSampler()
    provider = "settled-budget-" + nid
    register_scene_sampler(provider, lambda db, novel_id: sampler)
    monkeypatch.setattr(
        discovery, "_chunks", lambda values, budget=16000: [[item] for item in values]
    )
    task = await task_for(
        db, nid, 0, "甲紧张地摸了摸戒指。乙静静站着。", provider=provider, budget=2
    )
    with pytest.raises(BudgetExhaustedError):
        await handle_evolution_scene_step(db, task)
    await db.rollback()
    store = PostgresAttemptStore(db, nid)
    pending = await store.load_pending_frozen("discovery-test", 0)
    assert pending.payload["scene_discovery_0"]["stage"] == "failed"
    run = await store.load_run("discovery-test", for_update=True)
    run.reading_plan_json = {
        "steps": [
            {"scene_index": 0, "source_binding": pending.payload["source_binding"]}
        ],
        "pause_reason": "budget",
        "discovery_version": 1,
    }
    await db.commit()
    assert (await reading_status(db, nid, "discovery-test"))["run"][
        "status"
    ] == "needs_budget"
    # Grant another call in the fixture; existing failed request must stay frozen.
    run = await store.load_run("discovery-test", for_update=True)
    run.reading_plan_json = {}
    run.budget_total += 1
    run.budget_remaining += 1
    await db.commit()
    before = list(sampler.calls)
    await handle_evolution_scene_step(db, task)
    await db.commit()
    assert sampler.calls[:-1] == before and len(sampler.calls) == 3
    assert await store.load_head_receipt("discovery-test") is not None


def test_discovery_output_budget_changes_frozen_method(monkeypatch):
    from modules.evolution import discovery

    current = discovery.method_fingerprint()
    assert discovery.DISCOVERY_OUTPUT_TOKENS == 393216
    monkeypatch.setattr(discovery, "DISCOVERY_OUTPUT_TOKENS", 65536)
    assert discovery.method_fingerprint() != current
