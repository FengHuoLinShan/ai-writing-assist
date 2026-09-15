"""知识治理契约测试：序列化、指纹、版本容忍与导演规划校验。"""

from __future__ import annotations

import pytest

from modules.evidence.compilation.knowledge.contracts import (
    KNOWLEDGE_POLICY_VERSION,
    KnowledgeAuditFinding,
    KnowledgeAuditReceipt,
    KnowledgeContractError,
    KnowledgeContractVersionError,
    KnowledgeDimensionCoverage,
    KnowledgeDirectorDisposition,
    KnowledgeDirectorPlan,
    KnowledgeScopeReceipt,
    KnowledgeSourceEntry,
    KnowledgeSubject,
    knowledge_canonical_hash,
)


def _entry(key: str, **overrides) -> KnowledgeSourceEntry:
    payload = {
        "source_key": key,
        "source_type": "world_entity",
        "source_id": key.split(":")[-1],
        "content_hash": knowledge_canonical_hash(key),
        "label": "示例对象",
        "dimensions": ("world_entities",),
        "depends_on": (),
    }
    payload.update(overrides)
    return KnowledgeSourceEntry(**payload)


def _receipt(**overrides) -> KnowledgeScopeReceipt:
    payload = {
        "policy_version": KNOWLEDGE_POLICY_VERSION,
        "capability": "writing.generate",
        "novel_id": "novel-1",
        "subject": KnowledgeSubject(
            subject_type="character",
            character_id="char-1",
            cutoff_chapter=3,
        ),
        "included": (
            _entry("world_entity:a"),
            _entry("world_entity:b"),
            _entry("draft:ch3"),
        ),
        "excluded": (_entry("world_entity:hidden"),),
        "omitted": (),
        "coverage": (
            KnowledgeDimensionCoverage(
                dimension="world_entities",
                covered_by=("world_entity:a", "world_entity:b"),
            ),
            KnowledgeDimensionCoverage(
                dimension="prior_prose",
                covered_by=("draft:ch3",),
            ),
        ),
        "authority_fingerprint": "auth-fp",
        "generator_fingerprint": "gen-fp",
        "scope_complete": True,
    }
    payload.update(overrides)
    return KnowledgeScopeReceipt(**payload)


def test_scope_receipt_round_trip() -> None:
    receipt = _receipt()
    restored = KnowledgeScopeReceipt.from_dict(receipt.to_dict())
    assert restored == receipt
    assert restored.source_keys() == ("world_entity:a", "world_entity:b", "draft:ch3")
    assert restored.entry("draft:ch3") is not None
    assert restored.dimension_coverage("prior_prose") is not None
    assert restored.receipt_fingerprint() == receipt.receipt_fingerprint()


def test_scope_receipt_fingerprint_drifts_on_any_change() -> None:
    base = _receipt()
    assert base.receipt_fingerprint() == _receipt().receipt_fingerprint()

    changed_subject = _receipt(
        subject=KnowledgeSubject(subject_type="character", character_id="char-2")
    )
    changed_coverage = _receipt(
        coverage=base.coverage[:1],
    )
    changed_hash = _receipt(
        included=(
            KnowledgeSourceEntry(
                source_key="draft:ch3",
                source_type="draft",
                source_id="ch3",
                content_hash="different",
            ),
        )
    )
    for variant in (changed_subject, changed_coverage, changed_hash):
        assert variant.receipt_fingerprint() != base.receipt_fingerprint()


def test_scope_receipt_omission_blocks_completeness() -> None:
    omitted_entry = _receipt(
        omitted=(_entry("memory:m1"),),
        scope_complete=False,
    )
    assert omitted_entry.has_omissions()
    covered_only = _receipt(
        coverage=(
            KnowledgeDimensionCoverage(
                dimension="world_entities",
                omitted=True,
                omission_reason="预算不足",
            ),
        )
    )
    assert covered_only.has_omissions()
    assert not _receipt().has_omissions()


def test_scope_receipt_rejects_future_version() -> None:
    payload = _receipt().to_dict()
    payload["policy_version"] = KNOWLEDGE_POLICY_VERSION + 1
    with pytest.raises(KnowledgeContractVersionError):
        KnowledgeScopeReceipt.from_dict(payload)


