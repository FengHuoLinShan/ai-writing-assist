"""One physical source occurrence survives semantic re-extraction and batch splits."""

from uuid import uuid4

import pytest

from modules.evolution.contracts import SourceRevisionRef
from modules.evolution.discovery import _compile_change, method_fingerprint
from modules.evolution.ledger_contracts import LedgerClaim, evidence_counts
from modules.evolution.observations import derive_observation_id


def prepared_occurrence():
    novel, scene = str(uuid4()), str(uuid4())
    quote = "甲紧张地摸了摸戒指。"
    source = SourceRevisionRef(
        novel_id=novel,
        source_kind="chapter_draft",
        draft_id="draft-1",
        content_hash="a" * 64,
        chapter_identity="chapter:1",
        start_offset=0,
        end_offset=len(quote),
        range_hash=SourceRevisionRef.compute_range_hash("a" * 64, 0, len(quote)),
        source_revision=1,
        segmentation_version=1,
        source_visibility="working",
    )
    dependency = {
        "run_key": "run",
        "attempt_id": "attempt",
        "scene_id": scene,
        "scene_index": 0,
        "source_manifest_hash": "b" * 64,
    }
    records = {}
    for contract, predicate in [(1, "甲摸戒指。"), (2, "甲紧张时摸戒指。")]:
        identity = derive_observation_id(
            source_ref=source,
            predicate_or_description=predicate,
            modality="event_observed",
            observer_contract_version=contract,
        )
        records[identity] = {
            "observation_id": identity,
            "predicate": predicate,
            "modality": "event_observed",
            "position": {"scene_id": scene, "scene_index": 0, "chapter_index": 1},
            "dependency": dependency,
            "mentions": [],
            "evidence_quotes": [
                {"quote": quote, "source_ref": source.model_dump(mode="json")}
            ],
        }
    prepared = {
        "themes": {},
        "observations": records,
        "method_fingerprint": method_fingerprint(),
    }
    batch = {"current_observation_ids": list(records), "historical_context": []}
    change = {
        "action": "new",
        "category": "conditional_behavior",
        "label": "紧张时摸戒指",
        "statement": "这次紧张时摸了戒指。",
        "conditions": ["紧张"],
        "confidence": 0.7,
        "evidence": [
            {
                "observation_id": identity,
                "purpose": "occurrence",
                "occurrence_kind": "event",
            }
            for identity in records
        ],
    }
    return prepared, batch, change


def test_semantic_and_contract_reextraction_does_not_count_another_occurrence():
    prepared, batch, change = prepared_occurrence()
    claim = LedgerClaim.model_validate(_compile_change(prepared, change, batch)["claim"])
    assert evidence_counts(claim.evidence) == {
        "occurrences": 1,
        "counter_occurrences": 0,
        "exception_occurrences": 0,
        "observations": 2,
        "sources": 1,
        "unknown_occurrences": 0,
    }


