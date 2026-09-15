"""治理状态投影与脱敏工具。

面向 API/前端的加性字段（knowledge_review / stage）在此统一拼装；
issue 展示按当前用户可见性脱敏：隐藏来源不外泄 key，隐藏事实短语被遮蔽。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from modules.evidence.compilation.knowledge.contracts import (
    AUDIT_VERDICT_NOT_CHECKED,
    AUDIT_VERDICT_PASS,
    AUDIT_VERDICT_UNVERIFIABLE,
    REVIEW_STATUS_BLOCKED,
    REVIEW_STATUS_CHECKING,
    REVIEW_STATUS_LEGACY_UNCHECKED,
    REVIEW_STATUS_PASSED,
    REVIEW_STATUS_UNVERIFIABLE,
    KnowledgeAuditReceipt,
    KnowledgeReviewProjection,
)

_REDACTED = "［已隐藏］"


def redact_hidden_phrases(
    text: str,
    phrases: Iterable[str],
    *,
    min_phrase_length: int = 4,
) -> str:
    """把隐藏事实短语从展示文本中遮蔽；确定性、无外部调用。"""
    result = str(text or "")
    for raw in phrases:
        phrase = " ".join(str(raw or "").split())
        if len(phrase) < min_phrase_length:
            continue
        if phrase in result:
            result = result.replace(phrase, _REDACTED)
    return result


def sanitize_audit_receipt(
    audit: KnowledgeAuditReceipt | None,
    *,
    visible_keys: Iterable[str],
    hidden_phrases: Iterable[str],
) -> KnowledgeReviewProjection:
    """把审查回执转成对当前用户安全的投影。"""
    if audit is None:
        return KnowledgeReviewProjection(status=REVIEW_STATUS_CHECKING)
    visible = set(visible_keys)
    issues: list[dict[str, str]] = []
    for finding in audit.findings:
        open_target = None
        if finding.source_key and finding.source_key in visible:
            open_target = finding.source_key
        issues.append(
            {
                "kind": finding.kind,
                "severity": finding.severity,
                "message": redact_hidden_phrases(finding.message, hidden_phrases),
                "open_target": open_target or "",
            }
        )
    return KnowledgeReviewProjection(
        status=_projection_status(audit),
        repaired=False,
        coverage=audit.coverage,
        issue_counts=audit.finding_counts(),
        issues=tuple(issues),
    )


def _projection_status(audit: KnowledgeAuditReceipt) -> str:
    if audit.verdict == AUDIT_VERDICT_PASS:
        return REVIEW_STATUS_PASSED
    if audit.verdict == AUDIT_VERDICT_UNVERIFIABLE:
        return REVIEW_STATUS_UNVERIFIABLE
    if audit.verdict == AUDIT_VERDICT_NOT_CHECKED:
        return REVIEW_STATUS_BLOCKED
    return REVIEW_STATUS_BLOCKED


def knowledge_review_payload(
    *,
    audit: KnowledgeAuditReceipt | None,
    repaired: bool = False,
    visible_keys: Sequence[str] = (),
    hidden_phrases: Sequence[str] = (),
) -> dict:
    """API 响应的加性 knowledge_review 字段。"""
    projection = sanitize_audit_receipt(
        audit,
        visible_keys=visible_keys,
        hidden_phrases=hidden_phrases,
    )
    payload = projection.to_dict()
    payload["repaired"] = bool(repaired)
    return payload


def legacy_unchecked_payload(reason: str = "任务创建于知识治理之前") -> dict:
    """旧在途任务/旧待采用资产的兼容投影。"""
    projection = KnowledgeReviewProjection(
        status=REVIEW_STATUS_LEGACY_UNCHECKED,
    )
    payload = projection.to_dict()
    payload["reason"] = reason
    return payload


def require_knowledge_review_for_adoption(
    payload: dict[str, Any],
    *,
    label: str,
    error_type: type[Exception] | None = None,
) -> None:
    """Fail closed when an AI-authored artifact lacks a passed review receipt."""
    from core.errors import ValidationError

    review = payload.get("knowledge_review")
    if str((review or {}).get("status") or "") == "passed":
        return
    exception = error_type or ValidationError
    if review is None:
        raise exception(
            f"{label}由旧版本 AI 生成，未经知识治理审查；请重新生成后再采用。"
        )
    detail = "已返修仍失败" if review.get("repaired") else "存在阻断问题"
    raise exception(
        f"{label}未通过知识审查（{detail}），不能采用；可在补充资料后重新生成。"
    )


def governance_stage_payload(stage: str, **extra: object) -> dict:
    """长任务 stage 投影：collecting_context/directing/generating/reviewing/repairing。"""
    from modules.evidence.compilation.knowledge.contracts import GOVERNANCE_STAGES

    if stage not in GOVERNANCE_STAGES:
        raise ValueError(f"unknown governance stage: {stage}")
    return {"stage": stage, **extra}
