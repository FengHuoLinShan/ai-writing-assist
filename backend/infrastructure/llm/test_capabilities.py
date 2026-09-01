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


def test_unknown_model_uses_long_context_fallback() -> None:
    profile = resolve_llm_capability_profile("custom", "unknown-model")
    verified = resolve_llm_capability_profile("deepseek", "deepseek-v4-flash")

    # 产品决策:未校验模型假定不弱于已校准档,避免 source-bound 旅程
    # 每轮触发压缩;假定状态与 verified_dev 明确区分。
    assert profile.calibration_status == "unknown_long_context_fallback"
    assert profile.hard_input_tokens == verified.hard_input_tokens
    assert profile.story_output_tokens == verified.story_output_tokens
    assert profile.normal_input_tokens == verified.normal_input_tokens


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
