"""LLM health checker tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

import infrastructure.llm.health as health_module
from core.config import get_settings
from infrastructure.llm.health import (
    LLMHealthChecker,
    LLMHealthResult,
    check_llm_environment_health,
    check_llm_service_health,
)


@pytest.mark.asyncio
async def test_health_reports_fake_ip_without_proxy() -> None:
    checker = LLMHealthChecker(
        api_key="test-key",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
        trust_env=False,
        proxy_url="",
    )
    checker._resolve_host = AsyncMock(return_value=["198.18.0.102"])  # type: ignore[method-assign]
    checker._check_models = AsyncMock()  # type: ignore[method-assign]
    checker._check_chat = AsyncMock()  # type: ignore[method-assign]

    result = await checker.check()

    assert result.ok is False
    assert result.error_kind == "dns_fake_ip"
    assert result.dns_fake_ip is True
    checker._check_models.assert_not_awaited()
    checker._check_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_reports_success_after_models_and_chat() -> None:
    checker = LLMHealthChecker(
        api_key="test-key",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
        trust_env=False,
        proxy_url="",
    )
    checker._resolve_host = AsyncMock(return_value=["172.65.90.23"])  # type: ignore[method-assign]
    checker._check_models = AsyncMock(return_value=None)  # type: ignore[method-assign]
    checker._check_chat = AsyncMock(return_value=None)  # type: ignore[method-assign]

    result = await checker.check()

    assert result.ok is True
    assert result.error_kind == ""
    assert result.model == "deepseek-v4-flash"
    assert result.base_url_host == "opencode.ai"


@pytest.mark.asyncio
async def test_health_reports_chat_error_kind() -> None:
    checker = LLMHealthChecker(
        api_key="bad-key",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
        trust_env=False,
        proxy_url="",
    )
    checker._resolve_host = AsyncMock(return_value=["172.65.90.23"])  # type: ignore[method-assign]
    checker._check_models = AsyncMock(return_value=None)  # type: ignore[method-assign]
    checker._check_chat = AsyncMock(  # type: ignore[method-assign]
        return_value=LLMHealthResult(
            ok=False,
            model="deepseek-v4-flash",
            base_url_host="opencode.ai",
            error_kind="auth_error",
            message="Invalid API key",
        )
    )

    result = await checker.check()

    assert result.ok is False
    assert result.error_kind == "auth_error"
    assert "Invalid API key" in result.message


def test_health_error_message_redacts_secrets() -> None:
    checker = LLMHealthChecker(
        api_key="sk-live-secret-value",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
    )
    response = httpx.Response(
        401,
        text=("Authorization: Bearer sk-live-secret-value api_key=sk-another-secret"),
    )

    result = checker._http_error_result(response)

    assert result is not None
    assert "sk-live-secret-value" not in result.message
    assert "sk-another-secret" not in result.message
    assert "Bearer" not in result.message
    assert "[REDACTED]" in result.message


def test_health_error_message_exactly_redacts_nonstandard_current_key() -> None:
    api_key = "moonshot-credential-ABC123XYZ"
    checker = LLMHealthChecker(
        api_key=api_key,
        base_url="https://api.moonshot.cn/v1",
        model="kimi-k3",
    )

    http_result = checker._http_error_result(
        httpx.Response(401, text=f"credential {api_key} rejected")
    )
    exception_result = checker._exception_result(
        RuntimeError(f"provider rejected credential {api_key}")
    )

    assert http_result is not None
    assert api_key not in http_result.message
    assert api_key not in exception_result.message
    assert "[REDACTED]" in http_result.message
    assert "[REDACTED]" in exception_result.message


@pytest.mark.asyncio
async def test_public_health_rejects_private_dns_before_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("LLM_PROXY_URL", "")
    get_settings.cache_clear()
    checker = LLMHealthChecker(
        api_key="test-key",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    checker._resolve_host = AsyncMock(return_value=["10.0.0.5"])  # type: ignore[method-assign]
    checker._check_models = AsyncMock()  # type: ignore[method-assign]
    checker._check_chat = AsyncMock()  # type: ignore[method-assign]
    try:
        result = await checker.check()
    finally:
        get_settings.cache_clear()

    assert result.ok is False
    assert result.error_kind == "dns_private_ip"
    checker._check_models.assert_not_awaited()
    checker._check_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_health_custom_host_requires_explicit_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("LLM_PROXY_URL", "")
    get_settings.cache_clear()
    checker = LLMHealthChecker(
        api_key="test-key",
        base_url="https://attacker-controlled.example/v1",
        model="model",
    )
    checker._resolve_host = AsyncMock(return_value=["8.8.8.8"])  # type: ignore[method-assign]
    checker._check_models = AsyncMock()  # type: ignore[method-assign]
    checker._check_chat = AsyncMock()  # type: ignore[method-assign]
    try:
        result = await checker.check()
    finally:
        get_settings.cache_clear()

    assert result.ok is False
    assert result.error_kind == "configuration_error"
    checker._resolve_host.assert_not_awaited()
    checker._check_models.assert_not_awaited()
    checker._check_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_health_is_static_and_exposes_no_provider_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("LLM_TRUST_ENV", "false")
    monkeypatch.setenv("LLM_PROXY_URL", "")
    get_settings.cache_clear()

    async def fail_remote_check(_self: LLMHealthChecker) -> LLMHealthResult:
        raise AssertionError("service health must not contact a provider")

    monkeypatch.setattr(LLMHealthChecker, "check", fail_remote_check)
    try:
        result = await check_llm_service_health()
    finally:
        get_settings.cache_clear()

    assert result.ok is True
    assert result.scope == "service"
    assert result.remote_check is False
    assert result.model == ""
    assert result.base_url_host == ""
    assert result.profile_sources == {}
    assert result.profile_summary == {}
    assert result.resolved_ips == []


@pytest.mark.asyncio
async def test_service_health_rejects_invalid_proxy_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("LLM_TRUST_ENV", "false")
    monkeypatch.setenv("LLM_PROXY_URL", "file:///private/proxy-secret")
    get_settings.cache_clear()
    try:
        result = await check_llm_service_health()
    finally:
        get_settings.cache_clear()

    assert result.ok is False
    assert result.scope == "service"
    assert result.remote_check is False
    assert result.error_kind == "configuration_error"
    assert "private" not in result.message
    assert result.profile_summary == {}


@pytest.mark.asyncio
async def test_service_health_rejects_invalid_provider_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "list_account_provider_templates",
        lambda: [
            {
                "id": "broken",
                "base_url": "http://127.0.0.1:9000/v1",
                "default_model": "model",
            }
        ],
    )

    result = await check_llm_service_health()

    assert result.ok is False
    assert result.error_kind == "configuration_error"
    assert result.scope == "service"
    assert result.remote_check is False


@pytest.mark.asyncio
async def test_environment_health_uses_explicit_diagnostic_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def capture_remote_check(checker: LLMHealthChecker) -> LLMHealthResult:
        captured.update(
            api_key=checker.api_key,
            base_url=checker.base_url,
            model=checker.model,
            trust_env=checker.trust_env,
            proxy_url=checker.proxy_url,
        )
        return LLMHealthResult(ok=True, message="LLM health check passed")

    monkeypatch.setattr(LLMHealthChecker, "check", capture_remote_check)
    result = await check_llm_environment_health(
        {
            "LLM_API_KEY": "diagnostic-secret",
            "LLM_BASE_URL": "https://provider.example/v1",
            "LLM_MODEL": "diagnostic-model",
            "LLM_TRUST_ENV": "false",
            "LLM_PROXY_URL": "https://proxy.example:8443",
        }
    )

    assert captured == {
        "api_key": "diagnostic-secret",
        "base_url": "https://provider.example/v1",
        "model": "diagnostic-model",
        "trust_env": False,
        "proxy_url": "https://proxy.example:8443",
    }
    assert result.scope == "environment"
    assert result.remote_check is True
    assert "diagnostic-secret" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_environment_health_preserves_explicit_empty_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def capture_remote_check(checker: LLMHealthChecker) -> LLMHealthResult:
        captured.update(
            base_url=checker.base_url,
            model=checker.model,
            proxy_url=checker.proxy_url,
        )
        return LLMHealthResult(ok=False, error_kind="configuration_error")

    monkeypatch.setattr(LLMHealthChecker, "check", capture_remote_check)
    result = await check_llm_environment_health(
        {
            "LLM_BASE_URL": "",
            "LLM_MODEL": "",
            "LLM_PROXY_URL": "",
        }
    )

    assert captured == {"base_url": "", "model": "", "proxy_url": ""}
    assert result.profile_sources == {
        "api_key": "environment",
        "base_url": "environment",
        "model": "environment",
        "proxy_url": "environment",
        "trust_env": "default",
    }
