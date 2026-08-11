"""LLM provider health checks.

This module intentionally reports only diagnostic metadata. It must never expose
API keys or request bodies.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlsplit

import httpx
from pydantic import BaseModel, Field

from core.config import get_settings
from infrastructure.llm.egress import (
    build_public_llm_request_guard,
    validate_user_llm_base_url,
)
from infrastructure.llm.profiles import (
    list_account_provider_templates,
    resolve_llm_profile,
)
from infrastructure.llm.redaction import redact_diagnostic


class LLMHealthResult(BaseModel):
    """Machine-readable health check result."""

    ok: bool
    scope: str = "connection"
    remote_check: bool = True
    model: str = ""
    base_url_host: str = ""
    error_kind: str = ""
    message: str = ""
    dns_fake_ip: bool = False
    resolved_ips: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    profile_sources: dict[str, str] = Field(default_factory=dict)
    profile_summary: dict[str, Any] = Field(default_factory=dict)


@dataclass
class LLMHealthChecker:
    """Checks DNS/proxy/API readiness for the configured OpenAI-compatible LLM."""

    api_key: str
    base_url: str
    model: str
    trust_env: bool = False
    proxy_url: str = ""
    timeout: int = 20

    async def check(self) -> LLMHealthResult:
        start = time.monotonic()
        host = urlparse(self.base_url).hostname or ""
        settings = get_settings()
        if not self.api_key:
            return self._result(
                ok=False,
                host=host,
                error_kind="auth_error",
                message="Project LLM API key is not configured",
            )
        try:
            validate_user_llm_base_url(self.base_url, settings=settings)
        except ValueError as exc:
            return self._result(
                ok=False,
                host=host,
                error_kind="configuration_error",
                message=str(exc),
            )

        ips: list[str] = []
        if not (settings.auth_mode == "public" and self.proxy_url):
            try:
                ips = await self._resolve_host(host)
            except Exception as exc:
                return self._result(
                    ok=False,
                    host=host,
                    error_kind="dns_error",
                    message=str(exc),
                    latency_ms=self._elapsed_ms(start),
                )

        dns_fake_ip = any(_is_fake_ip(ip) for ip in ips)
        if settings.auth_mode == "public" and any(
            not _is_public_ip(ip) for ip in ips
        ):
            return self._result(
                ok=False,
                host=host,
                error_kind="dns_private_ip",
                message="Public LLM host did not resolve to a public destination",
                resolved_ips=ips,
                dns_fake_ip=dns_fake_ip,
                latency_ms=self._elapsed_ms(start),
            )
        if dns_fake_ip and not self.proxy_url:
            return self._result(
                ok=False,
                host=host,
                error_kind="dns_fake_ip",
                message="LLM host resolves to a fake-ip range without an explicit proxy",
                resolved_ips=ips,
                dns_fake_ip=True,
                latency_ms=self._elapsed_ms(start),
            )

        error = await self._check_models()
        if error is not None:
            error.resolved_ips = ips
            error.dns_fake_ip = dns_fake_ip
            error.latency_ms = self._elapsed_ms(start)
            return error

        error = await self._check_chat()
        if error is not None:
            error.resolved_ips = ips
            error.dns_fake_ip = dns_fake_ip
            error.latency_ms = self._elapsed_ms(start)
            return error

        return self._result(
            ok=True,
            host=host,
            message="LLM health check passed",
            resolved_ips=ips,
            dns_fake_ip=dns_fake_ip,
            latency_ms=self._elapsed_ms(start),
        )

    async def _resolve_host(self, host: str) -> list[str]:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return sorted({info[4][0] for info in infos})

    async def _check_models(self) -> LLMHealthResult | None:
        url = self.base_url.rstrip("/") + "/models"
        try:
            response = await self._client_get(url)
        except Exception as exc:
            return self._exception_result(exc)
        return self._http_error_result(response)

    async def _check_chat(self) -> LLMHealthResult | None:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Return only pong."}],
            "max_tokens": 16,
            "temperature": 0,
        }
        try:
            response = await self._client_post(url, json=payload)
        except Exception as exc:
            return self._exception_result(exc)
        return self._http_error_result(response)

    async def _client_get(self, url: str) -> httpx.Response:
        async with self._new_client() as client:
            return await client.get(url, headers=self._headers())

    async def _client_post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        async with self._new_client() as client:
            return await client.post(url, headers=self._headers(), json=json)

    def _new_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "timeout": self.timeout,
            "trust_env": self.trust_env,
            "event_hooks": {
                "request": [
                    build_public_llm_request_guard(
                        resolve_dns=not bool(self.proxy_url),
                    )
                ]
            },
        }
        if self.proxy_url:
            kwargs["proxy"] = self.proxy_url
        return httpx.AsyncClient(**kwargs)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _http_error_result(self, response: httpx.Response) -> LLMHealthResult | None:
        if response.status_code < 400:
            return None
        return self._result(
            ok=False,
            host=urlparse(self.base_url).hostname or "",
            error_kind=_classify_http_status(response.status_code),
            message=self._redact_provider_diagnostic(response.text),
        )

    def _exception_result(self, exc: Exception) -> LLMHealthResult:
        return self._result(
            ok=False,
            host=urlparse(self.base_url).hostname or "",
            error_kind=_classify_exception(exc),
            message=self._redact_provider_diagnostic(exc),
        )

    def _redact_provider_diagnostic(self, value: object) -> str:
        diagnostic = str(value)
        if self.api_key:
            diagnostic = diagnostic.replace(self.api_key, "[REDACTED]")
        return redact_diagnostic(diagnostic, limit=300)

    def _result(
        self,
        *,
        ok: bool,
        host: str,
        error_kind: str = "",
        message: str = "",
        resolved_ips: list[str] | None = None,
        dns_fake_ip: bool = False,
        latency_ms: float = 0.0,
        profile_sources: dict[str, str] | None = None,
        profile_summary: dict[str, Any] | None = None,
    ) -> LLMHealthResult:
        return LLMHealthResult(
            ok=ok,
            model=self.model,
            base_url_host=host,
            error_kind=error_kind,
            message=message,
            resolved_ips=resolved_ips or [],
            dns_fake_ip=dns_fake_ip,
            latency_ms=latency_ms,
            profile_sources=profile_sources or {},
            profile_summary=profile_summary or {},
        )

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.monotonic() - start) * 1000, 1)


async def check_llm_health_for_project(
    project_settings: dict[str, Any] | None = None,
    *,
    test_overrides: dict[str, Any] | None = None,
) -> LLMHealthResult:
    settings = get_settings()
    profile = resolve_llm_profile(
        project_settings,
        env_settings=settings,
        test_overrides=test_overrides,
    )
    checker = LLMHealthChecker(
        api_key=profile.api_key,
        base_url=profile.base_url,
        model=profile.model,
        trust_env=settings.llm_trust_env,
        proxy_url=settings.llm_proxy_url,
        timeout=min(int(profile.timeout), 30),
    )
    result = await checker.check()
    result.profile_sources = dict(profile.sources)
    result.profile_summary = profile.sanitized_summary()
    return result


async def check_llm_health() -> LLMHealthResult:
    """Run the legacy accountless connection check for internal callers."""

    return await check_llm_health_for_project(None)


async def check_llm_service_health() -> LLMHealthResult:
    """Validate service-owned LLM capability without credentials or network I/O."""

    settings = get_settings()
    try:
        _validate_service_proxy_configuration(
            settings.llm_proxy_url,
            trust_env=settings.llm_trust_env,
            public_mode=settings.auth_mode.strip().lower() == "public",
        )
        _validate_account_provider_templates(settings=settings)
    except (TypeError, ValueError):
        return LLMHealthResult(
            ok=False,
            scope="service",
            remote_check=False,
            error_kind="configuration_error",
            message="LLM service configuration is invalid",
        )
    return LLMHealthResult(
        ok=True,
        scope="service",
        remote_check=False,
        message="LLM service configuration is valid",
    )


async def check_llm_environment_health(
    environment: Mapping[str, str] | None = None,
) -> LLMHealthResult:
    """Run an explicit CLI-only remote diagnostic from environment values.

    This helper never participates in account or project profile resolution.
    """

    values = environment if environment is not None else os.environ
    settings = get_settings()
    api_key = str(values["LLM_API_KEY"]) if "LLM_API_KEY" in values else ""
    base_url = (
        str(values["LLM_BASE_URL"])
        if "LLM_BASE_URL" in values
        else settings.llm_base_url
    )
    model = str(values["LLM_MODEL"]) if "LLM_MODEL" in values else settings.llm_model
    proxy_url = (
        str(values["LLM_PROXY_URL"])
        if "LLM_PROXY_URL" in values
        else settings.llm_proxy_url
    )
    trust_env_value = values.get("LLM_TRUST_ENV")
    trust_env = (
        settings.llm_trust_env
        if trust_env_value is None
        else str(trust_env_value).strip().lower() in {"1", "true", "yes", "on"}
    )
    checker = LLMHealthChecker(
        api_key=api_key,
        base_url=base_url,
        model=model,
        trust_env=trust_env,
        proxy_url=proxy_url,
        timeout=min(int(settings.llm_timeout), 30),
    )
    result = await checker.check()
    result.scope = "environment"
    result.remote_check = True
    result.profile_sources = {
        "api_key": "environment",
        "base_url": "environment" if "LLM_BASE_URL" in values else "default",
        "model": "environment" if "LLM_MODEL" in values else "default",
        "proxy_url": "environment" if "LLM_PROXY_URL" in values else "default",
        "trust_env": "environment" if trust_env_value is not None else "default",
    }
    result.profile_summary = {
        "model": model,
        "base_url_host": urlparse(base_url).hostname or "",
        "api_key_configured": bool(api_key),
        "proxy_configured": bool(proxy_url),
        "trust_env": trust_env,
        "scope": "environment",
    }
    return result


def _validate_service_proxy_configuration(
    proxy_url: str,
    *,
    trust_env: bool,
    public_mode: bool,
) -> None:
    if public_mode and trust_env:
        raise ValueError("public service proxy configuration must be explicit")
    if not proxy_url:
        return
    try:
        parsed = urlsplit(proxy_url)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("invalid LLM proxy URL") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid LLM proxy URL")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("invalid LLM proxy URL")


def _validate_account_provider_templates(*, settings: Any) -> None:
    templates = list_account_provider_templates()
    if not templates:
        raise ValueError("no account LLM provider templates")
    provider_ids: set[str] = set()
    for template in templates:
        provider_id = str(template.get("id") or "").strip()
        base_url = str(template.get("base_url") or "").strip()
        model = str(template.get("default_model") or "").strip()
        if not provider_id or provider_id in provider_ids or not base_url or not model:
            raise ValueError("invalid account LLM provider template")
        provider_ids.add(provider_id)
        parsed = urlsplit(base_url)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("unsafe account LLM provider template")
        try:
            literal = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ValueError("unsafe account LLM provider template")
        validate_user_llm_base_url(base_url, settings=settings)


def _is_fake_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip in ipaddress.ip_network("198.18.0.0/15")


def _is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _classify_http_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "auth_error"
    if status_code == 429:
        return "rate_limit"
    if status_code >= 500:
        return "provider_error"
    if status_code == 400:
        return "invalid_request"
    return "http_error"


def _classify_exception(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    combined = f"{name} {text}"
    if "proxy" in combined or "connect tunnel" in combined or "503" in combined:
        return "proxy_error"
    if "ssl" in combined or "tls" in combined or "eof" in combined:
        return "tls_error"
    if "name or service" in combined or "nodename" in combined:
        return "dns_error"
    if "timeout" in combined:
        return "timeout"
    return "connection_error"