@pytest.mark.parametrize(
    "certification, accepted",
    [
        pytest.param(None, False, id="missing"),
        pytest.param(
            {"verdict": "uncertain", "observation_ids": ["current"]},
            False,
            id="uncertain",
        ),
        pytest.param(
            {"verdict": "rejected", "observation_ids": ["current"]}, False, id="rejected"
        ),
        pytest.param(
            {"verdict": "supported", "observation_ids": []}, False, id="no-source"
        ),
        pytest.param(
            {"verdict": "supported", "observation_ids": ["unselected"]},
            False,
            id="visible-unbound",
        ),
        pytest.param(
            {"verdict": "supported", "observation_ids": ["unseen-old"]},
            False,
            id="bound-unseen",
        ),
        pytest.param(
            {"verdict": "supported", "observation_ids": ["current"]}, True, id="certified"
        ),
    ],
)
def test_condition_change_needs_its_own_bound_visible_review(certification, accepted):
    from copy import deepcopy
    from types import SimpleNamespace

    from modules.evolution.discovery import compile_discovery

    prepared, batch, first = prepared_occurrence()
    old_id = batch["current_observation_ids"][0]
    for observation in prepared["observations"].values():
        evidence = observation["evidence_quotes"][0]
        evidence["quote"] = "门外有脚步声，甲紧张地摸了摸戒指。"
        evidence["source_ref"]["end_offset"] = len(evidence["quote"])
        evidence["source_ref"]["range_hash"] = SourceRevisionRef.compute_range_hash(
            "a" * 64, 0, len(evidence["quote"])
        )
    first["conditions"] = ["紧张", "门外脚步声"]
    original = _compile_change(prepared, first, batch)["claim"]
    original["evidence"][1]["observation_id"] = "unseen-old"
    current = deepcopy(prepared["observations"][old_id])
    quote = "乙说甲紧张时会摸戒指，但他未亲眼见过。"
    current.update(
        observation_id="current", predicate=quote, modality="character_statement"
    )
    current["position"].update(scene_id=str(uuid4()), scene_index=1, chapter_index=2)
    current["evidence_quotes"][0]["quote"] = quote
    ref = current["evidence_quotes"][0]["source_ref"]
    ref.update(draft_id="draft-2", chapter_identity="chapter:2", end_offset=len(quote))
    ref["range_hash"] = SourceRevisionRef.compute_range_hash("a" * 64, 0, len(quote))
    prepared["observations"].update(
        current=current, unselected={**current, "observation_id": "unselected"}
    )
    entry_id = str(uuid4())
    prepared["themes"][entry_id] = {"revision": 1, "claim": original}
    batch = {
        "current_observation_ids": ["current", "unselected"],
        "historical_context": [
            {
                "theme": {
                    "entry_id": entry_id,
                    "evidence_observations": [prepared["observations"][old_id]],
                }
            }
        ],
    }
    prepared.update(batches=[batch], unsupported_batches=[], coverage={})
    change = {
        **first,
        "action": "enhance",
        "target_entry_id": entry_id,
        "expected_revision": 1,
        "conditions": ["紧张"],
        "modality": "character_statement",
        "statement": "乙转述甲紧张时摸戒指，尚未验证习惯。",
        "evidence": [
            {
                "observation_id": "current",
                "purpose": "context",
                "occurrence_kind": "context",
            }
        ],
    }
    verdict = {
        "change_index": 0,
        "verdict": "supported",
        "reason": "当前转述有原话支持。",
        "context_observation_ids": ["current"],
    }
    if certification is not None:
        verdict["conditions_review"] = {
            **certification,
            "reason": "旧脚步声是当次背景；一般紧张的说法仅是未核实转述。",
        }
    frozen = SimpleNamespace(
        attempt_id="attempt",
        source_manifest_hash="b" * 64,
        previous_receipt=None,
        payload={
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": {
                    "changes": [change],
                    "coverage": "inspected",
                    "coverage_note": "核对转述。",
                },
            },
            "scene_discovery_review_0": {"result": {"verdicts": [verdict]}},
        },
    )
    result = compile_discovery(frozen)
    if accepted:
        claim = LedgerClaim.model_validate(result["changes"][0]["claim"])
        assert claim.conditions == ["紧张"]
        assert evidence_counts(claim.evidence)["occurrences"] == 1
        assert prepared["themes"][entry_id]["claim"] == original
    else:
        assert result["changes"] == []
        assert (
            result["pending"][0]["reason"]
            == "condition_change_not_independently_confirmed"
        )
    # Reordering preserved conditions requires no new semantic certification.
    change["conditions"] = list(reversed(original["conditions"]))
    verdict.pop("conditions_review", None)
    assert compile_discovery(frozen)["changes"]


