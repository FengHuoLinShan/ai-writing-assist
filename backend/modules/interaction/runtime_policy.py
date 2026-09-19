"""Versioned RP dispatch: an older worker must not downgrade an Agent task."""

import uuid

from infrastructure.llm.capabilities import (
    LLM_CAPABILITY_EXECUTION_KEY,
    LLM_CAPABILITY_SNAPSHOT_KEY,
    capability_from_execution_snapshot,
    resolve_llm_capability_profile,
)
from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY, read_ai_run_envelope
from infrastructure.llm.workflow_budget import (
    AIRunAuthorizationReason,
    AIRunEnvelope,
)

LEGACY_STORY_TASK = "interaction_story_generate"
AGENT_STORY_TASK = "interaction_agent_story_generate"
_STORY_REQUEST_LIMITS = {
    LEGACY_STORY_TASK: 46,
    AGENT_STORY_TASK: 29,
}
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
            **(
                {"actor_state_refs": checkpoint["actor_state_refs"]}
                if "actor_state_refs" in checkpoint
                else {}
            ),
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
        envelope = checkpoint.get(AI_RUN_ENVELOPE_KEY)
        if isinstance(envelope, dict) and envelope:
            preserved[AI_RUN_ENVELOPE_KEY] = envelope
        attempt.agent_checkpoint_json = preserved


def agent_story_enabled(snapshot: dict) -> bool:
    policy = snapshot.get("agent_runtime")
    if policy is None:
        return False
    if isinstance(policy, dict) and policy.get("version") == "3":
        if set(policy) != {"version", "mode", "web_search", "collaboration"} or policy[
            "collaboration"
        ] != {"protocol": "team_v1", "max_actors": 3}:
            raise ValueError("Unsupported frozen RP collaboration protocol")
        return agent_story_enabled(
            {
                "agent_runtime": {
                    key: value
                    for key, value in {**policy, "version": "2"}.items()
                    if key != "collaboration"
                }
            }
        )
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


def interaction_story_run_request_limit(task: object) -> int:
    """Freeze the historical request ceiling for one RP attempt."""
    return _STORY_REQUEST_LIMITS.get(
        str(getattr(task, "task_type", "")),
        _STORY_REQUEST_LIMITS[LEGACY_STORY_TASK],
    )


def interaction_story_run_id(task: object) -> str:
    """Return the generation attempt identity frozen into story task meta."""
    value = str((getattr(task, "meta", None) or {}).get("attempt_id") or "").strip()
    return str(uuid.UUID(value))


def new_interaction_story_envelope(
    *,
    attempt_id: str,
    novel_id: str,
    task_type: str,
    legacy_untracked: bool = False,
    request_limit: int | None = None,
) -> dict:
    from infrastructure.llm.workflow_budget import new_ai_run_envelope

    return (
        new_ai_run_envelope(
            operation_id=attempt_id,
            run_id=attempt_id,
            root_capability_id="interaction.story_generate",
            novel_id=novel_id,
            request_limit=(
                request_limit
                if request_limit is not None
                else _STORY_REQUEST_LIMITS.get(
                    task_type,
                    _STORY_REQUEST_LIMITS[LEGACY_STORY_TASK],
                )
            ),
            legacy_untracked=legacy_untracked,
        )
        .snapshot()
        .model_dump(mode="json")
    )


async def authorize_interaction_story_continuation(
    attempt: object,
    *,
    task_type: str,
) -> None:
    """Authorize exactly one new RP segment on the existing attempt run."""
    checkpoint = dict(getattr(attempt, "agent_checkpoint_json", None) or {})
    attempt_id = str(getattr(attempt, "id", ""))
    novel_id = str(getattr(attempt, "novel_id", ""))
    segment_limit = _STORY_REQUEST_LIMITS.get(
        task_type,
        _STORY_REQUEST_LIMITS[LEGACY_STORY_TASK],
    )
    continuation_count = int(getattr(attempt, "continuation_count", 0) or 0)
    payload = read_ai_run_envelope(checkpoint.get(AI_RUN_ENVELOPE_KEY))
    legacy_without_envelope = payload is None
    if payload is None:
        payload = read_ai_run_envelope(
            new_interaction_story_envelope(
                attempt_id=attempt_id,
                novel_id=novel_id,
                task_type=task_type,
                legacy_untracked=True,
                # The historical segment is unknowable, not unused. Only the
                # explicit continuation authorization creates spendable room.
                request_limit=0,
            )
        )
    if (
        payload is None
        or payload.run_id != attempt_id
        or payload.operation_id != attempt_id
        or payload.novel_id != novel_id
        or payload.root_capability_id != "interaction.story_generate"
        or continuation_count < 1
        or payload.authorization_revision != continuation_count - 1
        or payload.request_limit
        != (0 if legacy_without_envelope else segment_limit * continuation_count)
    ):
        raise ValueError("interaction continuation run envelope is invalid")
    ledger = AIRunEnvelope(payload)
    await ledger.authorize_additional_requests(
        segment_limit,
        reason=AIRunAuthorizationReason.author_resume,
    )
    checkpoint[AI_RUN_ENVELOPE_KEY] = ledger.snapshot().model_dump(mode="json")
    # AgentRunBudget is a per-handler compatibility guard. A continuation is a
    # new author-authorized handler segment; cumulative cost remains in the run
    # envelope and attempt usage counters.
    checkpoint.pop("budget", None)
    attempt.agent_checkpoint_json = checkpoint
