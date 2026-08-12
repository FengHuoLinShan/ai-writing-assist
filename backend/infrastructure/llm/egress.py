"""Public-mode egress controls for user-configured LLM endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from core.config import Settings, get_settings
from infrastructure.llm.profiles import PROVIDER_TEMPLATES

_BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_TRUSTED_PROVIDER_HOSTS = frozenset(
    {
        "api.openai.com",
        *(
            (urlsplit(str(template.get("base_url") or "")).hostname or "").lower()
            for template in PROVIDER_TEMPLATES
            if template.get("base_url") and "{" not in str(template["base_url"])
        ),
    }
)
_TRUSTED_PROVIDER_SUFFIXES = (".cn-beijing.maas.aliyuncs.com",)


def _is_trusted_provider_host(hostname: str) -> bool:
    return hostname in _TRUSTED_PROVIDER_HOSTS or hostname.endswith(
        _TRUSTED_PROVIDER_SUFFIXES
    )


def validate_user_llm_base_url(
    value: str,
    *,
    settings: Settings | None = None,
) -> str:
    """Validate a user-selected LLM endpoint at the public account boundary.

    Local and closed-test modes intentionally preserve HTTP endpoints such as
    Ollama. Public mode requires an authenticated HTTPS origin and rejects
    literal non-public destinations before the value is persisted or used.
    Without an operator-configured explicit proxy, the hostname must belong to
    a built-in provider so a public user cannot control DNS and rebind the
    connection after validation.
    """

    cleaned = value.strip()
    resolved = settings or get_settings()
    if resolved.auth_mode.strip().lower() != "public" or not cleaned:
        return cleaned

    parsed = urlsplit(cleaned)
    if parsed.scheme.lower() != "https":
        raise ValueError("Public LLM Base URL must use https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LLM Base URL must not contain user info")
    if parsed.fragment:
        raise ValueError("LLM Base URL must not contain a fragment")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        raise ValueError("LLM Base URL must include a hostname")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("LLM Base URL contains an invalid port") from exc
    if hostname in _BLOCKED_HOSTS or hostname.endswith(_BLOCKED_SUFFIXES):
        raise ValueError("Public LLM Base URL must use a public hostname")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("Public LLM Base URL must use a public destination")
    if not resolved.llm_proxy_url:
        if parsed.port not in {None, 443}:
            raise ValueError("Direct public LLM endpoints must use port 443")
        if not _is_trusted_provider_host(hostname):
            raise ValueError(
                "Custom public LLM endpoints require an explicit LLM_PROXY_URL"
            )
    return cleaned


def build_public_llm_request_guard(
    *,
    resolve_dns: bool,
) -> Callable[[httpx.Request], Awaitable[None]]:
    """Build an httpx request hook that rechecks every request and redirect."""

    async def guard(request: httpx.Request) -> None:
        settings = get_settings()
        if settings.auth_mode.strip().lower() != "public":
            return
        try:
            validate_user_llm_base_url(str(request.url), settings=settings)
        except ValueError as exc:
            raise httpx.ConnectError(
                "LLM endpoint is not permitted in public mode",
                request=request,
            ) from exc
        if not resolve_dns:
            # An operator-configured proxy is the network egress boundary.
            return
        hostname = request.url.host
        port = request.url.port or 443
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise httpx.ConnectError(
                "LLM endpoint DNS resolution failed",
                request=request,
            ) from exc
        resolved_ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        for address in addresses:
            raw = str(address[4][0]).split("%", 1)[0]
            try:
                resolved_ips.add(ipaddress.ip_address(raw))
            except ValueError as exc:
                raise httpx.ConnectError(
                    "LLM endpoint resolved to an invalid address",
                    request=request,
                ) from exc
        if not resolved_ips or any(not address.is_global for address in resolved_ips):
            raise httpx.ConnectError(
                "LLM endpoint did not resolve to a public destination",
                request=request,
            )

    return guard
