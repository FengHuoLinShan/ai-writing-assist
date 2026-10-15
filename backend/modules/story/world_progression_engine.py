"""Deterministic collision and metric helpers for candidate Story progression."""

from __future__ import annotations

from collections import defaultdict

from infrastructure.llm.collaboration import content_hash


def detect_progression_intersections(
    actions: list[dict], *, route_comparison_available: bool | str
) -> dict:
    """Compare shared typed IDs; labels, coordinates, and missing fields never match."""
    route_status = (
        route_comparison_available
        if isinstance(route_comparison_available, str)
        else "available"
        if route_comparison_available
        else "not_available"
    )
    if route_status not in {"available", "partial", "not_available"}:
        route_status = "not_available"
    by_actor = {str(item["actor_id"]): item for item in actions}
    pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    route_pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    actors = sorted(by_actor)
    for index, left_id in enumerate(actors):
        left = by_actor[left_id]
        for right_id in actors[index + 1 :]:
            right = by_actor[right_id]
            pair = (left_id, right_id)
            left_location = left.get("location_target")
            right_location = right.get("location_target")
            if (
                left_location
                and right_location
                and left_location.get("kind") == right_location.get("kind")
                and left_location.get("id") == right_location.get("id")
            ):
                pairs[pair].add("same_location_target")
            left_object = left.get("target_object_id")
            if left_object and left_object == right.get("target_object_id"):
                pairs[pair].add("same_target_object")
            left_resource = left.get("resource_key")
            if left_resource and left_resource == right.get("resource_key"):
                pairs[pair].add("same_resource_key")
            if route_status in {"available", "partial"}:
                shared = set(left.get("journey_route_ids") or ()) & set(
                    right.get("journey_route_ids") or ()
                )
                if shared:
                    pairs[pair].add("shared_existing_route")
                    route_pairs[pair].update(shared)
            if right_id in set(left.get("information_recipient_ids") or ()) or (
                left_id in set(right.get("information_recipient_ids") or ())
            ):
                pairs[pair].add("information_recipient")

    intersections = []
    for pair, kinds in sorted(pairs.items()):
        routes = sorted(route_pairs.get(pair, set()))
        intersections.append(
            {
                "intersection_id": content_hash(
                    {"actors": pair, "kinds": sorted(kinds), "routes": routes}
                )[:24],
                "actor_ids": list(pair),
                "kinds": sorted(kinds),
                "route_ids": routes,
            }
        )
    return {
        "items": intersections,
        "route_comparison": route_status,
        "route_note": (
            None
            if route_status == "available"
            else "地图路线覆盖不完整；已比较当前可见的结构化路线，其余路线未比较。"
            if route_status == "partial"
            else "当前没有可用地图路线依据；只比较相同结构化目的地，路线未比较。"
        ),
    }


def derive_progression_metrics(
    *,
    before_state: dict,
    after_state: dict,
    resolution: dict,
    intersections: dict,
) -> dict:
    """Count persisted structural deltas, never model prose or inferred facts."""
    statuses_before = before_state.get("candidate_status", {})
    statuses_after = after_state.get("candidate_status", {})
    attitudes_before = before_state.get("candidate_attitudes", {})
    attitudes_after = after_state.get("candidate_attitudes", {})
    knowledge_before = before_state.get("candidate_knowledge", {})
    knowledge_after = after_state.get("candidate_knowledge", {})
    resources_before = before_state.get("candidate_resources", {})
    resources_after = after_state.get("candidate_resources", {})
    changed = sum(
        [
            sum(
                statuses_before.get(key) != statuses_after.get(key)
                for key in set(statuses_before) | set(statuses_after)
            ),
            sum(
                attitudes_before.get(key) != attitudes_after.get(key)
                for key in set(attitudes_before) | set(attitudes_after)
            ),
            sum(
                knowledge_before.get(key) != knowledge_after.get(key)
                for key in set(knowledge_before) | set(knowledge_after)
            ),
            sum(
                resources_before.get(key) != resources_after.get(key)
                for key in set(resources_before) | set(resources_after)
            ),
        ]
    )
    prior_goals = {
        str(item.get("target_id")): item.get("status")
        for item in (before_state.get("rolling_summary") or {}).get(
            "candidate_goal_statuses", []
        )
    }
    goal_values = [
        item.get("status")
        for item in resolution.get("goal_outcomes", [])
        if prior_goals.get(str(item.get("target_id"))) != item.get("status")
    ]
    return {
        "state_changes": changed,
        "intersections": len(intersections.get("items") or []),
        "goals_completed": goal_values.count("completed"),
        "goals_blocked": goal_values.count("blocked"),
        "progress_score": changed
        + len(intersections.get("items") or [])
        + sum(value in {"completed", "blocked"} for value in goal_values),
    }


def recommend_step_length(metrics: list[dict], *, model_name: str) -> dict:
    """Recommend only from recorded step metrics for the exact provider model."""
    prior = [
        item
        for item in metrics
        if item.get("model_name") == model_name
        and item.get("step_length")
        in {"auto", "day", "week", "month", "season", "year", "next_beat"}
    ]
    if len(prior) < 3:
        return {
            "status": "insufficient_data",
            "model_name": model_name,
            "sample_count": len(prior),
            "message": "该模型的持久化推进步数不足，暂不推荐步长。",
        }
    grouped: dict[str, list[int]] = defaultdict(list)
    for item in prior:
        grouped[str(item["step_length"])].append(int(item.get("progress_score") or 0))
    best = max(
        grouped,
        key=lambda name: (sum(grouped[name]) / len(grouped[name]), len(grouped[name])),
    )
    return {
        "status": "measured",
        "model_name": model_name,
        "step_length": best,
        "sample_count": len(prior),
        "average_progress": round(sum(grouped[best]) / len(grouped[best]), 2),
    }


def low_progress_advice(metrics: list[dict]) -> dict | None:
    """Offer a longer step after two consecutive stored low-progress results."""
    if len(metrics) < 2:
        return None
    previous, current = metrics[-2:]
    if (
        int(previous.get("progress_score") or 0) != 0
        or int(current.get("progress_score") or 0) != 0
    ):
        return None
    order = ["auto", "day", "week", "month", "season", "year", "next_beat"]
    size = current.get("step_length")
    index = order.index(size) if size in order else 0
    return {
        "kind": "low_progress_two_steps",
        "current_step_length": size,
        "suggested_step_length": order[min(index + 1, len(order) - 1)],
        "evidence_steps": [previous.get("step_id"), current.get("step_id")],
    }