def test_director_plan_validates_receipt_exactly_once() -> None:
    receipt = _receipt()
    plan = KnowledgeDirectorPlan(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=(
            KnowledgeDirectorDisposition(
                source_key="world_entity:a",
                disposition="required_for_generation",
            ),
            KnowledgeDirectorDisposition(
                source_key="world_entity:b",
                disposition="allowed_for_generation",
            ),
            KnowledgeDirectorDisposition(
                source_key="draft:ch3",
                disposition="director_audit_only",
            ),
        ),
    )
    plan.validate_against_receipt(receipt)
    assert plan.disposition_for("draft:ch3").disposition == "director_audit_only"

    missing = KnowledgeDirectorPlan(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=plan.dispositions[:2],
    )
    with pytest.raises(KnowledgeContractError, match="missing disposition"):
        missing.validate_against_receipt(receipt)

    unknown = KnowledgeDirectorPlan(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=plan.dispositions
        + (
            KnowledgeDirectorDisposition(
                source_key="world_entity:ghost",
                disposition="forbidden",
            ),
        ),
    )
    with pytest.raises(KnowledgeContractError, match="unknown source key"):
        unknown.validate_against_receipt(receipt)

    duplicate = KnowledgeDirectorPlan(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=plan.dispositions
        + (
            KnowledgeDirectorDisposition(
                source_key="world_entity:a",
                disposition="forbidden",
            ),
        ),
    )
    with pytest.raises(KnowledgeContractError, match="duplicate disposition"):
        duplicate.validate_against_receipt(receipt)

    bad_disposition = KnowledgeDirectorPlan(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint=receipt.receipt_fingerprint(),
        dispositions=(
            KnowledgeDirectorDisposition(
                source_key="world_entity:a",
                disposition="leak_everything",
            ),
            KnowledgeDirectorDisposition(
                source_key="world_entity:b",
                disposition="allowed_for_generation",
            ),
            KnowledgeDirectorDisposition(
                source_key="draft:ch3",
                disposition="director_audit_only",
            ),
        ),
    )
    with pytest.raises(KnowledgeContractError, match="unknown disposition"):
        bad_disposition.validate_against_receipt(receipt)


def test_director_plan_round_trip_and_fingerprint() -> None:
    plan = KnowledgeDirectorPlan(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint="fp",
        dispositions=(
            KnowledgeDirectorDisposition(
                source_key="a",
                disposition="required_for_generation",
                reason="主角设定",
            ),
        ),
        notes=("备注",),
    )
    restored = KnowledgeDirectorPlan.from_dict(plan.to_dict())
    assert restored == plan
    assert restored.plan_fingerprint() == plan.plan_fingerprint()


def test_audit_receipt_blocking_and_counts() -> None:
    receipt = KnowledgeAuditReceipt(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint="scope-fp",
        plan_fingerprint="plan-fp",
        output_hash=knowledge_canonical_hash("生成正文"),
        verdict="blocked",
        findings=(
            KnowledgeAuditFinding(
                kind="premature_reveal",
                severity="blocker",
                message="提前揭示了读者不应知道的事实",
                excerpt="那段正文",
            ),
            KnowledgeAuditFinding(
                kind="unsupported_fact",
                severity="major",
                message="出现了资料中没有的地名",
            ),
            KnowledgeAuditFinding(
                kind="irrelevant_content",
                severity="minor",
                message="与任务无关的闲谈",
            ),
        ),
    )
    assert len(receipt.blocking_findings()) == 2
    counts = receipt.finding_counts()
    assert counts["premature_reveal"] == 1
    assert counts["irrelevant_content"] == 1
    assert receipt.audit_fingerprint() == (
        KnowledgeAuditReceipt.from_dict(receipt.to_dict()).audit_fingerprint()
    )
    # 输出 hash 变化必须改变回执指纹（绑定输出的核心语义）
    drifted = KnowledgeAuditReceipt(
        policy_version=KNOWLEDGE_POLICY_VERSION,
        capability="writing.generate",
        receipt_fingerprint="scope-fp",
        plan_fingerprint="plan-fp",
        output_hash=knowledge_canonical_hash("被替换的正文"),
        verdict="blocked",
        findings=receipt.findings,
    )
    assert drifted.audit_fingerprint() != receipt.audit_fingerprint()
