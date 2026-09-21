"""Conservative stable identity, explicit dispositions and within-tier ranking."""

from datetime import UTC, datetime

from infrastructure.llm.collaboration import content_hash


def stable_issue_key(capability, audience, anchor, question_kind):
    return content_hash(["forecast_v1", capability, audience, anchor, question_kind])


def assessment_hash(payload, dependencies):
    return content_hash(
        {
            "protocol": "forecast_v1",
            "payload": payload,
            "dependencies": sorted(
                dependencies, key=lambda value: value["dependency_key"]
            ),
        }
    )


def notice_key(novel_id, audience, issue_key):
    return content_hash([novel_id, audience, issue_key])


def hidden_by_decision(notice, *, now=None, event=None):
    if notice is None:
        return False
    decision = (notice.result_ref_json or {}).get("forecast_v1", {})
    if decision.get("disposition") in {"as_ordinary_detail", "not_this_direction"}:
        return True
    if notice.status == "dismissed":
        return True
    if notice.status != "snoozed":
        return False
    condition = decision.get("wake_condition") or {"kind": "manual_reopen"}
    if condition["kind"] == "at_time":
        return datetime.fromisoformat(condition["at"]) > (now or datetime.now(UTC))
    if not event:
        return True
    if condition["kind"] == "object_reappears":
        return not (
            event.get("kind") == "object_reappears"
            and event.get("object_id") == condition["object_id"]
            and event.get("previous_event_token") == condition["after_event_token"]
            and event.get("event_token") != condition["after_event_token"]
        )
    return not (
        event.get("kind") == condition["kind"]
        and event.get("target_id") == condition.get("target_id")
    )


def rank_key(candidate):
    features = candidate.payload_json.get("ranking", {})
    score = sum(
        weight * int(features.get(key, 0))
        for key, weight in {
            "window": 4,
            "task_help": 3,
            "explicit_relevance": 2,
            "evidence": 1,
            "executable": 1,
            "effort": -2,
            "narrative_lockin": -2,
            "repeat": -2,
        }.items()
    )
    return (
        {"attention": 0, "next": 1, "watch": 2}[candidate.tier],
        -score,
        candidate.issue_key,
    )
