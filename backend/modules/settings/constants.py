"""Settings module shared constants.

D10: owner_id 占位为 nil UUID，UI 显示 `local` 字样，DB 存 nil UUID。
D12: 全局作者偏好硬编码默认值。
D4: 字段级 DELETE 服务端硬白名单。
"""

from __future__ import annotations

import os
from typing import Any

from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from shared.constants import DEFAULT_LLM_MAX_TOKENS

# Demo owner 占位：nil UUID
LOCAL_OWNER_ID = BOOTSTRAP_ACCOUNT_ID
LOCAL_OWNER_LABEL: str = "local"

# D12 全局作者偏好硬编码默认（global 行不存在或字段 NULL 时回退）
AUTHOR_PREFS_DEFAULTS: dict[str, Any] = {
    "daily_goal": None,  # unset
    "editor_font": "system",
    "default_focus_mode": False,
}

# D23 系统内置 LLM 默认（global 行不存在时回退）
LLM_DEFAULTS_SYSTEM: dict[str, Any] = {
    "provider_id": "deepseek",
    "label": "DeepSeek",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-v4-flash",
    "timeout": 180,
    "max_tokens": DEFAULT_LLM_MAX_TOKENS,
    "temperature": 0.3,
    "top_p": None,
    "extra": {},
    "creative_mode": None,
    "deep_import": None,  # D9 本期永远 NULL
}

ACCOUNT_LLM_PROVIDER_TEMPLATES: dict[str, dict[str, Any]] = {
    "deepseek": {
        "provider_id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "timeout": 180,
        "max_tokens": DEFAULT_LLM_MAX_TOKENS,
        "temperature": 0.3,
        "top_p": None,
        "extra": {},
    },
    "kimi": {
        "provider_id": "kimi",
        "label": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k3",
        "timeout": 180,
        "max_tokens": DEFAULT_LLM_MAX_TOKENS,
        "temperature": 0.3,
        "top_p": None,
        "extra": {},
    },
}

ACCOUNT_LLM_PROVIDER_ORDER: tuple[str, ...] = ("deepseek", "kimi")


def account_llm_provider_enabled(provider_id: str) -> bool:
    """Keep unverified account templates unreachable until their real gate passes."""

    if provider_id == "deepseek":
        return True
    if provider_id == "kimi":
        return os.getenv("ENABLE_ACCOUNT_KIMI_K3", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return False


def enabled_account_llm_provider_order() -> tuple[str, ...]:
    return tuple(
        provider_id
        for provider_id in ACCOUNT_LLM_PROVIDER_ORDER
        if account_llm_provider_enabled(provider_id)
    )

# 字段级 DELETE 白名单
AUTHOR_PREFS_FIELDS: frozenset[str] = frozenset(
    {
        "daily_goal",
        "editor_font",
        "default_focus_mode",
    }
)

# LLM settings 可继承字段（不含 api_key）
LLM_INHERITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "provider_id",
        "label",
        "base_url",
        "model",
        "timeout",
        "max_tokens",
        "temperature",
        "top_p",
        "extra",
        "creative_mode",
        "deep_import",
    }
)

# source 取值
SOURCE_PROJECT = "project"
SOURCE_GLOBAL = "global"
SOURCE_SYSTEM = "system"
SOURCE_UNSET = "unset"

ALL_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_PROJECT,
        SOURCE_GLOBAL,
        SOURCE_SYSTEM,
        SOURCE_UNSET,
    }
)