def test_new_event_accepts_only_its_exact_host_anchor():
    from copy import deepcopy

    from modules.evolution.discovery import event_occurrence_id

    prepared, batch, change = prepared_occurrence()
    choice = change["evidence"][0]
    observation = prepared["observations"][choice["observation_id"]]
    anchor = event_occurrence_id(observation)
    choice["same_occurrence_as"] = anchor
    claim = LedgerClaim.model_validate(_compile_change(prepared, change, batch)["claim"])
    assert evidence_counts(claim.evidence)["occurrences"] == 1
    assert claim.evidence[0].occurrence_id == anchor

    for invalid in ["invented-anchor", choice["observation_id"]]:
        choice["same_occurrence_as"] = invalid
        with pytest.raises(ValueError, match="occurrence_identity_not_proven"):
            _compile_change(prepared, change, batch)
    choice["same_occurrence_as"] = anchor
    choice["occurrence_kind"] = "recall"
    with pytest.raises(ValueError, match="occurrence_identity_not_proven"):
        _compile_change(prepared, change, batch)
    choice.update(occurrence_kind="event", purpose="context")
    with pytest.raises(ValueError, match="context_cannot_claim_occurrence_identity"):
        _compile_change(prepared, change, batch)
    choice["purpose"] = "occurrence"
    subjective = deepcopy(prepared)
    subjective["observations"][choice["observation_id"]]["modality"] = (
        "character_statement"
    )
    with pytest.raises(ValueError):
        _compile_change(subjective, change, batch)
    other = deepcopy(observation)
    other["evidence_quotes"][0]["source_ref"]["draft_id"] = "another-draft"
    choice["same_occurrence_as"] = event_occurrence_id(other)
    with pytest.raises(ValueError, match="occurrence_identity_not_proven"):
        _compile_change(prepared, change, batch)


def test_supported_new_context_requires_structured_certification():
    from types import SimpleNamespace

    from modules.evolution.discovery import compile_discovery

    prepared, batch, change = prepared_occurrence()
    action_id, context_id = batch["current_observation_ids"]
    change["evidence"][1]["purpose"] = "context"
    prepared.update(batches=[batch], unsupported_batches=[], coverage={})
    review = {
        "change_index": 0,
        "verdict": "supported",
        "reason": "第二条仅共场，不应附入主题背景。",
        "occurrence_observation_ids": [action_id],
    }
    frozen = SimpleNamespace(
        attempt_id="attempt",
        source_manifest_hash="b" * 64,
        previous_receipt=None,
        payload={
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": {
                    "changes": [change],
                    "coverage": "inspected",
                    "coverage_note": "已核对本批。",
                },
            },
            "scene_discovery_review_0": {"result": {"verdicts": [review]}},
        },
    )
    result = compile_discovery(frozen)
    assert not result["changes"]
    assert result["pending"][0]["reason"] == (
        "context_evidence_not_independently_confirmed"
    )
    review["context_observation_ids"] = [context_id]
    claim = compile_discovery(frozen)["changes"][0]["claim"]
    assert evidence_counts(LedgerClaim.model_validate(claim).evidence)["occurrences"] == 1
    # Structured certification, rather than free-form reason, is authoritative.
    review["context_observation_ids"] = []
    review["counterevidence_observation_ids"] = [context_id]
    change["evidence"][1]["role"] = "counterevidence"
    counter = LedgerClaim.model_validate(compile_discovery(frozen)["changes"][0]["claim"])
    assert evidence_counts(counter.evidence)["counter_occurrences"] == 0
    assert counter.evidence[1].purpose == "context"

    # Existing certified context and known anchors do not need recertification.
    entry_id = str(uuid4())
    prepared["themes"][entry_id] = {"revision": 1, "claim": claim}
    batch["historical_context"] = [
        {
            "theme": {
                "entry_id": entry_id,
                "evidence_observations": list(prepared["observations"].values()),
            }
        }
    ]
    change.update(action="enhance", target_entry_id=entry_id, expected_revision=1)
    change["evidence"][1]["role"] = "support"
    review["counterevidence_observation_ids"] = []
    inherited = compile_discovery(frozen)["changes"][0]["claim"]
    assert inherited["evidence"] == claim["evidence"]


def test_new_themes_and_quotes_cannot_escape_the_actual_batch():
    prepared, batch, change = prepared_occurrence()
    with pytest.raises(ValueError, match="new_theme_outside_primary_batch"):
        _compile_change(prepared, change, {**batch, "allow_new_themes": False})
    with pytest.raises(ValueError, match="observation_not_in_frozen_input"):
        _compile_change(
            prepared,
            change,
            {**batch, "current_observation_ids": batch["current_observation_ids"][:1]},
        )


