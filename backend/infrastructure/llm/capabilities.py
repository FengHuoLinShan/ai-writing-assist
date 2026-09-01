"""Frozen model capability budgets for deterministic business workflows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

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

    @property
    def hard_input_tokens(self) -> int:
        return min(
            self.verified_input_ceiling_tokens,
            self.context_limit_tokens
            - max(self.story_output_tokens, self.summary_output_tokens)
            - self.safety_margin_tokens,
        )

    def validate(self) -> LLMCapabilityProfile:
        positive = (
            self.context_limit_tokens,
            self.verified_input_ceiling_tokens,
            self.normal_input_tokens,
            self.compact_trigger_tokens,
            self.summary_input_ceiling_tokens,
            self.story_output_tokens,
            self.see_sea_output_tokens,
            self.summary_output_tokens,
            self.safety_margin_tokens,
        )
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
        payload = {"version": LLM_CAPABILITY_VERSION, **asdict(self)}
        payload["capability_hash"] = _stable_hash(payload)
        return payload


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_DEEPSEEK_V4_FLASH = LLMCapabilityProfile(
    profile_id="deepseek-v4-flash-20260901-v1",
    provider_id="deepseek",
    model="deepseek-v4-flash",
    context_limit_tokens=1_048_576,
    verified_input_ceiling_tokens=400_000,
    normal_input_tokens=256_000,
    compact_trigger_tokens=360_000,
    summary_input_ceiling_tokens=256_000,
    story_output_tokens=8_192,
    see_sea_output_tokens=4_096,
    summary_output_tokens=12_000,
    safety_margin_tokens=8_192,
    calibration_status="verified_dev",
    official_spec_url="https://api-docs.deepseek.com/quick_start/pricing/",
    spec_verified_on="2026-09-01",
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
) -> LLMCapabilityProfile:
    provider = str(provider_id or "")
    model_name = str(model or "")
    if (provider, model_name) == (
        _DEEPSEEK_V4_FLASH.provider_id,
        _DEEPSEEK_V4_FLASH.model,
    ):
        return _DEEPSEEK_V4_FLASH
    return _short_fallback(provider, model_name)


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
        return resolve_llm_capability_profile(provider_id, model)
    return _profile_from_snapshot(value, provider_id=provider_id, model=model)


def legacy_capability_snapshot(provider_id: str, model: str) -> dict[str, Any]:
    """Materialize a conservative execution-only profile for old task snapshots."""

    return _short_fallback(provider_id, model, legacy=True).to_snapshot()
