"""A deliberate unchecked scope is explicit, source-pinned and never a retry."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.collaboration import content_hash
from infrastructure.tasks.models import AsyncTask
from modules.evolution.commit import ApplierResult, CommitConflictError, apply_frozen
from modules.evolution.consumer_reuse import observation_tokens, read_set
from modules.evolution.contracts import CommittedPrefix
from modules.evolution.discovery import (
    _discovery_envelope,
    _require_discovery_journals,
    compile_discovery,
    finish_scene_discovery,
)
from modules.evolution.discovery_gap import GAPS_KEY, confirmed_discovery_gaps
from modules.evolution.facade import (
    DiscoveryGapConfirmation,
    confirm_discovery_unknown_gap,
)
from modules.evolution.pipeline import _source_verifier
from modules.evolution.state_review import (
    has_unreconciled_scene_calls,
    paid_call_receipts,
)
from modules.evolution.tests.test_discovery_batch_parallel import Batches, batch_scope
from modules.evolution.workflow import reading_status, resume_reading
from modules.project.facade import require_understanding_writer
from modules.writing.facade import create_draft_only


async def gap_fixture(db, nid, monkeypatch):
    store, frozen, source, prepared, plans, generated = await batch_scope(db, nid)
    snapshot = {
        "profile": {
            "provider_id": "codex",
            "model": "gpt-6-luna",
            "connection_verified": True,
            "extra": {"reasoning_effort": "max"},
        }
    }
    run = await store.load_run(frozen.run_id)
    run.llm_snapshot_json = snapshot
    task = AsyncTask(
        id=uuid4(),
        novel_id=UUID(nid),
        task_type="evolution_scene_step_v2",
        status="failed",
        recovery_policy="manual_resume",
        meta={
            "original": {"private": "kept"},
            "recovery_required": False,
            "_understanding_owner": await require_understanding_writer(
                db, nid, engine="evolution"
            ),
        },
        result={"original_failure": "kept", "recovery_required": False},
    )
    db.add(task)
    run.reading_plan_json = {
        "steps": [{"scene_index": 0, "source_binding": source.model_dump(mode="json")}],
        "task_id": str(task.id),
    }
    frozen.payload["stage"] = "verified"
    frozen.payload["scene_discovery_0"] = {
        "stage": "failed",
        "input_hash": content_hash(_discovery_envelope(frozen, prepared, plans[0][1])),
        "read_set": read_set(
            run,
            "scene_discovery",
            {"method": prepared["method_fingerprint"], "inputs": plans[0][1]},
            tokens=observation_tokens(frozen.payload),
        ),
        "paid_call_receipt": {
            "provider": "codex",
            "model": "gpt-6-luna",
            "outcome": "failed_final",
            "usage": None,
            "attempts_detail": [],
        },
    }
    await store.replace_frozen_payload(frozen)
    await db.commit()

    async def current_snapshot(db, novel_id, *, provider_id):
        assert novel_id == nid and provider_id == "codex"
        return snapshot

    async def source_step(db, novel_id, step):
        assert novel_id == nid and step["scene_index"] == 0

    @asynccontextmanager
    async def snapshot_client(db, novel_id, frozen_snapshot):
        assert novel_id == nid and frozen_snapshot == snapshot
        yield SimpleNamespace(
            model_name="gpt-6-luna",
            resolve_request_defaults=lambda request: SimpleNamespace(
                extra=snapshot["profile"].get("extra", {})
            ),
        )

    monkeypatch.setattr(
        "modules.project.facade.open_project_snapshot_llm_client", snapshot_client
    )
    # Source slice verification remains real; only the synthetic plan's lookup is stubbed.
    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot", current_snapshot
    )
    monkeypatch.setattr("modules.evolution.workflow._read_step", source_step)
    confirmation = DiscoveryGapConfirmation(
        operation_id=uuid4(),
        attempt_id=frozen.attempt_id,
        journal_key="scene_discovery_0",
        expected_frozen_hash=content_hash(frozen.model_dump(mode="json")),
        original_request_hash="b" * 64,
        accept_unchecked_gap=True,
    )
    return store, frozen, source, generated, task, confirmation, snapshot


async def test_explicit_gap_reuses_prefix_sends_only_unstarted_batch_and_keeps_unknown(
    db_session,
    evolution_project_id,
    monkeypatch,
):
    db, nid = db_session, evolution_project_id
    store, frozen, source, generated, task, confirmation, _ = await gap_fixture(
        db, nid, monkeypatch
    )
    before = deepcopy(frozen.payload)
    receipts = deepcopy(paid_call_receipts(before))
    run = await store.load_run("parallel")
    budget = (run.budget_total, run.budget_remaining)
    gap = await confirm_discovery_unknown_gap(db, nid, "parallel", confirmation)
    await db.commit()
    confirmed = await store.load_frozen("parallel", "scope")
    assert {k: v for k, v in confirmed.payload.items() if k != GAPS_KEY} == before
    assert confirmed_discovery_gaps(confirmed) == [gap]
    assert paid_call_receipts(confirmed.payload) == receipts
    assert task.status == "failed" and task.result["original_failure"] == "kept"
    assert task.meta["original"] == {"private": "kept"}
    assert task.meta["recovery_required"] is True
    assert (run.budget_total, run.budget_remaining) == budget
    assert await confirm_discovery_unknown_gap(db, nid, "parallel", confirmation) == gap
    assert len((await store.load_run("parallel")).reading_plan_json[GAPS_KEY]) == 1
    assert not has_unreconciled_scene_calls(confirmed.payload, frozen=confirmed)
    # The queue resumes normally, without rewriting an unknown journal.
    await resume_reading(db, nid, "parallel")
    await db.commit()
    assert task.status == "pending"
    caller = Batches(generated, empty=True)
    caller.release.set()
    result = await finish_scene_discovery(db, store, confirmed, source, caller)
    assert caller.calls == [("discover_details", 1)]
    assert result.payload["scene_discovery_0"] == before["scene_discovery_0"]
    compiled = result.payload["discovery_result"]
    assert compiled["coverage"]["author_confirmed_unknown_gaps"] == [gap]
    assert compiled["inspected"][0]["coverage"] == "not_checked"
    assert compiled["pending"] == [{"reason": "author_confirmed_unknown_gap", "batch": 0}]
    assert compiled["changes"] == []
    assert paid_call_receipts(result.payload)[0] == receipts[0]
    again = await finish_scene_discovery(db, store, result, source, caller)
    assert again.payload == result.payload and caller.calls == [("discover_details", 1)]

    async def applier(db, frozen):
        # The shared commit gate, not one chosen applier, preserves the gap.
        return ApplierResult(
            committed_prefix=CommittedPrefix(
                through_scene_index=0, through_source_revision=1
            )
        )

    receipt = await apply_frozen(
        db,
        frozen=result,
        store=store,
        applier=applier,
        source_verifier=_source_verifier(source),
        owner_epoch_provider=store.owner_epoch_provider("parallel"),
    )
    await db.commit()
    loaded = await store.load_receipt("parallel", "scope")
    assert loaded == receipt
    assert loaded.coverage.unknown == loaded.coverage.excluded == ["scene_discovery_0"]
    assert loaded.coverage.inspected == []
    assert loaded.paid_call_receipts == receipts
    state = (await reading_status(db, nid, "parallel"))["run"]
    assert state["unchecked_discovery_gaps"] == [gap]
    assert state["completed_scenes"] == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "owner",
        "source",
        "input",
        "method",
        "read_set",
        "core_unknown",
        "peer_unknown",
        "review_unknown",
        "provider",
        "model",
        "unverified",
        "effort",
        "snapshot",
        "running",
        "lease",
        "task_type",
        "already_sampled",
        "result",
        "wrong_attempt",
        "wrong_project",
    ],
)
async def test_confirmation_rejects_drift_other_unknown_or_live_task(
    db_session,
    evolution_project_id,
    monkeypatch,
    mutation,
):
    db, nid = db_session, evolution_project_id
    store, frozen, source, _, task, confirmation, snapshot = await gap_fixture(
        db, nid, monkeypatch
    )
    journal = frozen.payload["scene_discovery_0"]
    if mutation == "hash":
        confirmation = confirmation.model_copy(update={"expected_frozen_hash": "c" * 64})
    elif mutation == "owner":
        frozen.owner_epoch += 1
    elif mutation == "source":
        await create_draft_only(db, nid, 1, "第一章", "来源已变化。")
    elif mutation == "input":
        journal["input_hash"] = "c" * 64
    elif mutation == "method":
        frozen.payload["discovery_preparation"]["method_fingerprint"] = "changed"
    elif mutation == "read_set":
        journal["read_set"]["fields"]["inputs"] = "changed"
    elif mutation in {"core_unknown", "peer_unknown", "review_unknown"}:
        key = {
            "core_unknown": "state_review",
            "peer_unknown": "scene_discovery_1",
            "review_unknown": "scene_discovery_review_0",
        }[mutation]
        frozen.payload[key] = {"stage": "failed", "paid_call_receipt": {}}
    elif mutation in {"provider", "model", "unverified", "effort", "snapshot"}:
        profile = snapshot["profile"]
        if mutation == "provider":
            profile["provider_id"] = "deepseek"
        elif mutation == "model":
            profile["model"] = "gpt-6-sol"
        elif mutation == "unverified":
            profile["connection_verified"] = False
        elif mutation == "effort":
            profile["extra"]["reasoning_effort"] = "high"
        else:
            snapshot["changed"] = True
        run = await store.load_run("parallel")
        run.llm_snapshot_json = deepcopy(snapshot)
    elif mutation == "running":
        task.status = "running"
    elif mutation == "lease":
        task.lease_id = str(uuid4())
    elif mutation == "task_type":
        task.task_type = "evolution_category_rescan_v1"
    elif mutation == "already_sampled":
        journal["stage"] = "sampled"
    elif mutation == "result":
        journal["result"] = {}
    elif mutation == "wrong_attempt":
        confirmation = confirmation.model_copy(update={"attempt_id": "other"})
    elif mutation == "wrong_project":
        nid = str(uuid4())
    await store.replace_frozen_payload(frozen)
    if mutation not in {"hash", "wrong_attempt", "wrong_project"}:
        confirmation = confirmation.model_copy(
            update={"expected_frozen_hash": content_hash(frozen.model_dump(mode="json"))}
        )
    await db.commit()
    with pytest.raises((ConflictError, CommitConflictError, NotFoundError)) as error:
        await confirm_discovery_unknown_gap(db, nid, "parallel", confirmation)
    assert not isinstance(error.value, AssertionError)
    await db.rollback()
    assert GAPS_KEY not in (await store.load_frozen("parallel", "scope")).payload


@pytest.mark.parametrize(
    "mutation",
    [
        "journal",
        "source",
        "prepared",
        "epoch",
        "attempt",
        "consent",
        "request_hash",
        "key",
    ],
)
async def test_confirmed_gap_is_revalidated_before_compile_or_sending(
    db_session,
    evolution_project_id,
    monkeypatch,
    mutation,
):
    store, _, _, _, _, confirmation, _ = await gap_fixture(
        db_session, evolution_project_id, monkeypatch
    )
    await confirm_discovery_unknown_gap(
        db_session, evolution_project_id, "parallel", confirmation
    )
    frozen = await store.load_frozen("parallel", "scope")
    if mutation == "journal":
        frozen.payload["scene_discovery_0"]["paid_call_receipt"]["usage"] = {
            "usage_complete": True
        }
    elif mutation == "source":
        frozen.payload["source_binding"]["content_hash"] = "c" * 64
    elif mutation == "prepared":
        frozen.payload["discovery_preparation"]["batches"][0]["scene_text"] = "changed"
    elif mutation == "epoch":
        frozen.owner_epoch += 1
    elif mutation == "attempt":
        frozen.attempt_id = "other"
    elif mutation == "consent":
        frozen.payload[GAPS_KEY][0]["accept_unchecked_gap"] = False
    elif mutation == "request_hash":
        frozen.payload[GAPS_KEY][0]["original_request_hash"] = "c" * 64
    elif mutation == "key":
        frozen.payload[GAPS_KEY][0]["scope"]["journal_key"] = "state_review"
    assert has_unreconciled_scene_calls(frozen.payload, frozen=frozen)
    with pytest.raises(ConflictError):
        _require_discovery_journals(frozen, frozen.payload["discovery_preparation"])
    with pytest.raises(ConflictError):
        compile_discovery(frozen)


def test_confirmation_requires_explicit_consent_and_optional_generation_only():
    data = dict(
        operation_id=uuid4(),
        attempt_id="attempt",
        journal_key="scene_discovery_0",
        expected_frozen_hash="a" * 64,
        original_request_hash="b" * 64,
        accept_unchecked_gap=True,
    )
    for value in (False, None, "true", 1):
        with pytest.raises(ValidationError):
            DiscoveryGapConfirmation(**{**data, "accept_unchecked_gap": value})
    for key in (
        "state_review",
        "scene_discovery_review_0",
        "scene_discovery_identity_0_1",
        "scene_discovery_00",
    ):
        with pytest.raises(ValidationError):
            DiscoveryGapConfirmation(**{**data, "journal_key": key})
