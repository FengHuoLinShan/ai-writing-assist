"""LLM health checker tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from infrastructure.llm.health import LLMHealthChecker, LLMHealthResult


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
        text=(
            "Authorization: Bearer sk-live-secret-value "
            "api_key=sk-another-secret"
        ),
    )

    result = checker._http_error_result(response)

    assert result is not None
    assert "sk-live-secret-value" not in result.message
    assert "sk-another-secret" not in result.message
    assert "Bearer" not in result.message
    assert "[REDACTED]" in result.message
