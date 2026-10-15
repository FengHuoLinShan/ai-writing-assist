"""Finite, isolated request quotas for spatial-enabled optional reading steps."""

from __future__ import annotations

from math import ceil
from typing import Any

OPTIONAL_STEP_CALLS_PER_SCENE = {"details": 8, "spatial": 2}
MAX_OPTIONAL_STEP_CALLS = 1000


class OptionalStepQuotaExhaustedError(Exception):
    """An optional request was not issued because its child budget is exhausted."""

    def __init__(self, step: str, journal_key: str, reason: str):
        super().__init__(f"{step} optional quota unavailable: {reason}")
        self.step = step
        self.journal_key = journal_key
        self.reason = reason


def record_optional_gap(
    payload: dict[str, Any], step: str, journal_key: str, reason: str
):
    coverage = dict(payload.get("optional_step_coverage") or {})
    current = dict(coverage.get(step) or {})
    gaps = list(current.get("gaps", []))
    entry = {"journal_key": journal_key, "reason": reason}
    if entry not in gaps:
        gaps.append(entry)
    has_result = any(
        key.startswith(f"scene_{'discovery' if step == 'details' else 'spatial'}_")
        and isinstance(value, dict)
        and value.get("stage") == "sampled"
        for key, value in payload.items()
    )
    status = "inspected" if has_result else "not_run"
    if current.get("status") in {"unknown", "stale"}:
        status = current["status"]
    current.update(status=status, gaps=gaps)
    coverage[step] = current
    payload["optional_step_coverage"] = coverage


def optional_quotas(
    plan: dict[str, Any], *, additional_scenes: int = 0
) -> dict[str, dict]:
    """Freeze a finite per-step child quota; no root-unlimited plan yields infinity."""
    previous = plan.get("optional_step_quotas", {})
    scenes = max(0, int(additional_scenes))
    enabled = {
        "details": plan.get("discovery_version", 0) in {1, 2},
        "spatial": plan.get("spatial_version", 0) == 1,
    }
    result = {}
    for key, is_enabled in enabled.items():
        if not is_enabled:
            continue
        per_scene = OPTIONAL_STEP_CALLS_PER_SCENE[key]
        old = previous.get(key, {})
        added = min(MAX_OPTIONAL_STEP_CALLS, scenes * per_scene)
        limit = min(MAX_OPTIONAL_STEP_CALLS, int(old.get("limit", 0)) + added)
        used = int(old.get("used", 0))
        # Initial previews may have no concrete scenes yet because boundaries
        # must be prepared first. The quota is extended only when those Scenes
        # are source-pinned into the plan.
        result[key] = {
            "version": 1,
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
            "per_scene_limit": per_scene,
            "authorized_scene_count": int(old.get("authorized_scene_count", 0))
            + scenes,
        }
    return result


def optional_step_for_journal(journal_key: str) -> str | None:
    if journal_key.startswith("scene_discovery_"):
        return "details"
    if journal_key.startswith("scene_spatial_"):
        return "spatial"
    return None


def optional_call_block_reason(run, payload: dict[str, Any], step: str) -> str | None:
    plan = run.reading_plan_json or {}
    quota = (plan.get("optional_step_quotas") or {}).get(step)
    if not quota or int(quota.get("remaining", 0)) <= 0:
        return "child_quota_exhausted"
    if run.budget_remaining is not None:
        reserve = mandatory_requests_remaining(run, payload)
        if run.budget_remaining - 1 < reserve:
            return "main_understanding_reserve_protected"
    return None


def adjust_optional_quota(plan: dict[str, Any], step: str, delta: int) -> dict[str, Any]:
    quotas = dict(plan.get("optional_step_quotas") or {})
    if step not in quotas:
        return plan
    quota = dict(quotas[step])
    used = max(0, min(int(quota.get("limit", 0)), int(quota.get("used", 0)) + delta))
    quota["used"] = used
    quota["remaining"] = int(quota.get("limit", 0)) - used
    quotas[step] = quota
    return {**plan, "optional_step_quotas": quotas}


