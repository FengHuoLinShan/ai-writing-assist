"""Frozen model capability budgets for deterministic business workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from infrastructure.stable_hash import stable_hash

LLM_CAPABILITY_SNAPSHOT_KEY = "llm_capability_profile"
LLM_CAPABILITY_EXECUTION_KEY = "_llm_capability_profile"
LLM_CAPABILITY_VERSION = "llm-capability-v1"


class LLMCapabilityError(ValueError):
    """Raised when a frozen model capability profile is missing or tampered."""


@dataclass(frozen=True)
class LLMCapabilityProfile:
    profile_id: str
    provider_id: str
    model: str
    context_limit_tokens: int
    verified_input_ceiling_tokens: int
    normal_input_tokens: int
    compact_trigger_tokens: int
    summary_input_ceiling_tokens: int
    story_output_tokens: int
    see_sea_output_tokens: int
    summary_output_tokens: int
    safety_margin_tokens: int
    calibration_status: str
    official_spec_url: str | None = None
    spec_verified_on: str | None = None
    interaction_reasoning_effort: str | None = None
    interaction_timeout_seconds: int | None = None
    declared_input_ceiling_tokens: int | None = None
    default_input_budget_tokens: int | None = None
    native_auto_compact_tokens: int | None = None
    token_estimation_method: str | None = None
    structured_output: str | None = "unverified"
    """json/response_format 支持声明：supported / unverified / unsupported。

    未登记模型默认 unverified；旧快照的 None 也表示未校准。三态语义：
    supported 与 unverified 的结构化调用保持既有行为（发送 provider
    json_object，尊重调用方预填）；unsupported 一律失败关闭，调用方预填
    response_format 不能绕过。unverified 只在 B5 路由候选资格上 fail-closed
    （modules/project/model_routing.verified_secondary_models）。"""

    @property
    def hard_input_tokens(self) -> int:
        return min(
            self.declared_input_ceiling_tokens or self.verified_input_ceiling_tokens,
            self.context_limit_tokens
            - max(self.story_output_tokens, self.summary_output_tokens)
            - self.safety_margin_tokens,
        )

    def validate(self) -> LLMCapabilityProfile:
        if self.interaction_reasoning_effort is not None and (
            self.provider_id != "deepseek"
            or self.model not in {"deepseek-flash", "deepseek-v4-flash"}
            or self.interaction_reasoning_effort not in {"high", "max"}
            or self.interaction_timeout_seconds != 900
        ):
            raise LLMCapabilityError("Unsupported RP execution policy")
        if (
            self.interaction_reasoning_effort is None
            and self.interaction_timeout_seconds is not None
        ):
            raise LLMCapabilityError("RP timeout requires a frozen thinking policy")
        positive = (
            self.context_limit_tokens,
            self.normal_input_tokens,
            self.compact_trigger_tokens,
            self.summary_input_ceiling_tokens,
            self.story_output_tokens,
            self.see_sea_output_tokens,
            self.summary_output_tokens,
            self.safety_margin_tokens,
        )
        if self.verified_input_ceiling_tokens < 0:
            raise LLMCapabilityError("Verified input ceiling cannot be negative")
        if self.default_input_budget_tokens is not None and not (
            0 < self.default_input_budget_tokens <= self.hard_input_tokens
        ):
            raise LLMCapabilityError("Configured input exceeds the context budget")
        if any(value <= 0 for value in positive):
            raise LLMCapabilityError("LLM capability budgets must be positive")
        if not (
            self.normal_input_tokens
            <= self.compact_trigger_tokens
            < self.hard_input_tokens
        ):
            raise LLMCapabilityError("LLM capability input tiers are invalid")
        if self.summary_input_ceiling_tokens > self.hard_input_tokens:
            raise LLMCapabilityError("LLM summary input exceeds the hard input budget")
        return self

    def to_snapshot(self) -> dict[str, Any]:
        fields = asdict(self)
        for key in (
            "declared_input_ceiling_tokens",
            "default_input_budget_tokens",
            "native_auto_compact_tokens",
            "token_estimation_method",
        ):
            if fields[key] is None:
                fields.pop(key)
        payload = {"version": LLM_CAPABILITY_VERSION, **fields}
        payload["capability_hash"] = _stable_hash(payload)
        return payload


def _stable_hash(value: Any) -> str:
    return stable_hash(value, stringify_unknown=False)


_DEEPSEEK_V4_FLASH = LLMCapabilityProfile(
    profile_id="deepseek-v4-flash-rp-max-20260908-v2",
    provider_id="deepseek",
    model="deepseek-v4-flash",
    context_limit_tokens=1_048_576,
    verified_input_ceiling_tokens=400_000,
    normal_input_tokens=256_000,
    compact_trigger_tokens=360_000,
    summary_input_ceiling_tokens=256_000,
    story_output_tokens=65_536,
    see_sea_output_tokens=65_536,
    summary_output_tokens=65_536,
    safety_margin_tokens=8_192,
    calibration_status="verified_dev",
    official_spec_url="https://api-docs.deepseek.com/quick_start/pricing/",
    spec_verified_on="2026-09-01",
    interaction_reasoning_effort="max",
    interaction_timeout_seconds=900,
    # DeepSeek 官方 API 支持 response_format={"type":"json_object"}
    # （https://api-docs.deepseek.com/guides/json_mode，2026-09 校准）。
    structured_output="supported",
).validate()

_DEEPSEEK_FLASH = LLMCapabilityProfile(
    **{
        **asdict(_DEEPSEEK_V4_FLASH),
        "profile_id": "deepseek-flash-rp-max-20260910-v1",
        "model": "deepseek-flash",
        "spec_verified_on": "2026-09-10",
    }
).validate()


def _codex_luna_profile():
    from infrastructure.llm.model_limits import get_model_limits
    from infrastructure.llm.token_estimation import token_estimation_method

    budget = get_model_limits("codex", "gpt-6-luna").input_budget_tokens or 500_000
    return LLMCapabilityProfile(
        profile_id="codex-luna-context-20261014-v1",
        provider_id="codex",
        model="gpt-6-luna",
        context_limit_tokens=1_050_000,
        verified_input_ceiling_tokens=0,
        declared_input_ceiling_tokens=837_500,
        default_input_budget_tokens=budget,
        normal_input_tokens=min(budget, 500_000),
        compact_trigger_tokens=600_000,
        summary_input_ceiling_tokens=min(budget, 500_000),
        story_output_tokens=128_000,
        see_sea_output_tokens=128_000,
        summary_output_tokens=64_000,
        safety_margin_tokens=32_000,
        native_auto_compact_tokens=800_000,
        token_estimation_method=token_estimation_method("gpt-6-luna"),
        calibration_status="official_spec_runtime_unverified",
        official_spec_url="https://developers.openai.com/api/docs/models/gpt-6-luna",
        spec_verified_on="2026-10-14",
        structured_output="supported",
    ).validate()


def _short_fallback(
    provider_id: str, model: str, *, legacy: bool = False
) -> LLMCapabilityProfile:
    return LLMCapabilityProfile(
        profile_id=("legacy-unfrozen-short-v1" if legacy else "unknown-short-v1"),
        provider_id=provider_id,
        model=model,
        context_limit_tokens=32_768,
        verified_input_ceiling_tokens=24_000,
        normal_input_tokens=16_000,
        compact_trigger_tokens=20_000,
        summary_input_ceiling_tokens=16_000,
        story_output_tokens=4_096,
        see_sea_output_tokens=4_096,
        summary_output_tokens=4_096,
        safety_margin_tokens=4_096,
        calibration_status="legacy_fallback" if legacy else "unknown_fallback",
    ).validate()


def resolve_llm_capability_profile(
    provider_id: str | None,
    model: str | None,
    *,
    high_quality: bool = False,
) -> LLMCapabilityProfile:
    provider = str(provider_id or "")
    model_name = str(model or "")
    if (provider, model_name) == ("codex", "gpt-6-luna"):
        return _codex_luna_profile()
    for profile in (_DEEPSEEK_FLASH, _DEEPSEEK_V4_FLASH):
        if (provider, model_name) == (profile.provider_id, profile.model):
            if not high_quality:
                profile = replace(
                    profile,
                    profile_id=f"{model_name}-rp-balanced-20260921-v1",
                    normal_input_tokens=128000,
                    compact_trigger_tokens=192000,
                    interaction_reasoning_effort="high",
                    calibration_status="historical_evidence_tuning",
                )
            break
    else:
        profile = _short_fallback(provider, model_name)
    from infrastructure.llm.model_limits import get_model_limits
    from infrastructure.llm.token_estimation import token_estimation_method

    budget = get_model_limits(provider, model_name).input_budget_tokens
    if budget is not None:
        profile = replace(
            profile,
            default_input_budget_tokens=budget,
            token_estimation_method=token_estimation_method(model_name),
        )
    return profile.validate()


def _profile_from_snapshot(
    value: dict[str, Any],
    *,
    provider_id: str,
    model: str,
) -> LLMCapabilityProfile:
    expected_hash = str(value.get("capability_hash") or "")
    unsigned = {key: item for key, item in value.items() if key != "capability_hash"}
    if value.get("version") != LLM_CAPABILITY_VERSION:
        raise LLMCapabilityError("Unsupported LLM capability profile version")
    if not expected_hash or _stable_hash(unsigned) != expected_hash:
        raise LLMCapabilityError("LLM capability profile hash mismatch")
    fields = {key: item for key, item in unsigned.items() if key != "version"}
    try:
        profile = LLMCapabilityProfile(**fields).validate()
    except (TypeError, ValueError) as exc:
        raise LLMCapabilityError("LLM capability profile is invalid") from exc
    if profile.provider_id != provider_id or profile.model != model:
        raise LLMCapabilityError("LLM capability profile provider/model mismatch")
    return profile


def capability_from_execution_snapshot(snapshot: dict[str, Any]) -> LLMCapabilityProfile:
    public_profile = snapshot.get("profile")
    public_profile = public_profile if isinstance(public_profile, dict) else {}
    provider_id = str(public_profile.get("provider_id") or "")
    model = str(public_profile.get("model") or "")
    value = snapshot.get(LLM_CAPABILITY_SNAPSHOT_KEY)
    if not isinstance(value, dict):
        return _short_fallback(provider_id, model, legacy=True)
    return _profile_from_snapshot(value, provider_id=provider_id, model=model)


def capability_from_execution_settings(settings: dict[str, Any]) -> LLMCapabilityProfile:
    llm = settings.get("llm")
    llm = llm if isinstance(llm, dict) else {}
    provider_id = str(llm.get("provider_id") or "")
    model = str(llm.get("model") or "")
    value = settings.get(LLM_CAPABILITY_EXECUTION_KEY)
    if not isinstance(value, dict):
        return resolve_llm_capability_profile(
            provider_id,
            model,
            high_quality=(llm.get("extra") or {}).get("reasoning_effort") == "max",
        )
    return _profile_from_snapshot(value, provider_id=provider_id, model=model)


def legacy_capability_snapshot(provider_id: str, model: str) -> dict[str, Any]:
    """Materialize a conservative execution-only profile for old task snapshots."""

    return _short_fallback(provider_id, model, legacy=True).to_snapshot()
