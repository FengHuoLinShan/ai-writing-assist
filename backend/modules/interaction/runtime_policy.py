"""Versioned RP dispatch: an older worker must not downgrade an Agent task."""

from infrastructure.llm.capabilities import (
    LLM_CAPABILITY_EXECUTION_KEY,
    LLM_CAPABILITY_SNAPSHOT_KEY,
    capability_from_execution_snapshot,
    resolve_llm_capability_profile,
)

LEGACY_STORY_TASK = "interaction_story_generate"
AGENT_STORY_TASK = "interaction_agent_story_generate"
STORY_TASK_TYPES = {LEGACY_STORY_TASK, AGENT_STORY_TASK}
ANONYMOUS_RP_SNAPSHOT_VERSION = "anonymous-rp-v1"
ANONYMOUS_RP_BASE_URL = "https://api.deepseek.com"
ANONYMOUS_RP_MODEL = "deepseek-v4-flash"


def anonymous_rp_execution_snapshot() -> dict:
    capability = resolve_llm_capability_profile("deepseek", ANONYMOUS_RP_MODEL)
    return {
        "version": ANONYMOUS_RP_SNAPSHOT_VERSION,
        "anonymous_rp": True,
        "profile": {
            "provider_id": "deepseek",
            "model": ANONYMOUS_RP_MODEL,
            "base_url_host": "api.deepseek.com",
        },
        LLM_CAPABILITY_SNAPSHOT_KEY: capability.to_snapshot(),
    }


def is_anonymous_rp_snapshot(snapshot: dict) -> bool:
    profile = snapshot.get("profile") if isinstance(snapshot, dict) else None
    return bool(
        snapshot.get("version") == ANONYMOUS_RP_SNAPSHOT_VERSION
        and snapshot.get("anonymous_rp") is True
        and isinstance(profile, dict)
        and profile.get("provider_id") == "deepseek"
        and profile.get("model") == ANONYMOUS_RP_MODEL
    )


def anonymous_rp_execution_settings(snapshot: dict) -> dict:
    if not is_anonymous_rp_snapshot(snapshot):
        raise ValueError("Anonymous RP execution snapshot is invalid")
    capability = capability_from_execution_snapshot(snapshot)
    return {
        "llm": {
            "provider_id": "deepseek",
            "base_url": ANONYMOUS_RP_BASE_URL,
            "model": ANONYMOUS_RP_MODEL,
            "timeout": capability.interaction_timeout_seconds,
            "max_tokens": capability.story_output_tokens,
            "temperature": 0.8,
        },
        LLM_CAPABILITY_EXECUTION_KEY: capability.to_snapshot(),
    }


def clear_private_agent_state(attempt):
    """Closed attempts retain usage and citations, never resumable model messages."""
    checkpoint = getattr(attempt, "agent_checkpoint_json", None)
    if checkpoint:
        preserved = {
            "budget": checkpoint.get("budget", {}),
            "evidence_receipts": checkpoint.get("evidence_receipts")
            or [
                {key: value for key, value in ref.items() if key != "text"}
                for ref in (checkpoint.get("references") or {}).values()
            ],
        }
        knowledge_hold = checkpoint.get("knowledge_hold")
        if isinstance(knowledge_hold, dict) and knowledge_hold:
            # ADR-0025：失败/关闭的 attempt 保留私有 hold 记录（正文与回执
            # 不展示、不经 API 返回），供排查与审计。
            preserved["knowledge_hold"] = knowledge_hold
        attempt.agent_checkpoint_json = preserved


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