def test_adding_overlapping_sources_does_not_change_the_occurrence_anchor():
    from modules.evolution.discovery import _normalized_evidence
    from modules.evolution.ledger_contracts import LedgerEvidence

    prepared, batch, change = prepared_occurrence()
    original = _compile_change(prepared, change, batch)["claim"]["evidence"][0]
    linked = {
        **original,
        "observation_id": "linked",
        "quote": original["quote"][1:],
        "source_ref": {**original["source_ref"], "start_offset": 1},
    }
    linked["source_ref"]["range_hash"] = SourceRevisionRef.compute_range_hash(
        linked["source_ref"]["content_hash"], 1, linked["source_ref"]["end_offset"]
    )
    normalized = _normalized_evidence([original, linked])
    assert normalized[0]["occurrence_id"] == original["occurrence_id"]
    assert (
        evidence_counts(
            [LedgerEvidence.model_validate(item) for item in [*normalized, original]]
        )["occurrences"]
        == 1
    )


def test_condition_support_is_not_another_reviewed_behavior():
    from types import SimpleNamespace

    from modules.evolution.discovery import compile_discovery

    prepared, batch, change = prepared_occurrence()
    action_id = batch["current_observation_ids"][0]
    condition_id = batch["current_observation_ids"][1]
    condition = prepared["observations"][condition_id]
    condition["predicate"] = "甲紧张。"
    source = condition["evidence_quotes"][0]["source_ref"]
    source["start_offset"] = 2
    source["range_hash"] = SourceRevisionRef.compute_range_hash(
        source["content_hash"], 2, source["end_offset"]
    )
    condition["evidence_quotes"][0]["quote"] = condition["evidence_quotes"][0]["quote"][
        2:
    ]
    change["evidence"][1]["purpose"] = "context"
    claim = LedgerClaim.model_validate(_compile_change(prepared, change, batch)["claim"])
    assert evidence_counts(claim.evidence)["occurrences"] == 1
    assert claim.evidence[1].occurrence_kind == "context"
    # Uncertified condition witnesses cannot add an occurrence.
    change["evidence"][1]["purpose"] = "occurrence"
    prepared.update(batches=[batch], unsupported_batches=[], coverage={})
    frozen = SimpleNamespace(
        attempt_id="attempt",
        source_manifest_hash="b" * 64,
        previous_receipt=None,
        payload={
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": {
                    "changes": [change],
                    "coverage": "inspected",
                    "coverage_note": "已核对本批。",
                },
            },
            "scene_discovery_review_0": {
                "result": {
                    "verdicts": [
                        {
                            "change_index": 0,
                            "verdict": "supported",
                            "reason": "动作只有一次，条件不能增加次数。",
                            "occurrence_observation_ids": [action_id],
                        }
                    ]
                }
            },
        },
    )
    result = compile_discovery(frozen)
    counts = evidence_counts(
        LedgerClaim.model_validate(result["changes"][0]["claim"]).evidence
    )
    assert counts["occurrences"] == 1 and counts["unknown_occurrences"] == 1

    verdict = frozen.payload["scene_discovery_review_0"]["result"]["verdicts"][0]
    verdict["context_observation_ids"] = [condition_id]
    classified = LedgerClaim.model_validate(
        compile_discovery(frozen)["changes"][0]["claim"]
    )
    assert evidence_counts(classified.evidence)["occurrences"] == 1
    assert evidence_counts(classified.evidence)["unknown_occurrences"] == 0
    assert classified.evidence[1].purpose == "context"
    assert classified.evidence[1].occurrence_kind == "context"
    verdict["verdict"] = "uncertain"
    uncertain = LedgerClaim.model_validate(
        compile_discovery(frozen)["changes"][0]["claim"]
    )
    assert uncertain.evidence[1].occurrence_kind == "context"
    verdict["context_observation_ids"] = [action_id]
    conflict = compile_discovery(frozen)
    assert not conflict["changes"]
    assert conflict["pending"][0]["reason"] == "review_evidence_role_conflict"


