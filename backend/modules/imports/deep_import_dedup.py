"""Phase 3 structure-dedup review for deep import workflows."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic


class StructureReviewAgent:
    """Run outline structure dedup suggestions after Phase 3 writes."""

    async def review(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        from modules.outline import facade as outline_facade

        try:
            suggestion_result = await outline_facade.suggest_structure_dedup(
                db,
                novel_id,
                asset_types=[
                    "plot_thread",
                    "outline_arc",
                    "foreshadowing_plan",
                    "reveal_plan",
                ],
                max_suggestions=40,
            )
        except Exception as exc:
            return {
                "checked": 0,
                "suggestions_recorded": 0,
                "auto_applied": 0,
                "skipped_external_asset": 0,
                "current_workflow_asset_outcomes": {
                    "review": 0,
                    "not_adopted": 0,
                    "affected": 0,
                    "review_asset_ids": [],
                    "not_adopted_asset_ids": [],
                },
                "degraded": 1,
                "error_kind": "structure_dedup_failed",
                "error_message": redact_diagnostic(exc, limit=240),
                "suggestions": [],
            }

        suggestions = [
            item
            for item in suggestion_result.get("suggestions", [])
            if isinstance(item, dict)
        ]
        auto_apply = [
            item
            for item in suggestions
            if _same_workflow_suggestion(item, workflow_id)
            and float(item.get("confidence") or 0) >= 0.96
            and item.get("action") in {"merge", "deprecate_duplicate"}
        ]
        skipped_external = len(suggestions) - len(auto_apply)
        apply_result: dict[str, Any] = {"applied": 0, "skipped": 0, "warnings": []}
        if auto_apply:
            apply_result = await outline_facade.apply_structure_dedup(
                db,
                novel_id,
                confirmed=True,
                suggestions=auto_apply,
            )
        workflow_asset_outcomes = _current_workflow_asset_outcomes(
            suggestions,
            auto_apply=auto_apply,
            apply_result=apply_result,
            workflow_id=workflow_id,
        )
        return {
            "checked": int(suggestion_result.get("total_assets_scanned", 0) or 0),
            "suggestions_recorded": len(suggestions),
            "auto_applied": int(apply_result.get("applied", 0) or 0),
            "skipped_external_asset": skipped_external,
            "current_workflow_asset_outcomes": workflow_asset_outcomes,
            "degraded": 0,
            "warnings": apply_result.get("warnings") or [],
            "suggestions": [
                _safe_structure_suggestion(item) for item in suggestions[:20]
            ],
        }
def _same_workflow_suggestion(item: dict[str, Any], workflow_id: str | None) -> bool:
    if not workflow_id:
        return False
    return (
        item.get("source_workflow_id") == workflow_id
        and item.get("target_workflow_id") == workflow_id
    )


def _current_workflow_asset_outcomes(
    suggestions: list[dict[str, Any]],
    *,
    auto_apply: list[dict[str, Any]],
    apply_result: dict[str, Any],
    workflow_id: str | None,
) -> dict[str, Any]:
    """Count unique current-workflow assets, never suggestion pairs."""
    if not workflow_id:
        return {
            "review": 0,
            "not_adopted": 0,
            "affected": 0,
            "review_asset_ids": [],
            "not_adopted_asset_ids": [],
        }

    not_adopted = _applied_structure_assets(
        auto_apply,
        apply_result=apply_result,
    )
    review: set[tuple[str, str]] = set()
    for item in suggestions:
        source = _structure_asset_identity(item, side="source")
        if source is not None and source in not_adopted:
            # This suggestion was resolved by deprecating its workflow-owned source.
            continue
        review.update(_current_workflow_assets(item, workflow_id=workflow_id))

    review.difference_update(not_adopted)
    return {
        "review": len(review),
        "not_adopted": len(not_adopted),
        "affected": len(review | not_adopted),
        "review_asset_ids": sorted(
            f"{asset_type}:{asset_id}" for asset_type, asset_id in review
        ),
        "not_adopted_asset_ids": sorted(
            f"{asset_type}:{asset_id}" for asset_type, asset_id in not_adopted
        ),
    }


def _applied_structure_assets(
    auto_apply: list[dict[str, Any]],
    *,
    apply_result: dict[str, Any],
) -> set[tuple[str, str]]:
    applied_count = max(0, int(apply_result.get("applied", 0) or 0))
    applied: set[tuple[str, str]] = set()
    for result in apply_result.get("results") or []:
        if not isinstance(result, dict):
            continue
        identity = _structure_asset_identity(result, side="source")
        if identity is not None:
            applied.add(identity)

    # Compatibility with existing/fake outline facades that only return a count.
    if len(applied) < applied_count:
        for item in auto_apply:
            identity = _structure_asset_identity(item, side="source")
            if identity is not None:
                applied.add(identity)
            if len(applied) >= applied_count:
                break
    return applied


def _current_workflow_assets(
    item: dict[str, Any],
    *,
    workflow_id: str,
) -> set[tuple[str, str]]:
    assets: set[tuple[str, str]] = set()
    for side in ("source", "target"):
        if item.get(f"{side}_workflow_id") != workflow_id:
            continue
        identity = _structure_asset_identity(item, side=side)
        if identity is not None:
            assets.add(identity)
    return assets


def _structure_asset_identity(
    item: dict[str, Any],
    *,
    side: str,
) -> tuple[str, str] | None:
    asset_type = str(item.get("asset_type") or "").strip()
    asset_id = str(item.get(f"{side}_asset_id") or "").strip()
    if not asset_type or not asset_id:
        return None
    return asset_type, asset_id


def _safe_structure_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "asset_type",
        "action",
        "source_asset_id",
        "source_title",
        "target_asset_id",
        "target_title",
        "recommended_primary_asset_id",
        "confidence",
        "match_method",
        "requires_confirmation",
        "source_workflow_id",
        "target_workflow_id",
    }
    return {key: value for key, value in item.items() if key in allowed}