def _known_scene_calls(plan: dict[str, Any]) -> dict[int, dict[str, int]]:
    entries = plan.get("mandatory_scene_calls") or []
    return {
        int(item["scene_index"]): {
            str(key): int(value) for key, value in item.get("calls", {}).items()
        }
        for item in entries
    }


def _journal_charged(payload: dict[str, Any], key: str) -> bool:
    journal = payload.get(key) or {}
    return bool(journal) and journal.get("stage") in {"sampling", "sampled", "failed"}


def _current_scene_reserve(payload: dict[str, Any], calls: dict[str, int]) -> int:
    remaining = 0
    scene_sample = payload.get("scene_sample") or {}
    if not _journal_charged(payload, "paid_call_receipt") and not (
        scene_sample.get("stage") in {"sampling", "sampled", "failed"}
        or payload.get("stage") in {"sampling", "sampled", "compiled", "verified"}
    ):
        remaining += calls.get("scene_sample", 0)
    if calls.get("world") and not _journal_charged(payload, "scene_world"):
        if not payload.get("world_result"):
            remaining += calls["world"]
    if calls.get("enrichment"):
        if not payload.get("enrichment_result"):
            remaining += sum(
                not _journal_charged(payload, key)
                for key in ("scene_enrichment", "scene_enrichment_review")
            )
    if payload.get("state_review_version") == 1 and payload.get(
        "state_event_candidates", payload.get("scene_events")
    ):
        if not _journal_charged(payload, "state_review"):
            remaining += 1
    relation = (payload.get("relations_preparation") or {}).get("call")
    if relation and not _journal_charged(payload, "scene_relations"):
        remaining += 1
    groups = (payload.get("world_review_preparation") or {}).get("groups", [])
    for group in groups:
        if group.get("deferred_reason") or not group.get("spec"):
            continue
        key = f"scene_world_review_group_{group['group_id']}"
        if not _journal_charged(payload, key):
            remaining += 1
    return remaining


def mandatory_requests_remaining(run, payload: dict[str, Any] | None = None) -> int:
    """Minimum outstanding core demand, using frozen versions and materialized plans.

    Optional detail/spatial calls are deliberately excluded. For the active Scene,
    persisted journals/results reduce the estimate; later source-pinned Scenes use
    the concrete requirements recorded at preview time.
    """
    plan = run.reading_plan_json or {}
    calls_by_scene = _known_scene_calls(plan)
    pending_index = run.committed_scene_index + 1
    reserve = 0
    for scene_index, calls in calls_by_scene.items():
        if scene_index <= run.committed_scene_index:
            continue
        if payload is not None and scene_index == pending_index:
            reserve += _current_scene_reserve(payload, calls)
        else:
            reserve += sum(calls.values())

    preparation = plan.get("preparation") or {}
    if preparation.get("stage") not in {None, "complete"}:
        calls = preparation.get("calls") or {}
        reserve += sum(
            item.get("stage") == "planned" for item in calls.values()
        )
        if not calls:
            reserve += len((preparation.get("plan") or {}).get("windows", []))

    structure = plan.get("structure") or {}
    if plan.get("structure_version", 0) == 1 and not structure.get("complete"):
        current = structure.get("current")
        if current:
            reserve += sum(
                call.get("stage") == "planned"
                for call in (current.get("calls") or {}).values()
            )
        else:
            # The real Story builder batches at most 16 committed Scene cards.
            through = int(structure.get("through_scene_index", -1))
            last_planned = max(
                (int(step["scene_index"]) for step in plan.get("steps", [])),
                default=-1,
            )
            reserve += ceil(max(0, last_planned - through) / 16)
    return max(0, int(reserve))


__all__ = [
    "MAX_OPTIONAL_STEP_CALLS",
    "OptionalStepQuotaExhaustedError",
    "OPTIONAL_STEP_CALLS_PER_SCENE",
    "adjust_optional_quota",
    "mandatory_requests_remaining",
    "optional_call_block_reason",
    "optional_quotas",
    "optional_step_for_journal",
    "record_optional_gap",
]
