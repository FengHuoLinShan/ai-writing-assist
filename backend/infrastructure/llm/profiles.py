"""Project-level LLM profile helpers.

The profile shape is intentionally OpenAI-compatible. Concrete suppliers vary
mostly by base URL and model name, so the provider layer can stay small while
the UI gives users useful presets.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from infrastructure.llm.secret_store import (
    decrypt_secret,
    secret_configured,
)

LLM_SETTINGS_KEY = "llm"
LLM_API_KEY_FIELD = "api_key"

LLM_SOURCE_PROJECT = "project"
LLM_SOURCE_TEST_OVERRIDE = "test_override"
LLM_SOURCE_DEFAULT = "default"

_DEFAULT_LLM_PROFILE: dict[str, Any] = {
    "provider_id": "deepseek",
    "label": "DeepSeek",
    LLM_API_KEY_FIELD: "",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "timeout": 180,
    "max_tokens": 4096,
    "temperature": 0.3,
    "top_p": None,
    "extra": {},
}

_NUMERIC_FIELDS = {"timeout", "max_tokens"}
_FLOAT_FIELDS = {"temperature", "top_p"}

_DEFAULT_PROVIDER_PARAMETERS: dict[str, Any] = {
    "timeout": 180,
    "max_tokens": 4096,
    "temperature": 0.3,
    "top_p": None,
    "extra": {},
}


def _template(
    provider_id: str,
    name: str,
    base_url: str,
    description: str,
    *,
    default_model: str = "",
    models: list[str] | None = None,
    docs_url: str = "",
    category: str = "直连供应商",
) -> dict[str, Any]:
    return {
        "id": provider_id,
        "name": name,
        "category": category,
        "base_url": base_url,
        "default_model": default_model,
        "models": list(models or []),
        "default_parameters": deepcopy(_DEFAULT_PROVIDER_PARAMETERS),
        "description": description,
        "docs_url": docs_url,
    }


PROVIDER_TEMPLATES: list[dict[str, Any]] = [
    _template(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com",
        "DeepSeek OpenAI-compatible API",
        default_model="deepseek-v4-flash",
        models=[
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
        ],
        docs_url="https://api-docs.deepseek.com/",
    ),
    _template(
        "kimi",
        "Kimi / Moonshot",
        "https://api.moonshot.cn/v1",
        "Moonshot Kimi OpenAI-compatible API",
        default_model="kimi-k2.6",
        models=[
            "kimi-k2.7-code",
            "kimi-k2.7-code-highspeed",
            "kimi-k2.6",
            "kimi-k2.5",
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
        docs_url="https://platform.kimi.com/docs/overview",
    ),
    _template(
        "qwen-dashscope",
        "通义千问 / 阿里云百炼",
        ("https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"),
        "阿里云百炼 OpenAI 兼容模式；请将 {WorkspaceId} 替换为业务空间 ID",
        default_model="qwen-plus",
        models=[
            "qwen-plus",
            "qwen-max",
            "qwen-turbo",
            "qwen-long",
            "qwen-coder-plus",
            "qwen3-coder-plus",
        ],
        docs_url=(
            "https://help.aliyun.com/zh/model-studio/"
            "compatibility-of-openai-with-dashscope"
        ),
    ),
    _template(
        "zhipu",
        "智谱 GLM",
        "https://open.bigmodel.cn/api/paas/v4",
        "智谱 OpenAI-compatible API",
        default_model="glm-4-plus",
        models=["glm-4-plus", "glm-4", "glm-4-air", "glm-4-flash"],
        docs_url="https://docs.bigmodel.cn/",
    ),
    _template(
        "baichuan",
        "百川智能",
        "https://api.baichuan-ai.com/v1",
        "百川 OpenAI-compatible API；如控制台显示不同端点，以控制台为准",
        default_model="Baichuan4",
        models=["Baichuan4", "Baichuan3-Turbo", "Baichuan3-Turbo-128k"],
        docs_url="https://platform.baichuan-ai.com/docs",
    ),
    _template(
        "minimax",
        "MiniMax",
        "https://api.minimax.chat/v1",
        "MiniMax OpenAI-compatible API；模型名可按控制台调整",
        default_model="MiniMax-M1",
        models=["MiniMax-M1", "abab6.5s-chat", "abab6.5g-chat"],
        docs_url="https://platform.minimaxi.com/document",
    ),
    _template(
        "hunyuan",
        "腾讯混元",
        "https://api.hunyuan.cloud.tencent.com/v1",
        "腾讯混元 OpenAI-compatible API；模型名可按控制台调整",
        default_model="hunyuan-turbos-latest",
        models=[
            "hunyuan-turbos-latest",
            "hunyuan-turbo-latest",
            "hunyuan-lite",
        ],
        docs_url="https://cloud.tencent.com/document/product/1729",
    ),
    _template(
        "qianfan",
        "百度千帆 / 文心",
        "https://qianfan.baidubce.com/v2",
        "百度千帆 OpenAI-compatible API；模型名可按控制台调整",
        default_model="ernie-4.5-turbo-128k",
        models=[
            "ernie-4.5-turbo-128k",
            "ernie-4.5-turbo-32k",
            "ernie-4.0-turbo-8k",
        ],
        docs_url="https://cloud.baidu.com/doc/WENXINWORKSHOP/index.html",
    ),
    _template(
        "stepfun",
        "阶跃星辰 StepFun",
        "https://api.stepfun.com/v1",
        "阶跃星辰 OpenAI-compatible API；模型名可按控制台调整",
        default_model="step-2-16k",
        models=["step-2-16k", "step-1-8k", "step-1-32k", "step-1-128k"],
        docs_url="https://platform.stepfun.com/docs",
    ),
    _template(
        "yi",
        "零一万物 Yi",
        "https://api.lingyiwanwu.com/v1",
        "零一万物 OpenAI-compatible API；模型名可按控制台调整",
        default_model="yi-large",
        models=["yi-large", "yi-medium", "yi-spark", "yi-large-turbo"],
        docs_url="https://platform.lingyiwanwu.com/docs",
    ),
    _template(
        "mimo",
        "MiMo",
        "",
        "MiMo 兼容接口；请按服务商控制台填写 Base URL 与模型名",
    ),
    _template(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "OpenRouter OpenAI-compatible relay",
        default_model="deepseek/deepseek-chat-v3-0324",
        models=[
            "deepseek/deepseek-chat-v3-0324",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o-mini",
        ],
        docs_url="https://openrouter.ai/docs/quickstart",
        category="中转站",
    ),
    _template(
        "siliconflow",
        "硅基流动 SiliconFlow",
        "https://api.siliconflow.cn/v1",
        "SiliconFlow OpenAI-compatible API",
        default_model="deepseek-ai/DeepSeek-V3.2",
        models=[
            "deepseek-ai/DeepSeek-V3.2",
            "Pro/deepseek-ai/DeepSeek-V3.2",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen3-32B",
            "Pro/zai-org/GLM-4.7",
        ],
        docs_url="https://docs.siliconflow.cn/",
        category="中转站",
    ),
    _template(
        "volcengine-ark",
        "火山方舟",
        "https://ark.cn-beijing.volces.com/api/v3",
        "火山方舟 OpenAI-compatible API；模型名使用控制台 Endpoint ID",
        docs_url="https://www.volcengine.com/docs/82379",
        category="中转站",
    ),
    _template(
        "aihubmix",
        "AiHubMix",
        "https://aihubmix.com/v1",
        "AiHubMix OpenAI-compatible relay",
        default_model="gpt-4o-mini",
        models=["gpt-4o-mini", "claude-3-5-sonnet-20241022"],
        category="中转站",
    ),
    _template(
        "openai-compatible",
        "自定义 OpenAI 兼容接口",
        "",
        "适用于 One API、New API、LiteLLM 等 OpenAI-compatible 网关",
        category="自定义",
    ),
]


@dataclass(frozen=True)
class ResolvedLLMProfile:
    """Effective OpenAI-compatible LLM profile with field-level provenance."""

    provider_id: str = "deepseek"
    label: str = "DeepSeek"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: int = 60
    max_tokens: int = 4096
    temperature: float | None = 0.3
    top_p: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def provider_kwargs(self) -> dict[str, Any]:
        """Return provider construction kwargs without unset values."""
        kwargs: dict[str, Any] = {}
        if self.api_key:
            kwargs[LLM_API_KEY_FIELD] = self.api_key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.model:
            kwargs["default_model"] = self.model
        if self.timeout:
            kwargs["timeout"] = int(self.timeout)
        return kwargs

    def request_defaults(self) -> dict[str, Any]:
        """Defaults for LLMCallRequest fields."""
        defaults: dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(self.max_tokens),
        }
        if self.temperature is not None:
            defaults["temperature"] = self.temperature
        if self.top_p is not None:
            defaults["top_p"] = self.top_p
        return defaults

    def sanitized_summary(self) -> dict[str, Any]:
        """Return log/API-safe profile metadata. Never includes API key."""
        return {
            "provider_id": self.provider_id,
            "label": self.label,
            "model": self.model,
            "base_url_host": _base_url_host(self.base_url),
            "timeout": int(self.timeout),
            "max_tokens": int(self.max_tokens),
            "temperature": self.temperature,
            "top_p": self.top_p,
            "api_key_configured": bool(self.api_key),
            "sources": dict(self.sources),
            "extra_keys": sorted(self.extra.keys()),
        }


def list_provider_templates() -> list[dict[str, Any]]:
    """Return a defensive copy of user-facing provider presets."""
    return deepcopy(PROVIDER_TEMPLATES)


def default_llm_profile() -> dict[str, Any]:
    """Return code-level defaults used when DB-backed config is missing."""
    return deepcopy(_DEFAULT_LLM_PROFILE)


def sanitize_project_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Remove write-only LLM secrets from a project settings payload."""
    cleaned = deepcopy(settings or {})
    llm = cleaned.get(LLM_SETTINGS_KEY)
    if isinstance(llm, dict):
        api_key = llm.pop(LLM_API_KEY_FIELD, None)
        llm["api_key_configured"] = secret_configured(api_key) or bool(
            llm.get("api_key_configured")
        )
    return cleaned


