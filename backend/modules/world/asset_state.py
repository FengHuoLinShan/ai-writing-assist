"""Author-facing lifecycle projection for world-owned assets.

Raw persistence states remain part of the compatibility interface.  This
module owns the smaller author-facing projection so API callers do not have to
reimplement status vocabulary mappings.
"""

from __future__ import annotations

from typing import Any

ACTIVE_DISPLAY_STATUSES = frozenset({"active", "canonical", "confirmed", "published"})
REVIEW_DISPLAY_STATUSES = frozenset(
    {
        "candidate",
        "conflicted",
        "draft",
        "needs_review",
        "pending",
        "processing",
        "proposal",
    }
)
ARCHIVED_DISPLAY_STATUSES = frozenset(
    {"accepted", "deprecated", "ignored", "merged", "rejected", "rolled_back"}
)

DISPLAY_STATE_STATUSES: dict[str, frozenset[str]] = {
    "active": ACTIVE_DISPLAY_STATUSES,
    "review": REVIEW_DISPLAY_STATUSES,
    "archived": ARCHIVED_DISPLAY_STATUSES,
}


def display_state_for_status(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in ACTIVE_DISPLAY_STATUSES:
        return "active"
    if normalized in ARCHIVED_DISPLAY_STATUSES:
        return "archived"
    return "review"


def statuses_for_display_state(display_state: str | None) -> frozenset[str] | None:
    if display_state is None:
        return None
    return DISPLAY_STATE_STATUSES.get(display_state)


def project_entity_state(
    *,
    status: str | None,
    content_json: dict[str, Any] | None,
    created_by: str | None,
) -> dict[str, Any]:
    meta = dict((content_json or {}).get("_meta") or {})
    attention_reasons = _attention_reasons(
        status=status,
        needs_review=meta.get("needs_review"),
        confidence=meta.get("confidence"),
    )
    return {
        "display_state": display_state_for_status(status),
        "source": meta.get("source") or created_by,
        "attention_reasons": attention_reasons,
        "suggested_action": meta.get("suggested_action"),
    }


def project_relation_state(
    *,
    status: str | None,
    review_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = dict(review_meta or {})
    attention_reasons = _attention_reasons(
        status=status,
        needs_review=meta.get("needs_review"),
        confidence=meta.get("confidence"),
    )
    return {
        "display_state": display_state_for_status(status),
        "source": meta.get("source"),
        "attention_reasons": attention_reasons,
        "suggested_action": meta.get("suggested_action")
        or ("adopt" if status in {"candidate", "conflicted"} else None),
    }


def project_alias_state(
    *,
    status: str | None,
    source: str | None,
    needs_review: bool | None,
    confidence: float | None,
    owner_status: str | None = None,
) -> dict[str, Any]:
    normalized_status = status or "canonical"
    display_state = display_state_for_status(normalized_status)
    owner_display_state = display_state_for_status(owner_status)
    if owner_status is not None and owner_display_state == "archived":
        display_state = "archived"
    elif owner_status is not None and owner_display_state == "review":
        display_state = "review"
    return {
        "display_state": display_state,
        "source": source,
        "attention_reasons": _attention_reasons(
            status=normalized_status,
            needs_review=needs_review,
            confidence=confidence,
        ),
        "suggested_action": "adopt" if normalized_status == "candidate" else None,
    }


def project_suggestion_state(
    *,
    status: str | None,
    source_module: str | None,
    risk_level: str | None,
    payload_json: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(payload_json or {})
    attention_reasons: list[str] = []
    if risk_level in {"high", "critical"}:
        attention_reasons.append("high_risk")
    return {
        "display_state": (
            "review" if status in {"pending", "processing"} else "archived"
        ),
        "source": source_module,
        "attention_reasons": attention_reasons,
        "suggested_action": payload.get("suggested_action") or "adopt",
    }


def project_map_state(
    *,
    status: str | None,
    source_ref: dict[str, Any] | None,
    confidence: float | None,
) -> dict[str, Any]:
    source = dict(source_ref or {}).get("source")
    return {
        "display_state": display_state_for_status(status),
        "source": source,
        "attention_reasons": _attention_reasons(
            status=status,
            confidence=confidence,
        ),
        "suggested_action": ("adopt" if status in {"candidate", "conflicted"} else None),
    }


def _attention_reasons(
    *,
    status: str | None,
    needs_review: Any = None,
    confidence: Any = None,
) -> list[str]:
    reasons: list[str] = []
    if status == "conflicted":
        reasons.append("conflict")
    if needs_review is True:
        reasons.append("needs_review")
    try:
        if confidence is not None and float(confidence) < 0.5:
            reasons.append("low_confidence")
    except (TypeError, ValueError):
        pass
    return list(dict.fromkeys(reasons))
