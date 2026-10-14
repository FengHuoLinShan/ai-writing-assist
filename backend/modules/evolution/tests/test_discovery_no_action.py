"""Skip structurally impossible new calls, retaining source and real journals."""

from copy import deepcopy

import pytest

from infrastructure.llm.collaboration import content_hash
from modules.evolution.commit import FrozenAttempt
from modules.evolution.discovery import (
    _discovery_envelope,
    compile_discovery,
    finish_scene_discovery,
    method_fingerprint,
)
from modules.evolution.pipeline import SamplePendingReconciliationError
from modules.evolution.store import PostgresAttemptStore


async def frozen_no_action(db, nid, *, stage=None):
    store = PostgresAttemptStore(db, nid)
    await store.register_run("no-action", mode="bootstrap", budget_total=32)
    batch = {
        "allow_new_themes": False,
        "current_observation_ids": ["current"],
        "current_observations": [{"observation_id": "current"}],
        "historical_context": [{"observation": {"observation_id": "prior"}}],
    }
    prepared = {
        "batches": [batch],
        "unsupported_batches": [],
        "coverage": {},
        "themes": {},
        "observations": {},
        "method_fingerprint": method_fingerprint(),
    }
    frozen = FrozenAttempt(
        novel_id=nid,
        run_id="no-action",
        attempt_id="scope",
        owner_epoch=1,
        producer_version="test",
        source_manifest_hash="a" * 64,
        payload={"discovery_version": 1, "discovery_preparation": prepared},
    )
    if stage:
        journal = {
            "stage": stage,
            "input_hash": content_hash(_discovery_envelope(frozen, prepared, batch)),
            "paid_call_receipt": {"original": True},
        }
        if stage == "sampled":
            journal["result"] = {
                "changes": [],
                "coverage": "inspected",
                "coverage_note": "原始模型结果，不能冒充新的宿主证明。",
            }
        frozen.payload["scene_discovery_0"] = journal
    await store.save_frozen(frozen)
    await db.commit()
    return store, frozen


async def never_call(*args, **kwargs):
    raise AssertionError("No model call may be made")


async def test_no_action_scope_durable_without_model_or_budget(
    db_session, evolution_project_id
):
    store, frozen = await frozen_no_action(db_session, evolution_project_id)
    before = deepcopy(frozen.payload["discovery_preparation"])
    result = await finish_scene_discovery(db_session, store, frozen, None, never_call)
    assert result.payload["discovery_preparation"] == before
    assert "scene_discovery_0" not in result.payload
    assert "paid_call_receipt" not in result.payload["discovery_no_action_0"]
    compiled = result.payload["discovery_result"]
    assert compiled["changes"] == []
    assert compiled["coverage"]["no_action_batches"] == [0]
    assert compiled["inspected"][0]["coverage"] == "not_checked"
    assert compiled["inspected"][0]["model_called"] is False
    assert set(compiled["coverage"]["category_coverage"].values()) == {"not_checked"}
    assert (await store.load_run("no-action")).budget_remaining == 32
    replayed = await finish_scene_discovery(db_session, store, result, None, never_call)
    assert replayed.payload == result.payload


@pytest.mark.parametrize("stage", ["sampling", "failed"])
async def test_no_action_does_not_bypass_unknown_or_failed_journal(
    db_session, evolution_project_id, stage
):
    store, frozen = await frozen_no_action(db_session, evolution_project_id, stage=stage)
    original = deepcopy(frozen.payload["scene_discovery_0"])
    with pytest.raises(SamplePendingReconciliationError):
        await finish_scene_discovery(db_session, store, frozen, None, never_call)
    retained = await store.load_frozen("no-action", "scope")
    assert retained.payload["scene_discovery_0"] == original
    assert "discovery_no_action_0" not in retained.payload
    assert (await store.load_run("no-action")).budget_remaining == 32


async def test_completed_call_reuses_original_without_no_action_reclassification(
    db_session, evolution_project_id
):
    store, frozen = await frozen_no_action(
        db_session, evolution_project_id, stage="sampled"
    )
    original = deepcopy(frozen.payload["scene_discovery_0"])
    result = await finish_scene_discovery(db_session, store, frozen, None, never_call)
    assert result.payload["scene_discovery_0"] == original
    assert "discovery_no_action_0" not in result.payload
    assert result.payload["discovery_result"]["coverage"]["no_action_batches"] == []
    assert (await store.load_run("no-action")).budget_remaining == 32


@pytest.mark.parametrize("drift", ["new_permission", "target", "hash", "existing_call"])
async def test_no_action_proof_fails_closed_after_scope_drift(
    db_session, evolution_project_id, drift
):
    store, frozen = await frozen_no_action(db_session, evolution_project_id)
    result = await finish_scene_discovery(db_session, store, frozen, None, never_call)
    changed = result.model_copy(deep=True)
    batch = changed.payload["discovery_preparation"]["batches"][0]
    if drift == "new_permission":
        batch["allow_new_themes"] = True
    elif drift == "target":
        batch["historical_context"].append({"theme": {"entry_id": "added"}})
    elif drift == "hash":
        changed.payload["discovery_no_action_0"]["input_hash"] = "changed"
    else:
        changed.payload["scene_discovery_0"] = {"stage": "sampling"}
    with pytest.raises(ValueError, match="discovery_no_action_scope_changed"):
        compile_discovery(changed)