def get_llm_profile(settings: dict[str, Any] | None) -> dict[str, Any]:
    llm = (settings or {}).get(LLM_SETTINGS_KEY)
    return deepcopy(llm) if isinstance(llm, dict) else {}


def get_runtime_llm_profile(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Return the project LLM profile with encrypted secrets decrypted."""
    profile = get_llm_profile(settings)
    api_key = profile.get(LLM_API_KEY_FIELD)
    if secret_configured(api_key):
        profile[LLM_API_KEY_FIELD] = decrypt_secret(api_key)
    return profile


def sanitize_llm_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = deepcopy(profile or {})
    api_key = cleaned.pop(LLM_API_KEY_FIELD, None)
    cleaned["api_key_configured"] = secret_configured(api_key) or bool(
        cleaned.get("api_key_configured")
    )
    return cleaned


def resolve_llm_profile(
    project_settings: dict[str, Any] | None = None,
    env_settings: Any | None = None,
    test_overrides: dict[str, Any] | None = None,
) -> ResolvedLLMProfile:
    """Resolve the effective business LLM profile.

    Precedence is: project ``settings["llm"]`` > explicit test overrides
    > code defaults. ``env_settings`` is accepted only for older callers and is
    intentionally ignored for business LLM profile fields.
    """
    values = deepcopy(_DEFAULT_LLM_PROFILE)
    sources = {field_name: LLM_SOURCE_DEFAULT for field_name in values}

    _merge_profile_values(
        values,
        sources,
        _normalize_override_payload(test_overrides),
        LLM_SOURCE_TEST_OVERRIDE,
    )
    _merge_profile_values(
        values,
        sources,
        _normalize_project_profile(project_settings),
        LLM_SOURCE_PROJECT,
    )

    return ResolvedLLMProfile(
        provider_id=str(values.get("provider_id") or "deepseek"),
        label=str(
            values.get("label")
            or _template_name(str(values.get("provider_id") or ""))
            or "DeepSeek"
        ),
        api_key=str(values.get(LLM_API_KEY_FIELD) or ""),
        base_url=str(values.get("base_url") or ""),
        model=str(values.get("model") or ""),
        timeout=max(int(values.get("timeout") or 60), 1),
        max_tokens=max(int(values.get("max_tokens") or 4096), 1),
        temperature=_optional_float(values.get("temperature")),
        top_p=_optional_float(values.get("top_p")),
        extra=deepcopy(values.get("extra") or {}),
        sources=sources,
    )


def sanitize_resolved_llm_profile(profile: ResolvedLLMProfile) -> dict[str, Any]:
    """Return the standard API/log-safe summary for a resolved profile."""
    return profile.sanitized_summary()


def _normalize_override_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        field_name = _override_key_to_field(str(key))
        if field_name:
            normalized[field_name] = value
    return normalized


def _normalize_project_profile(project_settings: dict[str, Any] | None) -> dict[str, Any]:
    profile = get_runtime_llm_profile(project_settings)
    if not profile:
        return {}

    normalized = dict(profile)
    provider_id = normalized.get("provider_id") or normalized.get("provider")
    if provider_id:
        normalized["provider_id"] = provider_id
        template = _provider_template(str(provider_id))
        if template is not None:
            normalized.setdefault("label", template.get("name"))
            normalized.setdefault("base_url", template.get("base_url"))
            normalized.setdefault("model", template.get("default_model"))
            defaults = template.get("default_parameters")
            if isinstance(defaults, dict):
                for key in ("timeout", "max_tokens", "temperature", "top_p", "extra"):
                    normalized.setdefault(key, defaults.get(key))
    if normalized.get("model") is None and normalized.get("default_model") is not None:
        normalized["model"] = normalized.get("default_model")
    parameters = normalized.get("parameters")
    if isinstance(parameters, dict):
        for key in ("timeout", "max_tokens", "temperature", "top_p", "extra"):
            normalized.setdefault(key, parameters.get(key))
    return normalized


def _merge_profile_values(
    values: dict[str, Any],
    sources: dict[str, str],
    payload: dict[str, Any],
    source: str,
) -> None:
    for field_name in (
        "provider_id",
        "label",
        LLM_API_KEY_FIELD,
        "base_url",
        "model",
        "timeout",
        "max_tokens",
        "temperature",
        "top_p",
        "extra",
    ):
        if field_name in payload:
            _set_profile_field(
                values,
                sources,
                field_name,
                payload.get(field_name),
                source,
            )


def _set_profile_field(
    values: dict[str, Any],
    sources: dict[str, str],
    field_name: str,
    raw_value: Any,
    source: str,
) -> None:
    if raw_value is None:
        return
    if isinstance(raw_value, str) and raw_value.strip() == "":
        return
    value = _coerce_profile_value(field_name, raw_value)
    if value is None and field_name not in {"temperature", "top_p"}:
        return
    if field_name == "extra" and not isinstance(value, dict):
        return
    values[field_name] = value
    sources[field_name] = source


def _coerce_profile_value(field_name: str, value: Any) -> Any:
    if field_name in _NUMERIC_FIELDS:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
    if field_name in _FLOAT_FIELDS:
        return _optional_float(value)
    if field_name == "extra":
        return deepcopy(value) if isinstance(value, dict) else None
    if isinstance(value, str):
        return value.strip()
    return value


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _override_key_to_field(key: str) -> str | None:
    normalized = key.lower()
    if normalized.startswith("llm_"):
        normalized = normalized[4:]
    aliases = {
        "api_key": LLM_API_KEY_FIELD,
        "base_url": "base_url",
        "model": "model",
        "timeout": "timeout",
        "max_tokens": "max_tokens",
        "temperature": "temperature",
        "top_p": "top_p",
        "extra": "extra",
        "provider": "provider_id",
        "provider_id": "provider_id",
        "label": "label",
    }
    return aliases.get(normalized)


def _provider_template(provider_id: str) -> dict[str, Any] | None:
    return next(
        (template for template in PROVIDER_TEMPLATES if template["id"] == provider_id),
        None,
    )


def _template_name(provider_id: str) -> str | None:
    template = _provider_template(provider_id)
    return str(template["name"]) if template is not None else None


def _base_url_host(base_url: str) -> str:
    if not base_url:
        return ""
    return urlparse(base_url).hostname or ""
