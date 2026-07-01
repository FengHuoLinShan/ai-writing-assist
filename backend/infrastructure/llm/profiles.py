"""Project-level LLM profile helpers.

The profile shape is intentionally OpenAI-compatible. Concrete suppliers vary
mostly by base URL and model name, so the provider layer can stay small while
the UI gives users useful presets.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LLM_SETTINGS_KEY = "llm"
LLM_API_KEY_FIELD = "api_key"


PROVIDER_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "category": "直连供应商",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "description": "DeepSeek OpenAI-compatible API",
        "docs_url": "https://api-docs.deepseek.com/",
    },
    {
        "id": "kimi",
        "name": "Kimi / Moonshot",
        "category": "直连供应商",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "description": "Moonshot Kimi OpenAI-compatible API",
        "docs_url": "https://platform.moonshot.cn/docs",
    },
    {
        "id": "mimo",
        "name": "MiMo",
        "category": "直连供应商",
        "base_url": "",
        "default_model": "",
        "models": [],
        "description": "MiMo 兼容接口；请按服务商控制台填写 Base URL 与模型名",
        "docs_url": "",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "category": "中转站",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "deepseek/deepseek-chat-v3-0324",
        "models": [
            "deepseek/deepseek-chat-v3-0324",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o-mini",
        ],
        "description": "OpenRouter OpenAI-compatible relay",
        "docs_url": "https://openrouter.ai/docs/quickstart",
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "category": "中转站",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1"],
        "description": "SiliconFlow OpenAI-compatible API",
        "docs_url": "https://docs.siliconflow.cn/",
    },
    {
        "id": "volcengine-ark",
        "name": "火山方舟",
        "category": "中转站",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "",
        "models": [],
        "description": "火山方舟 OpenAI-compatible API；模型名使用控制台 Endpoint ID",
        "docs_url": "https://www.volcengine.com/docs/82379",
    },
    {
        "id": "aihubmix",
        "name": "AiHubMix",
        "category": "中转站",
        "base_url": "https://aihubmix.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "claude-3-5-sonnet-20241022"],
        "description": "AiHubMix OpenAI-compatible relay",
        "docs_url": "",
    },
    {
        "id": "openai-compatible",
        "name": "自定义 OpenAI 兼容接口",
        "category": "自定义",
        "base_url": "",
        "default_model": "",
        "models": [],
        "description": "适用于 One API、New API、LiteLLM 等 OpenAI-compatible 网关",
        "docs_url": "",
    },
]


def list_provider_templates() -> list[dict[str, Any]]:
    """Return a defensive copy of user-facing provider presets."""
    return deepcopy(PROVIDER_TEMPLATES)


def sanitize_project_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Remove write-only LLM secrets from a project settings payload."""
    cleaned = deepcopy(settings or {})
    llm = cleaned.get(LLM_SETTINGS_KEY)
    if isinstance(llm, dict):
        api_key = llm.pop(LLM_API_KEY_FIELD, None)
        llm["api_key_configured"] = bool(api_key) or bool(
            llm.get("api_key_configured")
        )
    return cleaned


def get_llm_profile(settings: dict[str, Any] | None) -> dict[str, Any]:
    llm = (settings or {}).get(LLM_SETTINGS_KEY)
    return deepcopy(llm) if isinstance(llm, dict) else {}


def sanitize_llm_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = deepcopy(profile or {})
    api_key = cleaned.pop(LLM_API_KEY_FIELD, None)
    cleaned["api_key_configured"] = bool(api_key) or bool(
        cleaned.get("api_key_configured")
    )
    return cleaned
