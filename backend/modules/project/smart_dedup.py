from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline import facade as outline_facade
from modules.world import facade as world_facade

WORLD_ASSET_TYPE = "world_entity"
OUTLINE_ASSET_TYPES = {
    "plot_thread",
    "outline_arc",
    "scene",
    "foreshadowing_plan",
    "reveal_plan",
}


class SmartDedupService:
    """Project-level orchestrator for module-owned dedupe suggestion services."""

    async def scan(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scopes: list[str] | None = None,
        limit_per_scope: int = 1000,
        max_suggestions: int = 120,
        progress_callback: Any | None = None,
    ) -> dict[str, Any]:
        selected = set(scopes or [WORLD_ASSET_TYPE, *sorted(OUTLINE_ASSET_TYPES)])
        world_budget = max(1, max_suggestions // 3)
        outline_budget = max(1, max_suggestions - world_budget)

        suggestions: list[dict[str, Any]] = []
        module_results: dict[str, Any] = {}
        scanned_counts: dict[str, int] = {}

        if WORLD_ASSET_TYPE in selected:
            world_result = await world_facade.suggest_entity_fusion(
                db,
                novel_id,
                limit=min(limit_per_scope, 1000),
                max_suggestions=world_budget,
                progress_callback=lambda value: _progress(
                    progress_callback,
                    0.05,
                    0.4,
                    value,
                ),
            )
            module_results["world"] = _compact_module_result(world_result)
            scanned_counts[WORLD_ASSET_TYPE] = int(
                world_result.get("total_entities_scanned") or 0
            )
            suggestions.extend(_normalize_world_suggestions(world_result))

        outline_scopes = sorted(selected & OUTLINE_ASSET_TYPES)
        if outline_scopes:
            outline_result = await outline_facade.suggest_structure_dedup(
                db,
                novel_id,
                asset_types=outline_scopes,
                limit=limit_per_scope,
                max_suggestions=outline_budget,
                progress_callback=lambda value: _progress(
                    progress_callback,
                    0.45,
                    0.95,
                    value,
                ),
            )
            module_results["outline"] = _compact_module_result(outline_result)
            for key, value in (outline_result.get("scanned_counts") or {}).items():
                scanned_counts[key] = int(value or 0)
            suggestions.extend(_normalize_outline_suggestions(outline_result))

        suggestions = suggestions[:max_suggestions]
        total_assets = sum(scanned_counts.values())
        duplicate_count = len(
            [
                item
                for item in suggestions
                if item.get("action") in {"merge", "alias_only", "deprecate_duplicate"}
            ]
        )
        duplicate_rate = duplicate_count / total_assets if total_assets else 0.0
        return {
            "task_type": "smart_dedup_scan",
            "novel_id": novel_id,
            "scopes_scanned": sorted(selected),
            "scanned_counts": scanned_counts,
            "total_assets_scanned": total_assets,
            "suggestion_count": len(suggestions),
            "estimated_duplicate_count": duplicate_count,
            "estimated_duplicate_rate": round(duplicate_rate, 4),
            "suggestions": suggestions,
            "module_results": module_results,
            "summary": f"生成 {len(suggestions)} 条智能去重建议",
        }

    async def apply(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmed: bool,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("confirmed=true is required")

        world_items: list[dict[str, Any]] = []
        outline_items: list[dict[str, Any]] = []
        skipped = 0
        warnings: list[str] = []

        for item in suggestions:
            asset_type = str(item.get("asset_type") or "")
            if asset_type == WORLD_ASSET_TYPE:
                mapped = _world_apply_item(item)
                if mapped is None:
                    skipped += 1
                    warnings.append("跳过不可应用的世界对象建议")
                else:
                    world_items.append(mapped)
            elif asset_type in OUTLINE_ASSET_TYPES:
                outline_items.append(item)
            else:
                skipped += 1
                warnings.append(f"跳过未知资产类型：{asset_type}")

        results: dict[str, Any] = {}
        applied = 0
        if world_items:
            world_result = await world_facade.apply_entity_fusion(
                db,
                novel_id,
                confirmed=True,
                suggestions=world_items,
            )
            results["world"] = world_result
            applied += int(world_result.get("applied") or 0)
            skipped += int(world_result.get("skipped") or 0)
            warnings.extend(world_result.get("warnings") or [])
        if outline_items:
            outline_result = await outline_facade.apply_structure_dedup(
                db,
                novel_id,
                confirmed=True,
                suggestions=outline_items,
            )
            results["outline"] = outline_result
            applied += int(outline_result.get("applied") or 0)
            skipped += int(outline_result.get("skipped") or 0)
            warnings.extend(outline_result.get("warnings") or [])

        return {
            "applied": applied,
            "skipped": skipped,
            "results": results,
            "warnings": warnings,
        }


def _progress(callback: Any | None, start: float, end: float, value: float) -> None:
    if callback is None:
        return
    try:
        callback(start + (end - start) * max(0.0, min(1.0, float(value))))
    except Exception:
        return


def _compact_module_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_type": result.get("task_type"),
        "total_assets_scanned": (
            result.get("total_assets_scanned") or result.get("total_entities_scanned")
        ),
        "suggestion_count": result.get("suggestion_count"),
        "summary": result.get("summary"),
    }


def _normalize_world_suggestions(result: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in result.get("suggestions") or []:
        normalized.append(
            {
                "asset_type": WORLD_ASSET_TYPE,
                "action": item.get("action"),
                "source_asset_id": item.get("source_entity_id"),
                "source_title": item.get("source_entity_name"),
                "source_status": item.get("source_status"),
                "target_asset_id": item.get("target_entity_id"),
                "target_title": item.get("target_entity_name"),
                "target_status": item.get("target_status"),
                "recommended_primary_asset_id": item.get("recommended_primary_entity_id")
                or item.get("recommended_primary_asset_id")
                or item.get("target_entity_id"),
                "recommended_primary_title": item.get("recommended_primary_entity_name")
                or item.get("recommended_primary_title")
                or item.get("target_entity_name"),
                "confidence": item.get("confidence"),
                "reason": item.get("reason"),
                "match_method": item.get("match_method"),
                "evidence_anchors": item.get("evidence_anchors") or [],
                "alias": item.get("alias"),
                "requires_canonical_confirmation": item.get(
                    "requires_canonical_confirmation",
                    False,
                ),
                "requires_confirmation": True,
            }
        )
    return normalized


def _normalize_outline_suggestions(result: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in result.get("suggestions") or []:
        normalized_item = dict(item)
        normalized_item.setdefault(
            "recommended_primary_asset_id",
            item.get("target_asset_id"),
        )
        normalized_item.setdefault(
            "recommended_primary_title",
            item.get("target_title"),
        )
        normalized.append(normalized_item)
    return normalized


def _world_apply_item(item: dict[str, Any]) -> dict[str, Any] | None:
    action = item.get("action")
    if action not in {"merge", "alias_only"}:
        return None
    return {
        "action": action,
        "source_entity_id": item.get("source_asset_id"),
        "target_entity_id": item.get("target_asset_id"),
        "alias": item.get("alias") or item.get("source_title"),
        "allow_canonical_merge": bool(item.get("allow_canonical_merge")),
    }
