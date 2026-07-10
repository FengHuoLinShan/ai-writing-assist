"""Deep-import authorization snapshots and author-facing asset outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

DEFAULT_ADOPTION_POLICY = "user_authorized_pipeline"
SUPPORTED_ADOPTION_POLICIES = frozenset({DEFAULT_ADOPTION_POLICY})

ASSET_KINDS = ("scene", "entity", "relation", "alias", "structure")
OUTCOME_KEYS = ("adopted", "review", "not_adopted")


def build_authorization_snapshot(
    *,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    adoption_policy: str,
    authorization_confirmed: bool,
    stage: str | None = None,
) -> dict[str, Any]:
    if adoption_policy not in SUPPORTED_ADOPTION_POLICIES:
        raise ValueError(f"unsupported adoption_policy: {adoption_policy}")
    if authorization_confirmed is not True:
        raise ValueError("authorization_confirmed must be true")
    return {
        "adoption_policy": adoption_policy,
        "authorization_confirmed": True,
        "authorized_at": datetime.now(UTC).isoformat(),
        "scope": {
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "stage": stage,
        },
        "auto_adopt": [
            "scene_without_review_flags",
            "working_structure_asset",
        ],
        "review": [
            "scene_needs_review",
            "entity_candidate",
            "relation_candidate",
            "alias_candidate",
            "uncertain_structure",
        ],
        "not_adopted": ["ignored", "temporary_only", "provenance_conflict"],
        "provenance_required": [
            "source",
            "workflow_id",
            "scene_or_chapter_evidence",
        ],
        "rollback": {
            "supported": True,
            "mode": "workflow_owned_soft_deprecate",
        },
    }


def empty_asset_summary() -> dict[str, Any]:
    by_kind = {
        kind: {outcome: 0 for outcome in OUTCOME_KEYS}
        for kind in ASSET_KINDS
    }
    return {
        **{outcome: 0 for outcome in OUTCOME_KEYS},
        "by_kind": by_kind,
    }


def build_asset_summary(quality_stats: dict[str, Any] | None) -> dict[str, Any]:
    """Build mutually exclusive adopted/review/not-adopted totals from phase stats."""
    stats = quality_stats or {}
    scene = _dict(stats.get("scene_commit"))
    phase2 = _dict(stats.get("phase2"))
    phase3 = _dict(stats.get("phase3"))
    phase2_dedup = _dict(phase2.get("phase2_dedup_counts"))
    structure_dedup = _dict(phase3.get("structure_dedup"))

    temporary_entities = _count(phase2.get("phase2_temporary_only"))
    created_entities = _count(phase2.get("total_created"))
    structure_total = sum(
        _count(phase3.get(key))
        for key in (
            "total_threads",
            "total_arcs",
            "total_foreshadowing",
            "total_reveals",
        )
    )
    structure_review_assets, structure_not_adopted = _structure_asset_outcomes(
        structure_dedup,
        phase3=phase3,
        structure_total=structure_total,
    )
    by_kind = {
        "scene": {
            "adopted": _count(
                scene.get("adopted_count", scene.get("created_count"))
            ),
            "review": _count(scene.get("review_count")),
            "not_adopted": _count(scene.get("conflict_count")),
        },
        "entity": {
            "adopted": _count(phase2_dedup.get("auto_merged")),
            "review": max(0, created_entities - temporary_entities),
            "not_adopted": _count(phase2.get("phase2_ignored"))
            + temporary_entities,
        },
        "relation": {
            "adopted": 0,
            "review": _count(phase2.get("total_relations")),
            "not_adopted": 0,
        },
        "alias": {
            "adopted": 0,
            "review": _count(phase2.get("total_aliases")),
            "not_adopted": 0,
        },
        "structure": {
            "adopted": max(
                0, structure_total - structure_not_adopted - structure_review_assets
            ),
            "review": structure_review_assets,
            "not_adopted": structure_not_adopted,
        },
    }
    return {
        **{
            outcome: sum(values[outcome] for values in by_kind.values())
            for outcome in OUTCOME_KEYS
        },
        "by_kind": by_kind,
    }


def _structure_asset_outcomes(
    structure_dedup: dict[str, Any],
    *,
    phase3: dict[str, Any],
    structure_total: int,
) -> tuple[int, int]:
    """Return mutually exclusive (review, not-adopted) workflow asset counts."""
    if "current_workflow_asset_outcomes" in structure_dedup:
        outcomes = _dict(structure_dedup.get("current_workflow_asset_outcomes"))
        review_ids = _string_set(outcomes.get("review_asset_ids"))
        review_ids.update(_string_set(phase3.get("review_asset_ids")))
        review_ids.update(_string_set(phase3.get("uncertain_asset_ids")))
        not_adopted_ids = _string_set(outcomes.get("not_adopted_asset_ids"))
        if review_ids or not_adopted_ids:
            review_ids.difference_update(not_adopted_ids)
            review = len(review_ids)
            not_adopted = len(not_adopted_ids)
        else:
            review = _count(outcomes.get("review")) + _count(
                phase3.get("review_asset_count")
            )
            not_adopted = _count(outcomes.get("not_adopted"))
    else:
        # Legacy tasks only recorded suggestion-pair counts. Keep their best-effort
        # display bounded while new tasks use unique workflow asset counts above.
        review = _count(structure_dedup.get("skipped_external_asset"))
        review += _count(phase3.get("review_asset_count"))
        not_adopted = _count(structure_dedup.get("auto_applied"))

    not_adopted = min(structure_total, not_adopted)
    review = min(max(0, structure_total - not_adopted), review)
    return review, not_adopted


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
