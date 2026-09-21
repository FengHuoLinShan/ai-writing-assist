"""E01 契约层测试：来源、观察、身份解析、类型化操作与回执游标纪律。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.evolution.contracts import (
    CommittedPrefix,
    CoverageContract,
    EvidenceQuote,
    EvolutionReceipt,
    IdentityCandidate,
    IdentityResolution,
    MentionRef,
    ObservationEnvelope,
    SourceRevisionRef,
    StoryPosition,
    TypedStateOperation,
    operation_changes_state,
)

NOVEL = "0e0e0e0e-0e0e-4e0e-8e0e-0e0e0e0e0e0e"
CHAPTER = "1a1a1a1a-1a1a-4a1a-8a1a-1a1a1a1a1a1a"
HASH_A = "a" * 64
HASH_B = "b" * 64


def _source(
    *,
    content_hash: str = HASH_A,
    draft_id: str = "draft-1",
    start: int = 0,
    end: int = 120,
    revision: int = 3,
) -> SourceRevisionRef:
    return SourceRevisionRef(
        novel_id=NOVEL,
        source_kind="chapter_draft",
        draft_id=draft_id,
        content_hash=content_hash,
        chapter_identity=CHAPTER,
        start_offset=start,
        end_offset=end,
        range_hash=SourceRevisionRef.compute_range_hash(content_hash, start, end),
        source_revision=revision,
        segmentation_version=1,
        source_visibility="working",
    )


def _quote(source_ref: SourceRevisionRef) -> EvidenceQuote:
    return EvidenceQuote(quote="青竹从袖中取出铜钥匙", source_ref=source_ref)


def _observation(
    *,
    source_ref: SourceRevisionRef | None = None,
    predicate: str = "青竹在Scene中取出铜钥匙",
    modality: str = "event_observed",
    contract_version: int = 1,
    run_id: str = "run-1",
) -> ObservationEnvelope:
    return ObservationEnvelope.with_stable_id(
        source_ref=source_ref or _source(),
        observer_contract_version=contract_version,
        predicate_or_description=predicate,
        modality=modality,  # type: ignore[arg-type]
        learned_at_position=StoryPosition(scene_index=0, chapter_index=1),
        evidence_quotes=[_quote(source_ref or _source())],
        producer_run_id=run_id,
        input_manifest_hash="c" * 64,
    )


# ---------------------------------------------------------------------------
# 来源
# ---------------------------------------------------------------------------


def test_range_hash_is_deterministic_and_offset_sensitive() -> None:
    first = _source()
    second = _source()
    assert first.range_hash == second.range_hash
    shifted = _source(start=1, end=121)
    assert shifted.range_hash != first.range_hash


def test_range_hash_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="range_hash"):
        SourceRevisionRef(
            novel_id=NOVEL,
            source_kind="chapter_draft",
            draft_id="draft-1",
            content_hash=HASH_A,
            chapter_identity=CHAPTER,
            start_offset=0,
            end_offset=10,
            range_hash=HASH_B,
            source_revision=1,
            segmentation_version=1,
            source_visibility="working",
        )


def test_same_length_edit_changes_source_identity() -> None:
    """同字数替换改变 content_hash，来源身份可识别变化。"""
    assert _source().content_hash != _source(content_hash=HASH_B).content_hash
    assert _source() != _source(content_hash=HASH_B)


# ---------------------------------------------------------------------------
# 提及与观察
# ---------------------------------------------------------------------------


def test_unresolved_mention_requires_reason_and_refuses_fake_uuid() -> None:
    with pytest.raises(ValidationError, match="unresolved_reason"):
        MentionRef(mention_id="m-linzhou-1", surface="林舟")

    resolved = MentionRef(
        mention_id="m-linzhou-1",
        surface="林舟",
        resolved_entity_id="2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b",
    )
    assert resolved.resolved_entity_id is not None


def test_observation_requires_evidence_quote() -> None:
    base = _observation()
    data = base.model_dump()
    data["evidence_quotes"] = []
    with pytest.raises(ValidationError):
        ObservationEnvelope(**data)


def test_observation_modality_statement_does_not_imply_fact() -> None:
    statement = _observation(
        predicate="角色自称已杀死信使",
        modality="character_statement",
    )
    assert statement.modality == "character_statement"
    assert statement.modality != "event_observed"


# ---------------------------------------------------------------------------
# 身份解析
# ---------------------------------------------------------------------------


def test_identity_reuse_requires_candidate_evidence() -> None:
    mention = MentionRef(
        mention_id="m-linzhou-1",
        surface="林舟",
        resolved_entity_id="2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b",
    )
    resolution = IdentityResolution(
        mention_ref=mention,
        outcome="reuse",
        resolved_entity_id="2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b",
        candidates=[
            IdentityCandidate(
                entity_id="2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b",
                evidence="同名且持有相同信物",
            )
        ],
        rationale="同名同类型，证据唯一",
    )
    assert resolution.outcome == "reuse"

    with pytest.raises(ValidationError, match="candidates"):
        IdentityResolution(
            mention_ref=mention,
            outcome="ambiguous",
            candidates=[],
            rationale="无法判定",
        )


def test_identity_new_candidate_must_not_bind_existing_entity() -> None:
    mention = MentionRef(
        mention_id="m-baishi-1",
        surface="白石城主",
        unresolved_reason="首次出现，尚未解析归属",
    )
    with pytest.raises(ValidationError):
        IdentityResolution(
            mention_ref=mention,
            outcome="new_candidate",
            resolved_entity_id="2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b",
            rationale="首次出现",
        )


# ---------------------------------------------------------------------------
# 类型化状态操作
# ---------------------------------------------------------------------------


def _operation(**overrides: object) -> TypedStateOperation:
    payload: dict = {
        "schema_version": 1,
        "operation_kind": "location.observe",
        "subject_ref": "2b2b2b2b-2b2b-4b2b-8b2b-2b2b2b2b2b2b",
        "value": {"location": "白石城"},
        "story_position": StoryPosition(scene_index=0, chapter_index=1),
        "source_observation_ids": ["o" * 64],
        "derivation_version": 1,
    }
    payload.update(overrides)
    return TypedStateOperation(**payload)


def test_location_observe_vs_move_semantics_split() -> None:
    observe = _operation(operation_kind="location.observe")
    move = _operation(operation_kind="location.move")
    assert operation_changes_state(observe.operation_kind)
    assert operation_changes_state(move.operation_kind)
    # 前值未知允许为空（assert 语义），不得伪造 before。
    assert move.before_precondition is None


def test_documentary_assertion_does_not_change_state() -> None:
    assert not operation_changes_state("documentary_assertion")


def test_knowledge_operation_requires_subject() -> None:
    with pytest.raises(ValidationError, match="knowledge_subject"):
        _operation(operation_kind="knowledge.learn")


def test_relation_operation_requires_field() -> None:
    with pytest.raises(ValidationError, match="relation_or_field"):
        _operation(operation_kind="relation.establish")


def test_state_operation_requires_source_observations() -> None:
    with pytest.raises(ValidationError):
        _operation(source_observation_ids=[])


# ---------------------------------------------------------------------------
# 回执与游标纪律
# ---------------------------------------------------------------------------


def _receipt(
    *,
    execution_status: str = "succeeded",
    committed_prefix: CommittedPrefix | None = None,
    previous: CommittedPrefix | None = None,
) -> EvolutionReceipt:
    return EvolutionReceipt(
        run_id="run-1",
        attempt_id="attempt-1",
        owner_epoch=1,
        producer_version="evolution/0.1",
        source_manifest_hash="d" * 64,
        input_state_receipt="e" * 64,
        previous_receipt=None if previous is None else "f" * 64,
        previous_committed_prefix=previous,
        committed_prefix=committed_prefix
        or CommittedPrefix(through_scene_index=0, through_source_revision=3),
        execution_status=execution_status,  # type: ignore[arg-type]
        outcome_status="committed",
    )


def test_receipt_forbids_cursor_advance_on_failure() -> None:
    previous = CommittedPrefix(through_scene_index=0, through_source_revision=2)
    ok = _receipt(previous=previous)
    assert ok.committed_prefix.through_source_revision == 3

    with pytest.raises(ValidationError, match="committed_prefix"):
        _receipt(execution_status="failed", previous=previous)

    # 失败但游标原地不动是合法回执。
    unchanged = _receipt(
        execution_status="failed",
        committed_prefix=CommittedPrefix(
            through_scene_index=0, through_source_revision=2
        ),
        previous=previous,
    )
    assert unchanged.committed_prefix == previous


def test_unknown_billing_also_blocks_advance() -> None:
    previous = CommittedPrefix(through_scene_index=1, through_source_revision=4)
    with pytest.raises(ValidationError):
        _receipt(execution_status="unknown_billing", previous=previous)


def test_coverage_counts_each_status_separately() -> None:
    coverage = CoverageContract(inspected=["s0", "s1"], unknown=["s2"], excluded=["s3"])
    assert coverage.total_claimed() == 4
    assert coverage.not_run == []
