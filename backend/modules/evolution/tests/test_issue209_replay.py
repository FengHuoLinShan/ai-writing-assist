"""Actual Scene journals: shard identity proof, capacity gaps and idempotent replay."""

import pytest

from modules.evolution import discovery
from modules.evolution.ledger import list_ledger, persist_discovery_claim
from modules.evolution.ledger_contracts import LedgerClaim
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.state_review import SceneCallFailedError
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_discovery import DiscoverySampler, task_for


@pytest.mark.parametrize("failed_identity", [False, True])
async def test_index_shard_reviews_are_frozen_and_never_repeat_adoption(
    db_session, evolution_project_id, monkeypatch, failed_identity
):
    class Sampler(DiscoverySampler):
        async def discover_details(self, *, inputs):
            if inputs["scene_index"] == 0:
                return await super().discover_details(inputs=inputs)
            self.calls.append(("discover", inputs))
            changes = []
            if inputs["allow_new_themes"] and inputs["current_observation_ids"]:
                changes = [
                    {
                        "action": "new",
                        "category": "clue",
                        "label": "铜钥匙",
                        "statement": "甲举起了铜钥匙。",
                        "confidence": 0.8,
                        "evidence": [
                            {
                                "observation_id": inputs["current_observation_ids"][0],
                                "purpose": "occurrence",
                                "occurrence_kind": "event",
                            }
                        ],
                    }
                ]
            return {
                "result": {
                    "changes": changes,
                    "coverage": "inspected",
                    "coverage_note": "只检查本片。",
                },
                "paid_call_receipt": {
                    "provider": "fixture",
                    "usage": {"total_tokens": 2},
                },
            }

        async def review_discovery(self, *, inputs):
            if inputs.get("theme_identity_check") and failed_identity:
                self.calls.append("identity_failure")
                raise SceneCallFailedError(
                    {
                        "outcome": "failed_final",
                        "usage": {"usage_complete": True, "unknown_attempts": 0},
                        "attempts_detail": [
                            {"status": "failed", "error_kind": "invalid_json"}
                        ],
                    }
                )
            return await super().review_discovery(inputs=inputs)

    db, nid = db_session, evolution_project_id
    sampler = Sampler()
    provider = "issue209-shards-" + nid
    register_scene_sampler(provider, lambda db, novel_id: sampler)
    first = await task_for(db, nid, 0, "甲紧张地摸了摸戒指。", provider=provider)
    await handle_evolution_scene_step(db, first)
    await db.commit()
    original = (await list_ledger(db, nid, through_scene_index=0))["items"][0]
    claim = LedgerClaim.model_validate(original["claim"]).model_copy(
        update={
            "category": "clue",
            "label": "戒指线索",
            "statement": "甲这次摸了戒指。",
        }
    )
    await persist_discovery_claim(
        db,
        nid,
        {
            "action": "new",
            "category": "clue",
            "label": claim.label,
            "statement": claim.statement,
            "confidence": claim.confidence,
            "evidence": [
                {
                    "observation_id": claim.evidence[0].observation_id,
                    "purpose": "occurrence",
                    "occurrence_kind": "event",
                }
            ],
        },
        claim,
        operation_key="synthetic-second-theme",
        review={"verdict": "supported"},
    )
    await db.commit()
    # Force two exhaustive index shards and separate context units using small
    # deterministic inputs, without paying for a model or creating giant prose.
    monkeypatch.setattr(
        discovery, "_chunks", lambda values, budget=16000: [[value] for value in values]
    )
    second = await task_for(db, nid, 1, "甲举起了铜钥匙。", provider=provider)
    result = await handle_evolution_scene_step(db, second)
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    frozen = await store.load_frozen("discovery-test", result["attempt_id"])
    journals = [
        value
        for key, value in frozen.payload.items()
        if key.startswith("scene_discovery_identity_")
    ]
    assert len(journals) == 1
    assert journals[0]["stage"] == ("failed" if failed_identity else "sampled")
    materialized = frozen.payload["discovery_materialization"]["applied"]
    assert len(materialized) == (0 if failed_identity else 1)
    assert (
        bool(frozen.payload["discovery_result"]["coverage"]["identity_review_gaps"])
        == failed_identity
    )
    before = len(sampler.calls)
    replay = await handle_evolution_scene_step(db, second)
    await db.commit()
    assert replay["attempt_id"] == result["attempt_id"]
    assert len(sampler.calls) == before
    ledger = await list_ledger(db, nid, through_scene_index=1)
    assert ledger["total"] == (2 if failed_identity else 3)
    assert all(item["revision"] == 1 for item in ledger["items"])
