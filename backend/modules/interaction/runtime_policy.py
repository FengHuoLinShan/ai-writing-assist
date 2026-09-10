"""Versioned RP dispatch: an older worker must not downgrade an Agent task."""

LEGACY_STORY_TASK = "interaction_story_generate"
AGENT_STORY_TASK = "interaction_agent_story_generate"
STORY_TASK_TYPES = {LEGACY_STORY_TASK, AGENT_STORY_TASK}


def clear_private_agent_state(attempt):
    """Closed attempts retain usage and citations, never resumable model messages."""
    checkpoint = getattr(attempt, "agent_checkpoint_json", None)
    if checkpoint:
        attempt.agent_checkpoint_json = {
            "budget": checkpoint.get("budget", {}),
            "evidence_receipts": checkpoint.get("evidence_receipts")
            or [
                {key: value for key, value in ref.items() if key != "text"}
                for ref in (checkpoint.get("references") or {}).values()
            ],
        }


def agent_story_enabled(snapshot: dict) -> bool:
    policy = snapshot.get("agent_runtime")
    if policy is None:
        return False
    if policy == {"version": "1", "mode": "rp", "allow_web": True}:
        return True
    if (
        isinstance(policy, dict)
        and set(policy) == {"version", "mode", "web_search"}
        and policy["version"] == "2"
        and policy["mode"] == "rp"
    ):
        web = policy["web_search"]
        if web is None or (
            isinstance(web, dict)
            and set(web) == {"protocol", "endpoint_hash"}
            and web["protocol"] == "searxng-v1"
            and isinstance(web["endpoint_hash"], str)
            and len(web["endpoint_hash"]) == 64
        ):
            return True
    raise ValueError("Unsupported frozen RP agent runtime")


def story_task_type(snapshot: dict) -> str:
    return AGENT_STORY_TASK if agent_story_enabled(snapshot) else LEGACY_STORY_TASK