def test_review_can_confirm_inherited_evidence_but_cannot_invent_counterevidence():
    from copy import deepcopy
    from types import SimpleNamespace

    from modules.evolution.discovery import compile_discovery

    prepared, batch, first = prepared_occurrence()
    original = _compile_change(prepared, first, batch)["claim"]
    entry_id = str(uuid4())
    old_id = batch["current_observation_ids"][0]
    current = deepcopy(prepared["observations"][old_id])
    current.update(observation_id="current-context", predicate="甲在等候。")
    prepared["observations"]["current-context"] = current
    prepared["themes"][entry_id] = {"revision": 1, "claim": original}
    batch = {
        "current_observation_ids": ["current-context"],
        "historical_context": [
            {
                "theme": {
                    "entry_id": entry_id,
                    "evidence_observations": [prepared["observations"][old_id]],
                }
            }
        ],
    }
    prepared.update(batches=[batch], unsupported_batches=[], coverage={})
    change = {
        **first,
        "action": "enhance",
        "target_entry_id": entry_id,
        "expected_revision": 1,
        "evidence": [{"observation_id": "current-context", "purpose": "context"}],
    }
    review = {
        "change_index": 0,
        "verdict": "supported",
        "reason": "旧动作已确认，本场只有背景，不增加发生。",
        "occurrence_observation_ids": [old_id],
        "context_observation_ids": ["current-context"],
    }
    frozen = SimpleNamespace(
        attempt_id="new-attempt",
        source_manifest_hash="b" * 64,
        previous_receipt=None,
        payload={
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": {
                    "changes": [change],
                    "coverage": "inspected",
                    "coverage_note": "已核对本批。",
                },
            },
            "scene_discovery_review_0": {"result": {"verdicts": [review]}},
        },
    )
    result = compile_discovery(frozen)
    assert len(result["changes"]) == 1
    assert (
        evidence_counts(
            LedgerClaim.model_validate(result["changes"][0]["claim"]).evidence
        )["occurrences"]
        == 1
    )
    # Reusing an old physical appearance as context must not revoke its old event.
    change["evidence"].append({"observation_id": old_id, "purpose": "context"})
    review["occurrence_observation_ids"] = []
    review["context_observation_ids"].append(old_id)
    basis_copy = deepcopy(prepared["themes"][entry_id]["claim"])
    reused = compile_discovery(frozen)
    reused_claim = LedgerClaim.model_validate(reused["changes"][0]["claim"])
    assert evidence_counts(reused_claim.evidence)["occurrences"] == 1
    assert any(
        item.observation_id == old_id and item.purpose == "context"
        for item in reused_claim.evidence
    )
    assert prepared["themes"][entry_id]["claim"] == basis_copy
    change["evidence"].pop()
    review["context_observation_ids"].remove(old_id)
    review["occurrence_observation_ids"] = ["not-provided"]
    assert (
        compile_discovery(frozen)["pending"][0]["reason"]
        == "review_evidence_not_in_change"
    )
    # Visible comparison sources are not evidence selected for this change.
    unbound = deepcopy(current)
    unbound["observation_id"] = "visible-unbound-context"
    prepared["observations"][unbound["observation_id"]] = unbound
    batch["current_observation_ids"].append(unbound["observation_id"])
    review["occurrence_observation_ids"] = [old_id]
    assert len(compile_discovery(frozen)["changes"]) == 1
    for verdict in ["supported", "uncertain"]:
        for field in [
            "occurrence_observation_ids",
            "exception_observation_ids",
            "counterevidence_observation_ids",
            "context_observation_ids",
        ]:
            probe = deepcopy(frozen)
            probe.payload["scene_discovery_review_0"]["result"]["verdicts"] = [
                {**review, "verdict": verdict, field: [unbound["observation_id"]]}
            ]
            result = compile_discovery(probe)
            assert not result["changes"]
            assert result["pending"][0]["reason"] == "review_evidence_not_in_change"
    # A review of old evidence cannot certify the unconfirmed current counterclaim.
    change["action"] = "exception"
    change["evidence"][0]["role"] = "counterevidence"
    review.update(occurrence_observation_ids=[], counterevidence_observation_ids=[old_id])
    assert (
        compile_discovery(frozen)["pending"][0]["reason"]
        == "exception_or_counterevidence_not_independently_confirmed"
    )

    # A later review can certify the actual old source, even when the generator
    # only adds current context. It must not certify unseen or reported sources.
    change["action"] = "enhance"
    change["evidence"][0]["role"] = "support"
    review.update(occurrence_observation_ids=[old_id], counterevidence_observation_ids=[])
    original["evidence"] = original["evidence"][:1]
    original["evidence"][0].update(occurrence_kind="unknown", occurrence_id=None)
    basis_copy = deepcopy(original)
    confirmed = LedgerClaim.model_validate(
        compile_discovery(frozen)["changes"][0]["claim"]
    )
    assert evidence_counts(confirmed.evidence)["occurrences"] == 1
    assert evidence_counts(confirmed.evidence)["unknown_occurrences"] == 0
    assert prepared["themes"][entry_id]["claim"] == basis_copy
    review["occurrence_observation_ids"] = []
    unconfirmed = LedgerClaim.model_validate(
        compile_discovery(frozen)["changes"][0]["claim"]
    )
    assert evidence_counts(unconfirmed.evidence)["occurrences"] == 0
    review["occurrence_observation_ids"] = [old_id]
    batch["historical_context"][0]["theme"]["evidence_observations"] = []
    unseen = LedgerClaim.model_validate(compile_discovery(frozen)["changes"][0]["claim"])
    assert evidence_counts(unseen.evidence)["occurrences"] == 0
    batch["historical_context"][0]["theme"]["evidence_observations"] = [
        prepared["observations"][old_id]
    ]
    original["evidence"][0]["modality"] = "character_statement"
    prepared["observations"][old_id]["modality"] = "character_statement"
    reported = LedgerClaim.model_validate(
        compile_discovery(frozen)["changes"][0]["claim"]
    )
    assert evidence_counts(reported.evidence)["occurrences"] == 0


