"""Immutable revisions, exact retries and author decisions survive machine updates."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError
from modules.evolution.ledger import (
    list_ledger,
    persist_discovery_claim,
    read_author_panorama,
    read_ledger_entry,
    read_ledger_evidence,
    save_ledger_decision,
)
from modules.evolution.ledger_contracts import LedgerClaim
from modules.evolution.models import EvolutionLedgerEntry, EvolutionLedgerRevision
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.evolution.tests.test_workflow import seed
from modules.story.facade import get_scenes_by_novel
from modules.writing.facade import create_draft_only


async def prepared(db, nid):
    text = "甲紧张时摸了戒指。"
    await seed(db, nid, 1, text)
    scene = (await get_scenes_by_novel(db, nid))[0]

    class Sampler:
        async def sample(self, *, scene_text, input_manifest):
            return {"observations": [{"predicate": text, "quote": text}]}

    provider = "ledger-persistence-" + nid
    register_scene_sampler(provider, lambda db, novel_id: Sampler())
    await handle_evolution_scene_step(
        db,
        SimpleNamespace(
            meta={
                "novel_id": nid,
                "scene_id": scene["id"],
                "scene_index": 0,
                "chapter_index": 1,
                "scene_text": text,
                "run_key": "ledger-base",
                "sampler_provider": provider,
            }
        ),
    )
    await db.commit()
    store = PostgresAttemptStore(db, nid)
    receipt = await store.load_head_receipt("ledger-base")
    frozen = await store.load_frozen("ledger-base", receipt.attempt_id)
    observation = frozen.payload["compiled_observations"][0]
    claim = LedgerClaim(
        category="conditional_behavior",
        label="紧张时摸戒指",
        statement="甲在此次紧张时摸了戒指。",
        confidence=0.6,
        conditions=["紧张"],
        method_fingerprint="b" * 64,
        evidence=[
            {
                "observation_id": observation["observation_id"],
                "quote": text,
                "position": {
                    "scene_id": scene["id"],
                    "scene_index": 0,
                    "chapter_index": 1,
                },
                "modality": "event_observed",
                "source_ref": observation["evidence_quotes"][0]["source_ref"],
                "purpose": "occurrence",
                "occurrence_kind": "event",
                "occurrence_id": observation["observation_id"],
            }
        ],
        dependencies=[
            {
                "run_key": "ledger-base",
                "attempt_id": receipt.attempt_id,
                "scene_id": scene["id"],
                "scene_index": 0,
                "source_manifest_hash": frozen.source_manifest_hash,
            }
        ],
    )
    change = {
        "action": "new",
        "category": claim.category,
        "label": claim.label,
        "statement": claim.statement,
        "conditions": claim.conditions,
        "confidence": claim.confidence,
        "evidence": [
            {
                "observation_id": observation["observation_id"],
                "purpose": "occurrence",
                "occurrence_kind": "event",
            }
        ],
    }
    return claim, change


async def test_ledger_replay_decision_revision_and_source_change(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db, nid, change, claim, operation_key="a" * 64, review={"verdict": "supported"}
    )
    await db.commit()
    assert (
        await persist_discovery_claim(
            db,
            nid,
            change,
            claim,
            operation_key="a" * 64,
            review={"verdict": "supported"},
        )
    )["replayed"]
    with pytest.raises(ConflictError, match="同一次操作"):
        await persist_discovery_claim(
            db,
            nid,
            change,
            claim.model_copy(update={"confidence": 0.8}),
            operation_key="a" * 64,
            review={"verdict": "supported"},
        )
    # Another generation over identical support must not count as another event.
    assert (
        await persist_discovery_claim(
            db,
            nid,
            change,
            claim,
            operation_key="c" * 64,
            review={"verdict": "supported"},
        )
    )["replayed"]
    entry_id = first["entry_id"]
    decision = {
        "operation_id": uuid4(),
        "expected_revision": 1,
        "decision": "corrected",
        "corrected_statement": "只是这次试探的动作。",
    }
    saved = await save_ledger_decision(db, nid, entry_id, decision)
    await db.commit()
    assert saved["revision"] == 2
    assert (await save_ledger_decision(db, nid, entry_id, decision))["replayed"]
    updated = claim.model_copy(
        update={"statement": "这是一次有条件的行为观察。", "confidence": 0.7}
    )
    enhancement = {
        **change,
        "action": "narrow",
        "target_entry_id": entry_id,
        "expected_revision": 2,
        "statement": updated.statement,
    }
    await persist_discovery_claim(
        db,
        nid,
        enhancement,
        updated,
        operation_key="d" * 64,
        review={"verdict": "supported"},
    )
    await db.commit()
    current = await read_ledger_entry(db, nid, entry_id)
    assert current["revision"] == 3 and current["source_status"] == "current"
    assert (
        current["current_author_decision"]["corrected_statement"]
        == decision["corrected_statement"]
    )
    old = await read_ledger_entry(db, nid, entry_id, revision=1)
    assert old["claim"]["statement"] == claim.statement and old["author_decision"] == {}
    assert len(old["history"]) == 3
    await create_draft_only(db, nid, 1, content="甲没有摸戒指。")
    await db.commit()
    stale = await read_ledger_entry(db, nid, entry_id)
    assert stale["source_status"] == "source_changed"
    assert stale["current_author_decision"] == current["current_author_decision"]
    assert (await save_ledger_decision(db, nid, entry_id, decision))["revision"] == 2


async def test_ledger_scope_cas_and_transactional_rollback(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db, nid, change, claim, operation_key="e" * 64, review={"verdict": "uncertain"}
    )
    await db.rollback()
    assert await db.scalar(select(func.count()).select_from(EvolutionLedgerEntry)) == 0
    assert await db.scalar(select(func.count()).select_from(EvolutionLedgerRevision)) == 0
    first = await persist_discovery_claim(
        db, nid, change, claim, operation_key="e" * 64, review={"verdict": "uncertain"}
    )
    await db.commit()
    assert (await list_ledger(db, nid, through_scene_index=0))["total"] == 1
    assert (await list_ledger(db, nid, through_scene_index=0, category="commitment"))[
        "total"
    ] == 0
    assert (await list_ledger(db, nid, through_scene_index=-1))["total"] == 0
    with pytest.raises(ConflictError, match="新修订"):
        await save_ledger_decision(
            db,
            nid,
            first["entry_id"],
            {"operation_id": uuid4(), "expected_revision": 99, "decision": "reject"},
        )
    # A different, existing project must not resolve this project's entry identity.
    from modules.project.models import Project

    other = Project(
        id=uuid4(),
        title="其他合成作品",
        owner_id=UUID("00000000-0000-0000-0000-000000000000"),
    )
    db.add(other)
    await db.commit()
    with pytest.raises(NotFoundError):
        await read_ledger_entry(db, str(other.id), first["entry_id"])


async def test_author_panorama_and_literal_source_readback(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db, nid, change, claim, operation_key="f" * 64, review={"verdict": "supported"}
    )
    await db.commit()
    panorama = await read_author_panorama(db, nid, claim.dependencies[0].scene_id)
    assert panorama["author_only"] and panorama["state"]["viewpoint"]["kind"] == "author"
    assert panorama["ledger"]["total"] == 1
    source = await read_ledger_evidence(db, nid, first["entry_id"], 0)
    assert source["quote"] == "甲紧张时摸了戒指。" and not source["historical"]
    with pytest.raises(NotFoundError):
        await read_ledger_evidence(db, nid, first["entry_id"], 99)


async def test_demo_principal_cannot_observe_author_ledger(
    db_session, evolution_project_id
):
    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal

    token = bind_principal(
        AccountPrincipal(
            account_id=BOOTSTRAP_ACCOUNT_ID,
            status="active",
            identity_type="account",
            support_code="synthetic",
            access_scope="demo_readonly",
            demo_project_id=UUID(evolution_project_id),
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await list_ledger(db_session, evolution_project_id, through_scene_index=0)
    finally:
        reset_principal(token)


async def test_ledger_public_routes_return_real_revisions(
    async_client, db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db, nid, change, claim, operation_key="1" * 64, review={"verdict": "supported"}
    )
    await db.commit()
    response = await async_client.get(
        "/api/evolution/ledger", params={"novel_id": nid, "through_scene_index": 0}
    )
    assert response.status_code == 200 and response.json()["total"] == 1
    entry_id = first["entry_id"]
    decision = {"operation_id": str(uuid4()), "expected_revision": 1, "decision": "keep"}
    saved = await async_client.post(
        f"/api/evolution/ledger/{entry_id}/decision",
        params={"novel_id": nid},
        json=decision,
    )
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    detail = await async_client.get(
        f"/api/evolution/ledger/{entry_id}", params={"novel_id": nid}
    )
    assert (
        detail.status_code == 200
        and detail.json()["author_decision"]["decision"] == "keep"
    )
    source = await async_client.get(
        f"/api/evolution/ledger/{entry_id}/evidence/0",
        params={"novel_id": nid, "revision": 1},
    )
    assert source.status_code == 200 and source.json()["quote"] == "甲紧张时摸了戒指。"


async def test_panorama_compares_actual_scene_records_without_inventing_absent_states(
    db_session, evolution_project_id
):
    from datetime import UTC, datetime

    from modules.story.continuity.tests.test_p2a_read_side import _checkpoint, _scene

    db, nid = db_session, evolution_project_id
    first = await _scene(db, nid, 0, 1)
    second = await _scene(db, nid, 1, 2)
    key, holder = str(uuid4()), str(uuid4())
    await _checkpoint(
        db,
        nid,
        first,
        "entities",
        {"entities": {key: {"name": "铜钥匙", "custody_holder": holder}}},
        created_at=datetime.now(UTC),
    )
    await _checkpoint(
        db,
        nid,
        second,
        "entities",
        {"entities": {key: {"name": "铜钥匙", "custody_holder": str(uuid4())}}},
        created_at=datetime.now(UTC),
    )
    await db.commit()
    panorama = await read_author_panorama(db, nid, second.id)
    changes = panorama["changes"]
    holder_change = next(
        item for item in changes["items"] if item["field"] == "custody_holder"
    )
    assert changes["basis_scene_index"] == 0
    assert holder_change["before"] == holder and holder_change["before_known"]
    assert holder_change["after"] != holder and holder_change["after_known"]
    assert (
        holder_change["before_source"]["checkpoint_id"]
        != holder_change["after_source"]["checkpoint_id"]
    )
    start = await read_author_panorama(db, nid, first.id)
    assert start["changes"]["basis_scene_index"] is None
    assert all(not item["before_known"] for item in start["changes"]["items"])
    assert panorama["coverage"]["status"] == "not_checked"


@pytest.mark.parametrize("review_verdict", ["uncertain", "supported"])
async def test_question_proposal_preserves_supported_baseline_and_routing(
    db_session, evolution_project_id, review_verdict
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db,
        nid,
        change,
        claim,
        operation_key="supported-baseline",
        review={"verdict": "supported", "reason": "原句只支持一次。"},
    )
    later = claim.model_copy(update={"statement": "可能还有未核实的条件。"})
    candidate = await persist_discovery_claim(
        db,
        nid,
        {
            **change,
            "action": "question",
            "target_entry_id": first["entry_id"],
            "expected_revision": 1,
            "statement": later.statement,
        },
        later,
        operation_key="uncertain-candidate",
        review={"verdict": review_verdict, "reason": "问题有依据，答案仍待核。"},
    )
    await db.commit()
    current = await read_ledger_entry(db, nid, candidate["entry_id"])
    listed = next(
        item
        for item in (await list_ledger(db, nid, through_scene_index=0))["items"]
        if item["entry_id"] == candidate["entry_id"]
    )
    for item in (current, listed):
        assert item["independent_review"] == {
            "verdict": review_verdict,
            "reason": "问题有依据，答案仍待核。",
        }
        assert item["previous_supported"]["revision"] == 1
        assert item["previous_supported"]["claim"]["statement"] == claim.statement
    old = await read_ledger_entry(db, nid, first["entry_id"], revision=1)
    assert old["head_revision"] == 1
    assert old["claim"]["statement"] == claim.statement
    assert old["previous_supported"] is None
    assert old["independent_review"]["verdict"] == "supported"

    assert candidate["entry_id"] != first["entry_id"]
    assert current["proposal_target"] == {"entry_id": first["entry_id"], "revision": 1}
    from modules.evolution.discovery import prepare_discovery

    store = PostgresAttemptStore(db, nid)
    receipt = await store.load_head_receipt("ledger-base")
    frozen = await store.load_frozen("ledger-base", receipt.attempt_id)
    next_inputs = await prepare_discovery(
        db,
        store,
        frozen.model_copy(update={"payload": {**frozen.payload, "scene_index": 1}}),
    )
    assert set(next_inputs["themes"]) == {first["entry_id"]}
    assert all(
        set(unit["theme"]["prior_review"]) == {"verdict"}
        for batch in next_inputs["batches"]
        for unit in batch["historical_context"]
        if "theme" in unit
    )

    if review_verdict == "supported":
        await save_ledger_decision(
            db,
            nid,
            candidate["entry_id"],
            {
                "operation_id": str(uuid4()),
                "expected_revision": 1,
                "decision": "keep",
                "note": "保留疑问，不改原理解。",
            },
        )
        question = {
            **change,
            "action": "question",
            "target_entry_id": first["entry_id"],
            "expected_revision": 1,
            "statement": later.statement,
        }
        updated = await persist_discovery_claim(
            db,
            nid,
            question,
            later,
            operation_key="question-requalified",
            review={"verdict": "uncertain", "reason": "新复核仍未确定答案。"},
        )
        assert updated["entry_id"] == candidate["entry_id"]
        assert updated["revision"] == 3
        requalified = await read_ledger_entry(db, nid, updated["entry_id"])
        assert requalified["proposal_target"] == current["proposal_target"]
        assert requalified["previous_supported"]["claim"]["statement"] == claim.statement
        assert requalified["author_decision"]["note"] == "保留疑问，不改原理解。"
        replay = await persist_discovery_claim(
            db,
            nid,
            question,
            later,
            operation_key="question-requalified",
            review={"verdict": "uncertain", "reason": "新复核仍未确定答案。"},
        )
        assert replay["replayed"] is True and replay["entry_id"] == candidate["entry_id"]
        assert (await read_ledger_entry(db, nid, first["entry_id"]))["head_revision"] == 1


async def test_same_origin_reextraction_refreshes_qualification_and_keeps_author_decision(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db,
        nid,
        change,
        claim,
        operation_key="old-qualification",
        review={"verdict": "uncertain"},
    )
    await save_ledger_decision(
        db,
        nid,
        first["entry_id"],
        {
            "operation_id": uuid4(),
            "expected_revision": 1,
            "decision": "keep",
            "note": "保留这个观察，仍不概括。",
        },
    )
    refreshed = claim.model_copy(
        update={
            "dependencies": [
                claim.dependencies[0].model_copy(update={"attempt_id": "new-attempt"})
            ],
            "method_fingerprint": "c" * 64,
        }
    )
    updated = await persist_discovery_claim(
        db,
        nid,
        change,
        refreshed,
        operation_key="new-qualification",
        review={"verdict": "supported"},
    )
    await db.commit()
    assert updated["entry_id"] == first["entry_id"] and updated["revision"] == 3
    latest = await read_ledger_entry(db, nid, updated["entry_id"])
    assert latest["independent_review"]["verdict"] == "supported"
    assert latest["claim"]["dependencies"][0]["attempt_id"] == "new-attempt"
    assert latest["claim"]["method_fingerprint"] == "c" * 64
    assert latest["current_author_decision"]["note"] == "保留这个观察，仍不概括。"
    assert latest["counts"]["occurrences"] == 1
    assert latest["counts"]["extractions"] == 2
    assert (
        await persist_discovery_claim(
            db,
            nid,
            change,
            refreshed,
            operation_key="new-qualification",
            review={"verdict": "supported"},
        )
    )["replayed"]
    original = await read_ledger_entry(db, nid, first["entry_id"], revision=1)
    assert original["independent_review"]["verdict"] == "uncertain"
    assert original["claim"]["dependencies"][0]["attempt_id"] != "new-attempt"


async def test_uncertain_new_extraction_matching_supported_origin_stays_a_candidate(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    claim, change = await prepared(db, nid)
    first = await persist_discovery_claim(
        db,
        nid,
        change,
        claim,
        operation_key="supported-origin",
        review={"verdict": "supported"},
    )
    candidate = await persist_discovery_claim(
        db,
        nid,
        change,
        claim,
        operation_key="uncertain-reextraction",
        review={"verdict": "uncertain", "reason": "主体仍待核实。"},
    )
    await db.commit()
    assert candidate["entry_id"] != first["entry_id"]
    supported = await read_ledger_entry(db, nid, first["entry_id"])
    assert supported["head_revision"] == 1
    assert supported["independent_review"]["verdict"] == "supported"
    proposal = await read_ledger_entry(db, nid, candidate["entry_id"])
    assert proposal["proposal_target"] == {"entry_id": first["entry_id"], "revision": 1}
    assert proposal["independent_review"]["verdict"] == "uncertain"
    assert proposal["previous_supported"]["claim"]["statement"] == claim.statement
    assert (
        await persist_discovery_claim(
            db,
            nid,
            change,
            claim,
            operation_key="uncertain-reextraction",
            review={"verdict": "uncertain", "reason": "主体仍待核实。"},
        )
    )["replayed"]
