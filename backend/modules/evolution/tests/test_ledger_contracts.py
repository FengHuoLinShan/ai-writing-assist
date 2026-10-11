"""Freeze author/claim/source axes and separate events from repeated citations."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from modules.evolution.contracts import SourceRevisionRef, StoryPosition
from modules.evolution.ledger_contracts import (
    DiscoveryChange,
    LedgerDecision,
    LedgerEvidence,
    LedgerTarget,
    evidence_counts,
)


def evidence(observation="first", **kwargs):
    values = {
        "observation_id": observation,
        "position": StoryPosition(scene_index=0),
        "modality": "event_observed",
        "quote": "甲摸戒指。",
        "source_ref": SourceRevisionRef(
            novel_id="synthetic",
            source_kind="chapter_draft",
            draft_id="v1",
            content_hash="a" * 64,
            chapter_identity="chapter-1",
            start_offset=0,
            end_offset=5,
            range_hash=SourceRevisionRef.compute_range_hash("a" * 64, 0, 5),
            source_revision=1,
            segmentation_version=1,
            source_visibility="working",
        ),
        "occurrence_id": "ring-event-1",
        "purpose": "occurrence",
        "occurrence_kind": "event",
    }
    return LedgerEvidence(**{**values, **kwargs})


def test_recalled_event_and_reextraction_do_not_increase_occurrences():
    original = evidence()
    recall = evidence(
        "recalled", modality="character_statement", occurrence_kind="recall"
    )
    unknown = evidence("ambiguous", occurrence_id=None, occurrence_kind="unknown")
    assert evidence_counts([original, original, recall, unknown]) == {
        "occurrences": 1,
        "counter_occurrences": 0,
        "exception_occurrences": 0,
        "observations": 3,
        "sources": 1,
        "unknown_occurrences": 1,
    }


def test_certified_observation_is_not_also_counted_as_an_unknown_occurrence():
    qualified = evidence("same")
    old_unknown = evidence("same", occurrence_kind="unknown", occurrence_id=None)
    other_unknown = evidence("other", occurrence_kind="unknown", occurrence_id=None)
    counts = evidence_counts([qualified, old_unknown, other_unknown])
    assert counts["occurrences"] == 1
    assert counts["unknown_occurrences"] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"modality": "belief"},
        {"occurrence_id": None},
    ],
)
def test_unproven_occurrence_is_rejected(patch):
    with pytest.raises(ValidationError):
        evidence(**patch)


def test_topic_revision_and_explicit_counterevidence_are_required():
    values = {
        "action": "new",
        "category": "conditional_behavior",
        "label": "紧张时摸戒指",
        "statement": "甲在这次紧张时摸了戒指。",
        "confidence": 0.5,
        "evidence": [{"observation_id": "first"}],
    }
    assert DiscoveryChange(**values).modality == "hypothesis"
    with pytest.raises(ValidationError, match="exact existing revision"):
        DiscoveryChange(**{**values, "action": "narrow"})
    with pytest.raises(ValidationError, match="explicit evidence"):
        DiscoveryChange(
            **{
                **values,
                "action": "exception",
                "target_entry_id": uuid4(),
                "expected_revision": 1,
            }
        )


def test_author_correction_scope_does_not_silently_expand():
    decision = {
        "operation_id": uuid4(),
        "expected_revision": 1,
        "decision": "corrected",
        "corrected_statement": "只适用于此次试探。",
    }
    assert LedgerDecision(**decision).scope == "instance"
    with pytest.raises(ValidationError, match="explicit confirmation"):
        LedgerDecision(**{**decision, "scope": "theme"})
    assert (
        LedgerDecision(
            **{**decision, "scope": "theme", "confirmed_scope_expansion": True}
        ).scope
        == "theme"
    )


def test_cross_domain_target_identity_cannot_be_reassigned():
    with pytest.raises(ValidationError, match="original domain"):
        LedgerTarget(
            domain="story", kind="entity", target_id=uuid4(), version_fingerprint="v1"
        )