@pytest.mark.parametrize("confirmed", [True, False])
def test_same_condition_negative_case_preserves_the_prior_positive_event(confirmed):
    from copy import deepcopy
    from types import SimpleNamespace

    from modules.evolution.discovery import compile_discovery

    prepared, batch, first = prepared_occurrence()
    original = _compile_change(prepared, first, batch)["claim"]
    entry_id = str(uuid4())
    old_id = batch["current_observation_ids"][0]
    negative = deepcopy(prepared["observations"][old_id])
    quote = "甲同样紧张，这次双手平放，没有摸戒指。"
    negative.update(
        observation_id="negative-choice",
        predicate=quote,
        position={"scene_id": str(uuid4()), "scene_index": 5, "chapter_index": 6},
    )
    source = negative["evidence_quotes"][0]["source_ref"]
    source.update(draft_id="draft-6", chapter_identity="chapter:6", end_offset=len(quote))
    source["range_hash"] = SourceRevisionRef.compute_range_hash("a" * 64, 0, len(quote))
    negative["evidence_quotes"][0]["quote"] = quote
    prepared["observations"]["negative-choice"] = negative
    prepared["themes"][entry_id] = {"revision": 1, "claim": original}
    batch = {
        "current_observation_ids": ["negative-choice"],
        "historical_context": [
            {
                "theme": {
                    "entry_id": entry_id,
                    "evidence_observations": [prepared["observations"][old_id]],
                }
            }
        ],
    }
    prepared.update(batches=[batch], unsupported_batches=[], coverage={})
    change = {
        **first,
        "action": "exception",
        "target_entry_id": entry_id,
        "expected_revision": 1,
        "conditions": ["紧张"],
        "statement": "首次紧张时曾摸戒指，后来同样紧张却没有摸，不能认定每次都会摸。",
        "evidence": [
            {
                "observation_id": "negative-choice",
                "role": "exception_case",
                "purpose": "occurrence",
                "occurrence_kind": "event",
            }
        ],
    }
    verdict = {
        "change_index": 0,
        "verdict": "supported",
        "reason": "明确同条件负向实例，不否定首次动作存在。",
        "occurrence_observation_ids": [old_id] if confirmed else [],
        "exception_observation_ids": ["negative-choice"] if confirmed else [old_id],
        "counterevidence_observation_ids": [],
    }
    frozen = SimpleNamespace(
        attempt_id="attempt",
        source_manifest_hash="b" * 64,
        previous_receipt=None,
        payload={
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": {
                    "changes": [change],
                    "coverage": "inspected",
                    "coverage_note": "已查明确负向实例。",
                },
            },
            "scene_discovery_review_0": {"result": {"verdicts": [verdict]}},
        },
    )
    result = compile_discovery(frozen)
    if not confirmed:
        assert result["changes"] == []
        assert (
            result["pending"][0]["reason"]
            == "exception_or_counterevidence_not_independently_confirmed"
        )
        return
    claim = LedgerClaim.model_validate(result["changes"][0]["claim"])
    counts = evidence_counts(claim.evidence)
    assert counts["occurrences"] == 1
    assert counts["exception_occurrences"] == 1
    assert counts["counter_occurrences"] == 0
    assert claim.evidence[0].quote == original["evidence"][0]["quote"]
    assert claim.evidence[-1].quote == quote
    assert claim.evidence[-1].role == "exception_case"

    # A review's negative classification cannot leave a generator's positive count.
    change["action"] = "enhance"
    change["evidence"][0]["role"] = "support"
    conflict = compile_discovery(frozen)
    assert conflict["changes"] == []
    assert conflict["pending"][0]["reason"] == "review_evidence_role_conflict"

    change["action"] = "exception"
    change["evidence"][0]["role"] = "exception_case"
    verdict["occurrence_observation_ids"].append("negative-choice")
    assert (
        compile_discovery(frozen)["pending"][0]["reason"]
        == "review_evidence_role_conflict"
    )


