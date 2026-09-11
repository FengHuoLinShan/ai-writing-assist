from __future__ import annotations

import pytest

from infrastructure.llm.capabilities import (
    LLM_CAPABILITY_EXECUTION_KEY,
    LLM_CAPABILITY_SNAPSHOT_KEY,
    LLMCapabilityError,
    capability_from_execution_settings,
    capability_from_execution_snapshot,
    resolve_llm_capability_profile,
)


def test_deepseek_capability_is_deterministic_and_bounded() -> None:
    profile = resolve_llm_capability_profile("deepseek", "deepseek-v4-flash")

    assert profile.context_limit_tokens == 1_048_576
    assert profile.hard_input_tokens == 400_000
    assert profile.compact_trigger_tokens == 360_000
    assert profile.summary_input_ceiling_tokens == 256_000
    assert profile.to_snapshot() == profile.to_snapshot()

    canonical = resolve_llm_capability_profile("deepseek", "deepseek-flash")
    assert canonical.model == "deepseek-flash"
    assert canonical.hard_input_tokens == profile.hard_input_tokens
    assert canonical.interaction_reasoning_effort == "max"


def test_unknown_model_uses_short_fallback() -> None:
    profile = resolve_llm_capability_profile("kimi", "moonshot-v1-8k")

    assert profile.calibration_status == "unknown_fallback"
    assert profile.hard_input_tokens == 24_000
    assert profile.story_output_tokens == 4_096


def test_capability_snapshot_rejects_tamper_and_provider_mismatch() -> None:
    frozen = resolve_llm_capability_profile(
        "deepseek",
        "deepseek-v4-flash",
    ).to_snapshot()
    snapshot = {
        "profile": {
            "provider_id": "deepseek",
            "model": "deepseek-v4-flash",
        },
        LLM_CAPABILITY_SNAPSHOT_KEY: frozen,
    }
    assert capability_from_execution_snapshot(snapshot).hard_input_tokens == 400_000
    assert (
        capability_from_execution_settings(
            {
                "llm": snapshot["profile"],
                LLM_CAPABILITY_EXECUTION_KEY: frozen,
            }
        ).hard_input_tokens
        == 400_000
    )

    tampered = {**frozen, "hard_input_tokens": 1}
    snapshot[LLM_CAPABILITY_SNAPSHOT_KEY] = tampered
    with pytest.raises(LLMCapabilityError, match="hash mismatch"):
        capability_from_execution_snapshot(snapshot)

    snapshot[LLM_CAPABILITY_SNAPSHOT_KEY] = frozen
    snapshot["profile"] = {"provider_id": "other", "model": "deepseek-v4-flash"}
    with pytest.raises(LLMCapabilityError, match="provider/model mismatch"):
        capability_from_execution_snapshot(snapshot)


def test_legacy_capability_retains_output_and_no_thinking_override():
    from dataclasses import replace

    from infrastructure.llm.capabilities import _stable_hash
    from infrastructure.llm.schemas import LLMMessage
    from modules.interaction.generation import (
        PreparedStoryGeneration,
        rp_timeout_seconds,
        story_request,
    )

    current = resolve_llm_capability_profile("deepseek", "deepseek-v4-flash")
    old = replace(
        current,
        profile_id="deepseek-v4-flash-20260901-v1",
        story_output_tokens=8192,
        see_sea_output_tokens=4096,
        summary_output_tokens=12000,
        interaction_reasoning_effort=None,
        interaction_timeout_seconds=None,
    ).to_snapshot()
    for key in (
        "interaction_reasoning_effort",
        "interaction_timeout_seconds",
        "capability_hash",
    ):
        old.pop(key)
    old["capability_hash"] = _stable_hash(old)
    settings = {
        "llm": {
            "provider_id": "deepseek",
            "model": "deepseek-v4-flash",
            "max_tokens": 8192,
        },
        LLM_CAPABILITY_EXECUTION_KEY: old,
    }
    prepared = PreparedStoryGeneration(
        "novel",
        "journey",
        "attempt",
        "see_sea_continue",
        [LLMMessage(role="user", content="继续")],
        settings,
        "已有正文",
    )
    assert story_request(prepared).max_tokens == 4096
    assert story_request(prepared).extra == {}
    assert rp_timeout_seconds(prepared) is None
    assert current.story_output_tokens == current.summary_output_tokens == 65536
    assert current.interaction_reasoning_effort == "max"
