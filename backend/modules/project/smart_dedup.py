from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.llm.redaction import redact_diagnostic
from modules.project.repositories import SmartDedupWorkbenchDecisionRepository
from modules.story import facade as outline_facade
from modules.world import facade as world_facade
from shared.utils import parse_uuid

WORLD_ASSET_TYPE = "world_entity"
OUTLINE_ASSET_TYPES = {
    "plot_thread",
    "outline_arc",
    "scene",
    "foreshadowing_plan",
    "reveal_plan",
}

logger = logging.getLogger(__name__)


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
        llm_client: Any | None = None,
    ) -> dict[str, Any]:
        selected = set(scopes or [WORLD_ASSET_TYPE, *sorted(OUTLINE_ASSET_TYPES)])
        world_legacy_budget = max(1, max_suggestions // 3)
        outline_budget = max(1, max_suggestions - world_legacy_budget)

        suggestions: list[dict[str, Any]] = []
        world_suggestions: list[dict[str, Any]] = []
        outline_suggestions: list[dict[str, Any]] = []
        module_results: dict[str, Any] = {}
        scanned_counts: dict[str, int] = {}

        disposition_repo = SmartDedupWorkbenchDecisionRepository()
        disposition_rows = await disposition_repo.list_active(
            db,
            parse_uuid(novel_id, "novel_id"),
            selected,
        )
        exclusions = [
            {
                "asset_type": item.asset_type,
                "left_asset_id": item.left_asset_id,
                "right_asset_id": item.right_asset_id,
                "left_semantic_fingerprint": item.left_semantic_fingerprint,
                "right_semantic_fingerprint": item.right_semantic_fingerprint,
            }
            for item in disposition_rows
        ]

        if WORLD_ASSET_TYPE in selected:
            world_result = await world_facade.suggest_entity_fusion(
                db,
                novel_id,
                limit=min(limit_per_scope, 1000),
                # World connected components must see the complete edge set within
                # the project-level suggestion budget before group trimming.
                max_suggestions=max_suggestions,
                group_before_budget=True,
                progress_callback=lambda value: _progress(
                    progress_callback,
                    0.05,
                    0.4,
                    value,
                ),
                exclusions=[
                    item for item in exclusions if item["asset_type"] == WORLD_ASSET_TYPE
                ],
                llm_client=llm_client,
            )
            module_results["world"] = _compact_module_result(world_result)
            scanned_counts[WORLD_ASSET_TYPE] = int(
                world_result.get("total_entities_scanned") or 0
            )
            world_suggestions = _normalize_world_suggestions(world_result)
            suggestions.extend(world_suggestions)

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
                exclusions=[
                    item for item in exclusions if item["asset_type"] in outline_scopes
                ],
                llm_client=llm_client,
            )
            module_results["outline"] = _compact_module_result(outline_result)
            for key, value in (outline_result.get("scanned_counts") or {}).items():
                scanned_counts[key] = int(value or 0)
            outline_suggestions = _normalize_outline_suggestions(outline_result)
            suggestions.extend(outline_suggestions)

        await disposition_repo.supersede_changed_pairs(
            db,
            disposition_rows,
            _semantic_pairs(suggestions),
        )
        groups, deferred_edge_count = _build_groups(suggestions)
        groups = _trim_groups(groups, max_suggestions)
        world_limit = world_legacy_budget if outline_suggestions else max_suggestions
        outline_limit = outline_budget if world_suggestions else max_suggestions
        suggestions = [
            *world_suggestions[:world_limit],
            *outline_suggestions[:outline_limit],
        ][:max_suggestions]
        total_assets = sum(scanned_counts.values())
        duplicate_count = len(
            [
                item
                for item in suggestions
                if item.get("action")
                in {"merge", "ai_fusion", "alias_only", "deprecate_duplicate"}
            ]
        )
        duplicate_rate = duplicate_count / total_assets if total_assets else 0.0
        return {
            "schema_version": 2,
            "task_type": "smart_dedup_scan",
            "novel_id": novel_id,
            "scopes_scanned": sorted(selected),
            "scanned_counts": scanned_counts,
            "total_assets_scanned": total_assets,
            "suggestion_count": len(suggestions),
            "estimated_duplicate_count": duplicate_count,
            "estimated_duplicate_rate": round(duplicate_rate, 4),
            "suggestions": suggestions,
            "groups": groups,
            "group_count": len(groups),
            "deferred_edge_count": deferred_edge_count,
            "module_results": module_results,
            "summary": f"生成 {len(suggestions)} 条智能去重建议",
        }

    async def apply_groups(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scan_task_id: str,
        groups: list[dict[str, Any]],
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValidationError(
                "confirmed=true is required",
                code="confirmation_required",
            )
        from infrastructure.tasks.facade import get_completed_task_payload

        task = await get_completed_task_payload(
            db,
            task_id=scan_task_id,
            task_type="smart_dedup_scan",
            novel_id=novel_id,
            for_update=True,
        )
        if task is None:
            raise ValidationError("invalid scan task", code="invalid_group")
        result = task.result
        if result.get("schema_version") != 2:
            raise ValidationError(
                "group apply requires smart dedup schema version 2",
                code="invalid_group",
            )
        server_groups = {
            str(item.get("group_id")): item for item in result.get("groups") or []
        }
        seen_assets: set[str] = set()
        for request_group in groups:
            server_group = server_groups.get(str(request_group.get("group_id")))
            if server_group is None or request_group.get(
                "asset_type"
            ) != server_group.get("asset_type"):
                raise ValidationError("invalid_group", code="invalid_group")
            operation_sources = [
                str(item.get("source_asset_id"))
                for item in request_group.get("operations") or []
            ]
            if len(operation_sources) != len(set(operation_sources)):
                raise ValidationError(
                    "duplicate source operation",
                    code="invalid_group",
                )
            involved = {
                str(request_group.get("primary_asset_id")),
                *operation_sources,
            }
            if seen_assets & involved:
                raise ValidationError(
                    "asset cannot participate in multiple groups",
                    code="invalid_group",
                )
            seen_assets.update(involved)

        group_results: list[dict[str, Any]] = []
        applied = 0
        skipped = 0
        warnings: list[str] = []
        repo = SmartDedupWorkbenchDecisionRepository()
        nid = parse_uuid(novel_id, "novel_id")

        async def invoke_domain_group(
            request_group: dict[str, Any],
            server_group: dict[str, Any],
            prepared: list[dict[str, Any]],
            *,
            validate_only: bool,
            execution_fingerprints_prevalidated: bool,
        ) -> list[dict[str, Any]]:
            if server_group["asset_type"] == WORLD_ASSET_TYPE:
                return await world_facade.apply_entity_fusion_group(
                    db,
                    novel_id,
                    primary_entity_id=str(request_group["primary_asset_id"]),
                    operations=[
                        {**item, "source_entity_id": item["source_asset_id"]}
                        for item in prepared
                    ],
                    validate_only=validate_only,
                    execution_fingerprints_prevalidated=(
                        execution_fingerprints_prevalidated
                    ),
                )
            return await outline_facade.apply_structure_dedup_group(
                db,
                novel_id,
                asset_type=str(server_group["asset_type"]),
                primary_asset_id=str(request_group["primary_asset_id"]),
                operations=prepared,
                validate_only=validate_only,
                execution_fingerprints_prevalidated=(
                    execution_fingerprints_prevalidated
                ),
            )

        prepared_by_group: dict[str, list[dict[str, Any]]] = {}
        preflight_failures: dict[str, tuple[str, str]] = {}
        # Validate every group against the same pre-write snapshot. World/outline
        # keep the relevant rows locked until this request completes, so relation
        # migrations from an earlier successful group cannot make a later group
        # appear externally stale.
        for request_group in groups:
            group_id = str(request_group["group_id"])
            server_group = server_groups[group_id]
            try:
                prepared = _validate_group_request(server_group, request_group)
                async with db.begin_nested():
                    await invoke_domain_group(
                        request_group,
                        server_group,
                        prepared,
                        validate_only=True,
                        execution_fingerprints_prevalidated=False,
                    )
                prepared_by_group[group_id] = prepared
            except Exception as exc:
                code = _group_error_code(exc)
                logger.warning(
                    "Smart dedup group preflight failed group_id=%s "
                    "error_code=%s diagnostic=%s",
                    group_id,
                    code,
                    redact_diagnostic(f"{type(exc).__name__}: {exc}", limit=500),
                )
                preflight_failures[group_id] = (
                    code,
                    _public_group_error_message(code),
                )

        for request_group in groups:
            group_id = str(request_group["group_id"])
            server_group = server_groups[group_id]
            if group_id in preflight_failures:
                code, message = preflight_failures[group_id]
                skipped += len(request_group.get("operations") or [])
                warnings.append(f"{group_id}: {code}")
                group_results.append(
                    {
                        "group_id": group_id,
                        "status": "failed",
                        "applied": 0,
                        "error_code": code,
                        "message": message,
                    }
                )
                continue
            try:
                async with db.begin_nested():
                    prepared = prepared_by_group[group_id]
                    domain_results = await invoke_domain_group(
                        request_group,
                        server_group,
                        prepared,
                        validate_only=False,
                        execution_fingerprints_prevalidated=True,
                    )
                    keep_results = [
                        item
                        for item in domain_results
                        if item.get("action") == "keep_separate"
                    ]
                    if len(keep_results) != sum(
                        item.get("action") == "keep_separate" for item in prepared
                    ):
                        raise ValueError("group_apply_failed")
                    await repo.keep_separate_many(
                        db,
                        novel_id=nid,
                        asset_type=str(server_group["asset_type"]),
                        dispositions=keep_results,
                        source_scan_task_id=scan_task_id,
                    )
                count = len(prepared)
                applied += count
                group_results.append(
                    {
                        "group_id": group_id,
                        "status": "success",
                        "applied": count,
                        "results": domain_results,
                    }
                )
            except Exception as exc:
                skipped += len(request_group.get("operations") or [])
                code = _group_error_code(exc)
                logger.warning(
                    "Smart dedup group apply failed group_id=%s error_code=%s "
                    "diagnostic=%s",
                    group_id,
                    code,
                    redact_diagnostic(f"{type(exc).__name__}: {exc}", limit=500),
                )
                warnings.append(f"{group_id}: {code}")
                group_results.append(
                    {
                        "group_id": group_id,
                        "status": "failed",
                        "applied": 0,
                        "error_code": code,
                        "message": _public_group_error_message(code),
                    }
                )
        return {
            "applied": applied,
            "skipped": skipped,
            "results": {},
            "warnings": warnings,
            "group_results": group_results,
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
        risk = _world_suggestion_risk(item)
        normalized.append(
            {
                "asset_type": WORLD_ASSET_TYPE,
                "action": item.get("action"),
                "source_asset_id": item.get("source_entity_id"),
                "source_title": item.get("source_entity_name"),
                "source_status": item.get("source_status"),
                "entity_type": item.get("entity_type"),
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
                "source_snapshot": item.get("source_snapshot") or {},
                "target_snapshot": item.get("target_snapshot") or {},
                "source_semantic_fingerprint": item.get("source_semantic_fingerprint"),
                "target_semantic_fingerprint": item.get("target_semantic_fingerprint"),
                "source_execution_fingerprint": item.get("source_execution_fingerprint"),
                "target_execution_fingerprint": item.get("target_execution_fingerprint"),
                "requires_canonical_confirmation": item.get(
                    "requires_canonical_confirmation",
                    False,
                ),
                "requires_manual_confirmation": risk["requires_manual_confirmation"],
                "risk_level": risk["risk_level"],
                "risk_reason": risk["risk_reason"],
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
        "allow_canonical_alias": bool(item.get("allow_canonical_alias")),
    }


def _world_suggestion_risk(item: dict[str, Any]) -> dict[str, Any]:
    method = str(item.get("match_method") or "").lower()
    action = str(item.get("action") or "")
    source_title = _normalized_title(item.get("source_entity_name"))
    target_title = _normalized_title(item.get("target_entity_name"))
    is_alias_derived = "alias" in method
    is_destructive_action = action in {"merge", "alias_only"}
    title_conflict = bool(source_title and target_title and source_title != target_title)
    if is_alias_derived and is_destructive_action and title_conflict:
        return {
            "requires_manual_confirmation": True,
            "risk_level": "high",
            "risk_reason": "alias_derived_title_conflict",
        }
    return {
        "requires_manual_confirmation": False,
        "risk_level": None,
        "risk_reason": None,
    }


def _normalized_title(value: Any) -> str:
    return str(value or "").strip().lower()


def _build_groups(suggestions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    world = [item for item in suggestions if item.get("asset_type") == WORLD_ASSET_TYPE]
    outline = [item for item in suggestions if item.get("asset_type") != WORLD_ASSET_TYPE]
    groups, deferred = _build_world_groups(world)
    groups.extend(_pair_group(item) for item in outline)
    return groups, deferred


def _trim_groups(
    groups: list[dict[str, Any]],
    max_suggestions: int,
) -> list[dict[str, Any]]:
    """Trim after grouping without splitting one connected component."""
    selected: list[dict[str, Any]] = []
    consumed = 0
    for group in groups:
        edge_count = max(1, len(group.get("edges") or []))
        if selected and consumed + edge_count > max_suggestions:
            break
        selected.append(group)
        consumed += edge_count
    return selected


def _build_world_groups(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_type[str(item.get("entity_type") or "unknown")].append(item)
    groups: list[dict[str, Any]] = []
    deferred = 0
    for entity_type in sorted(by_type):
        type_groups, type_deferred = _build_world_type_groups(by_type[entity_type])
        groups.extend(type_groups)
        deferred += type_deferred
    return groups, deferred


def _build_world_type_groups(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    edge_by_pair: dict[frozenset[str], dict[str, Any]] = {}
    for item in items:
        source = str(item.get("source_asset_id") or "")
        target = str(item.get("target_asset_id") or "")
        if not source or not target:
            continue
        adjacency[source].add(target)
        adjacency[target].add(source)
        edge_by_pair[frozenset((source, target))] = item
    components: list[set[str]] = []
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        stack = [start]
        component: set[str] = set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(adjacency[node] - component)
        unseen -= component
        components.append(component)

    groups: list[dict[str, Any]] = []
    deferred = 0
    for component in components:
        hubs = sorted(node for node in component if component - {node} <= adjacency[node])
        component_edges = [
            edge for pair, edge in edge_by_pair.items() if pair <= component
        ]
        if hubs:
            recommended = _recommended_hub(component_edges, hubs)
            groups.append(
                _world_cluster_group(component, component_edges, hubs, recommended)
            )
            continue
        ordered = sorted(
            component_edges,
            key=lambda item: (-float(item.get("confidence") or 0), _pair_ids(item)),
        )
        used: set[str] = set()
        for edge in ordered:
            pair = set(_pair_ids(edge))
            if used & pair:
                deferred += 1
                continue
            used.update(pair)
            groups.append(_pair_group(edge))
    return groups, deferred


def _recommended_hub(edges: list[dict[str, Any]], hubs: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for edge in edges:
        candidate = str(edge.get("recommended_primary_asset_id") or "")
        if candidate in hubs:
            counts[candidate] += 1
    return sorted(hubs, key=lambda item: (-counts[item], item))[0]


def _world_cluster_group(
    component: set[str],
    edges: list[dict[str, Any]],
    hubs: list[str],
    recommended: str,
) -> dict[str, Any]:
    members: dict[str, dict[str, Any]] = {}
    for edge in edges:
        members[str(edge["source_asset_id"])] = edge.get("source_snapshot") or {}
        members[str(edge["target_asset_id"])] = edge.get("target_snapshot") or {}
    return {
        "group_id": _group_id(WORLD_ASSET_TYPE, component),
        "asset_type": WORLD_ASSET_TYPE,
        "entity_type": edges[0].get("entity_type") if edges else None,
        "presentation": "cluster" if len(component) > 2 else "pair",
        "members": [members[item] for item in sorted(component)],
        "eligible_primary_asset_ids": hubs,
        "recommended_primary_asset_id": recommended,
        "risk_level": "high"
        if any(edge.get("risk_level") == "high" for edge in edges)
        else None,
        "edges": [_group_edge(item) for item in edges],
    }


def _pair_group(item: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(item.get("asset_type") or "")
    ids = {str(item["source_asset_id"]), str(item["target_asset_id"])}
    return {
        "group_id": _group_id(asset_type, ids),
        "asset_type": asset_type,
        "presentation": "pair",
        "members": [
            item.get("source_snapshot") or {},
            item.get("target_snapshot") or {},
        ],
        "eligible_primary_asset_ids": sorted(ids),
        "recommended_primary_asset_id": item.get("recommended_primary_asset_id"),
        "risk_level": item.get("risk_level"),
        "edges": [_group_edge(item)],
    }


def _group_edge(item: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(item.get("asset_type") or "")
    allowed = (
        ["merge", "alias_only", "keep_separate"]
        if asset_type == WORLD_ASSET_TYPE
        else (
            ["ai_fusion", "merge", "keep_separate"]
            if asset_type == "scene"
            else ["deprecate_duplicate", "keep_separate"]
        )
    )
    return {
        "source_asset_id": item.get("source_asset_id"),
        "target_asset_id": item.get("target_asset_id"),
        "recommended_action": item.get("action"),
        "resolution_mode": item.get("resolution_mode"),
        "allowed_actions": allowed,
        "confidence": item.get("confidence"),
        "reason": item.get("reason"),
        "match_method": item.get("match_method"),
        "evidence_anchors": item.get("evidence_anchors") or [],
        "source_semantic_fingerprint": item.get("source_semantic_fingerprint"),
        "target_semantic_fingerprint": item.get("target_semantic_fingerprint"),
        "source_execution_fingerprint": item.get("source_execution_fingerprint"),
        "target_execution_fingerprint": item.get("target_execution_fingerprint"),
    }


def _group_id(asset_type: str, member_ids: set[str]) -> str:
    raw = f"2:{asset_type}:{','.join(sorted(member_ids))}"
    return f"sdg-{hashlib.sha256(raw.encode()).hexdigest()[:24]}"


def _pair_ids(item: dict[str, Any]) -> tuple[str, str]:
    return tuple(
        sorted((str(item.get("source_asset_id")), str(item.get("target_asset_id"))))
    )


def _semantic_pairs(suggestions: list[dict[str, Any]]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for item in suggestions:
        source = str(item.get("source_asset_id") or "")
        target = str(item.get("target_asset_id") or "")
        source_fp = str(item.get("source_semantic_fingerprint") or "")
        target_fp = str(item.get("target_semantic_fingerprint") or "")
        if not source or not target or not source_fp or not target_fp:
            continue
        left, right = sorted((source, target))
        left_fp, right_fp = (
            (source_fp, target_fp) if left == source else (target_fp, source_fp)
        )
        pairs.append(
            {
                "asset_type": str(item.get("asset_type") or ""),
                "left_asset_id": left,
                "right_asset_id": right,
                "left_semantic_fingerprint": left_fp,
                "right_semantic_fingerprint": right_fp,
            }
        )
    return pairs


def _validate_group_request(
    server_group: dict[str, Any], request_group: dict[str, Any]
) -> list[dict[str, Any]]:
    primary = str(request_group.get("primary_asset_id") or "")
    if primary not in set(server_group.get("eligible_primary_asset_ids") or []):
        raise ValueError("invalid_group")
    member_ids = {
        str(item.get("asset_id") or "") for item in server_group.get("members") or []
    }
    operations = request_group.get("operations") or []
    submitted_source_list = [
        str(item.get("source_asset_id") or "") for item in operations
    ]
    submitted_sources = set(submitted_source_list)
    if (
        not member_ids
        or len(submitted_source_list) != len(submitted_sources)
        or submitted_sources != member_ids - {primary}
    ):
        raise ValueError("invalid_group")
    edges = {
        frozenset((str(item["source_asset_id"]), str(item["target_asset_id"]))): item
        for item in server_group.get("edges") or []
    }
    prepared: list[dict[str, Any]] = []
    for operation in operations:
        source = str(operation.get("source_asset_id") or "")
        edge = edges.get(frozenset((source, primary)))
        if edge is None or operation.get("action") not in edge.get("allowed_actions", []):
            raise ValueError("invalid_group")
        source_is_edge_source = source == str(edge["source_asset_id"])
        source_execution = edge[
            "source_execution_fingerprint"
            if source_is_edge_source
            else "target_execution_fingerprint"
        ]
        target_execution = edge[
            "target_execution_fingerprint"
            if source_is_edge_source
            else "source_execution_fingerprint"
        ]
        if (
            operation.get("expected_source_execution_fingerprint") != source_execution
            or operation.get("expected_target_execution_fingerprint") != target_execution
        ):
            raise ValueError("stale_suggestion")
        normalized = {**operation, "source_asset_id": source}
        prepared.append(normalized)
    return prepared


def _group_error_code(exc: Exception) -> str:
    if isinstance(exc, ValidationError) and exc.code in {
        "stale_suggestion",
        "confirmation_required",
        "invalid_group",
        "group_apply_failed",
    }:
        return exc.code
    message = str(exc)
    if "stale_suggestion" in message:
        return "stale_suggestion"
    if "confirmation_required" in message:
        return "confirmation_required"
    if "invalid_group" in message:
        return "invalid_group"
    return "group_apply_failed"


def _public_group_error_message(code: str) -> str:
    return {
        "stale_suggestion": "资产已发生变化，请重新扫描后再裁决。",
        "confirmation_required": "该操作需要补充明确确认。",
        "invalid_group": "裁决组与扫描结果不一致，请重新扫描。",
        "group_apply_failed": "该裁决组执行失败，请重试或重新扫描。",
    }.get(code, "该裁决组执行失败，请重试或重新扫描。")