@pytest.mark.parametrize(
    "case",
    [
        "certified",
        "missing",
        "uncertain",
        "wrong-anchor",
        "unbound-old",
        "empty-old",
        "unbound-new",
        "duplicate",
        "no-link",
    ],
)
def test_recall_link_needs_independent_two_sided_identity_review(case):
    from copy import deepcopy
    from types import SimpleNamespace

    from modules.evolution.discovery import compile_discovery

    prepared, batch, first = prepared_occurrence()
    original = _compile_change(prepared, first, batch)["claim"]
    old_id = batch["current_observation_ids"][0]
    anchor = original["evidence"][0]["occurrence_id"]
    current = deepcopy(prepared["observations"][old_id])
    current.update(observation_id="recall", modality="event_observed")
    quote = "甲回忆自己当时摸了戒指。"
    current["predicate"] = quote
    current["evidence_quotes"][0]["quote"] = quote
    current["position"].update(scene_id=str(uuid4()), scene_index=1, chapter_index=2)
    ref = current["evidence_quotes"][0]["source_ref"]
    ref.update(draft_id="draft-2", chapter_identity="chapter:2", end_offset=len(quote))
    ref["range_hash"] = SourceRevisionRef.compute_range_hash("a" * 64, 0, len(quote))
    prepared["observations"]["recall"] = current
    entry_id = str(uuid4())
    prepared["themes"][entry_id] = {"revision": 1, "claim": original}
    batch = {
        "current_observation_ids": ["recall"],
        "historical_context": [
            {
                "theme": {
                    "entry_id": entry_id,
                    "evidence_observations": list(prepared["observations"].values()),
                }
            }
        ],
    }
    prepared.update(batches=[batch], unsupported_batches=[], coverage={})
    change = {
        **first,
        "action": "enhance",
        "target_entry_id": entry_id,
        "expected_revision": 1,
        "evidence": [
            {
                "observation_id": "recall",
                "purpose": "occurrence",
                "occurrence_kind": "recall",
                "same_occurrence_as": None if case == "no-link" else anchor,
            }
        ],
    }
    certificate = {
        "observation_id": "recall",
        "occurrence_id": anchor,
        "verdict": "uncertain" if case == "uncertain" else "supported",
        "original_observation_ids": [old_id],
        "identity_observation_ids": ["recall"],
        "reason": "对照本项旧原动作与当前指认核定同一次实例。",
    }
    if case == "wrong-anchor":
        certificate["occurrence_id"] = "different-anchor"
    if case == "empty-old":
        certificate["original_observation_ids"] = []
    if case == "unbound-old":
        certificate["original_observation_ids"] = ["recall"]
    if case == "unbound-new":
        certificate["identity_observation_ids"].append("unbound")
    certificates = (
        [] if case == "missing" else [certificate] * (2 if case == "duplicate" else 1)
    )
    verdict = {
        "change_index": 0,
        "verdict": "supported",
        "reason": "动作本身有据。",
        "occurrence_observation_ids": ["recall"],
        "recall_identity_reviews": certificates,
    }
    frozen = SimpleNamespace(
        attempt_id="attempt",
        source_manifest_hash="b" * 64,
        previous_receipt=None,
        payload={
            "discovery_preparation": prepared,
            "scene_discovery_0": {
                "stage": "sampled",
                "result": {
                    "changes": [change],
                    "coverage": "inspected",
                    "coverage_note": "核回忆。",
                },
            },
            "scene_discovery_review_0": {"result": {"verdicts": [verdict]}},
        },
    )
    result = compile_discovery(frozen)
    if case in {"certified", "no-link"}:
        claim = LedgerClaim.model_validate(result["changes"][0]["claim"])
        assert evidence_counts(claim.evidence)["occurrences"] == 1
        assert evidence_counts(claim.evidence)["unknown_occurrences"] == int(
            case == "no-link"
        )
        if case == "no-link":
            # A narrator can report a recollection as observed: its unresolved
            # original event still must not become another physical occurrence.
            prepared["themes"][entry_id]["claim"] = claim.model_dump(mode="json")
            followup = deepcopy(current)
            identity_quote = "甲指出这段回忆指的是先前紧张时摸戒指的那一次。"
            followup.update(observation_id="followup", predicate=identity_quote)
            followup["evidence_quotes"][0]["quote"] = identity_quote
            followup_ref = followup["evidence_quotes"][0]["source_ref"]
            followup_ref.update(
                draft_id="draft-3",
                chapter_identity="chapter:3",
                end_offset=len(identity_quote),
            )
            followup_ref["range_hash"] = SourceRevisionRef.compute_range_hash(
                "a" * 64, 0, len(identity_quote)
            )
            prepared["observations"]["followup"] = followup
            batch["current_observation_ids"] = ["followup"]
            change["evidence"] = [{"observation_id": "followup", "purpose": "context"}]
            verdict.update(
                context_observation_ids=["followup"], recall_identity_reviews=[]
            )
            for origin in ("recall", None):
                basis = prepared["themes"][entry_id]["claim"]
                basis["evidence"][-1]["occurrence_origin"] = origin
                retained = LedgerClaim.model_validate(
                    compile_discovery(frozen)["changes"][0]["claim"]
                )
                assert evidence_counts(retained.evidence)["occurrences"] == 1
                assert evidence_counts(retained.evidence)["unknown_occurrences"] == 1
            basis["evidence"][-1]["occurrence_origin"] = "recall"
            change["evidence"].append(
                {
                    "observation_id": "recall",
                    "purpose": "occurrence",
                    "occurrence_kind": "event",
                }
            )
            retagged = compile_discovery(frozen)
            assert retagged["changes"] == []
            assert (
                retagged["pending"][0]["reason"]
                == "recalled_source_cannot_create_new_event"
            )
            change["evidence"].pop()
            # New identity evidence may explicitly resolve a historical recall
            # in the new head, with both sides reviewed; old head is untouched.
            change["evidence"].append(
                {
                    "observation_id": "recall",
                    "purpose": "occurrence",
                    "occurrence_kind": "recall",
                    "same_occurrence_as": anchor,
                }
            )
            verdict["recall_identity_reviews"] = [certificate]
            assert not compile_discovery(frozen)["changes"]  # no new identity source
            certificate["identity_observation_ids"].append("followup")
            linked = LedgerClaim.model_validate(
                compile_discovery(frozen)["changes"][0]["claim"]
            )
            assert evidence_counts(linked.evidence)["occurrences"] == 1
            assert evidence_counts(linked.evidence)["unknown_occurrences"] == 0
            assert basis["evidence"][-1]["occurrence_id"] is None
        if case == "certified":
            # Re-selecting an inherited certified use does not need a new certificate.
            prepared["themes"][entry_id]["claim"] = claim.model_dump(mode="json")
            verdict["recall_identity_reviews"] = []
            assert compile_discovery(frozen)["changes"]
    else:
        assert result["changes"] == []
        assert (
            result["pending"][0]["reason"]
            == "recall_identity_not_independently_confirmed"
        )
    assert original["evidence"][0]["occurrence_id"] == anchor
