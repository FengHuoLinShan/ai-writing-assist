"""Source/model admission defaults, independent from frozen execution context."""

import json
from dataclasses import dataclass

from core.config import get_settings


@dataclass(frozen=True)
class ModelLimits:
    concurrency: int = 8
    rpm: int = 0
    input_budget_tokens: int | None = None


def model_source(provider_id: str) -> str:
    return "subscription" if provider_id == "codex" else "api"


def confirmed_scope_eligible(snapshot: dict | None) -> bool:
    from infrastructure.llm.capabilities import capability_from_execution_snapshot

    profile = (snapshot or {}).get("profile") or {}
    if (profile.get("provider_id"), profile.get("model")) != (
        "codex",
        "gpt-6-luna",
    ) or profile.get("connection_verified") is not True:
        return False
    capability = capability_from_execution_snapshot(snapshot)
    return capability.default_input_budget_tokens is not None


def get_model_limits(provider_id: str, model: str, *, settings=None) -> ModelLimits:
    settings = settings or get_settings()
    try:
        values = json.loads(getattr(settings, "llm_model_limits_json", "{}"))
        if not isinstance(values, dict):
            raise ValueError
        for key, value in values.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError
            if key != "default":
                source, provider, selected_model = key.split("/", 2)
                if (
                    source != model_source(provider)
                    or not provider
                    or provider == "*"
                    or not selected_model
                    or any(part != part.strip() for part in (provider, selected_model))
                    or ("*" in selected_model and selected_model != "*")
                ):
                    raise ValueError
            if set(value) - {"concurrency", "rpm", "input_budget_tokens"}:
                raise ValueError
            for field, number in value.items():
                if type(number) is not int or number < (0 if field == "rpm" else 1):
                    raise ValueError
        key = f"{model_source(provider_id)}/{provider_id}/{model}"
        configured = {}
        for entry in ("default", f"{model_source(provider_id)}/{provider_id}/*", key):
            configured.update(values.get(entry, {}))
        return ModelLimits(**configured)
    except (ValueError, TypeError) as error:
        raise ValueError("LLM_MODEL_LIMITS_JSON contains invalid model limits") from error
