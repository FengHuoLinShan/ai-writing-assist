"""ASGI authentication, account-state, origin, and CSRF boundary."""

from __future__ import annotations

import hashlib
import hmac
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from core.config import get_settings
from core.database import get_manager
from modules.account.constants import SESSION_COOKIE_NAME
from modules.account.context import bind_principal, reset_principal
from modules.account.services import service

_PUBLIC_AUTH_PATHS = {
    "/api/auth/config",
    "/api/auth/email/request-code",
    "/api/auth/email/verify",
    "/api/auth/wechat/start",
    "/api/auth/wechat/callback",
}
_PENDING_ALLOWED_PATHS = {
    "/api/auth/me",
    "/api/auth/logout",
    "/api/auth/reauth/email/request-code",
    "/api/auth/reauth/email/verify",
    "/api/auth/reauth/wechat/start",
    "/api/auth/wechat/start",
    "/api/auth/wechat/callback",
    "/api/account/deletion",
}
_STATE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in scope.get("headers", [])
    }


def _cookie(headers: dict[str, str], name: str) -> str:
    parsed = SimpleCookie()
    parsed.load(headers.get("cookie", ""))
    morsel = parsed.get(name)
    return morsel.value if morsel is not None else ""


def _same_origin(origin: str, public_base_url: str, allowed: list[str]) -> bool:
    if not origin:
        return False
    expected = urlsplit(public_base_url)
    supplied = urlsplit(origin)
    normalized = f"{supplied.scheme}://{supplied.netloc}"
    public_origin = f"{expected.scheme}://{expected.netloc}"
    return normalized == public_origin or normalized in allowed


class AccountAuthMiddleware:
    """Bind one verified browser principal to every protected public request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        path = str(scope.get("path") or "")
        method = str(scope.get("method") or "").upper()
        if (
            scope.get("type") != "http"
            or settings.auth_mode != "public"
            or not path.startswith("/api/")
            or method == "OPTIONS"
            or path in {"/api/health", "/api/health/llm"}
        ):
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        if path in _PUBLIC_AUTH_PATHS:
            await self._check_public_write_origin(
                scope, receive, send, method, headers, settings
            )
            return

        raw_token = _cookie(headers, SESSION_COOKIE_NAME)
        if not raw_token:
            await self._reject(scope, receive, send, 401, "Authentication required")
            return
        manager = get_manager()
        async with manager.session() as db:
            principal = await service.authenticate_session(
                db,
                raw_token,
                settings=settings,
            )
        if principal is None:
            await self._reject(scope, receive, send, 401, "Authentication required")
            return
        if principal.status == "pending_deletion" and path not in _PENDING_ALLOWED_PATHS:
            await self._reject(scope, receive, send, 403, "Account pending deletion")
            return
        if method in _STATE_METHODS:
            origin = headers.get("origin", "")
            if not _same_origin(
                origin,
                settings.public_base_url,
                settings.allowed_origins,
            ):
                await self._reject(scope, receive, send, 403, "Invalid request origin")
                return
            csrf = headers.get("x-csrf-token", "")
            supplied = hmac.new(
                settings.auth_secret_key.encode(),
                f"csrf:{csrf}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if principal.csrf_digest is None or not hmac.compare_digest(
                supplied,
                principal.csrf_digest,
            ):
                await self._reject(scope, receive, send, 403, "Invalid CSRF token")
                return
        token = bind_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_principal(token)

    async def _check_public_write_origin(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        method: str,
        headers: dict[str, str],
        settings,
    ) -> None:
        if method in _STATE_METHODS and not _same_origin(
            headers.get("origin", ""),
            settings.public_base_url,
            settings.allowed_origins,
        ):
            await self._reject(scope, receive, send, 403, "Invalid request origin")
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        await JSONResponse(status_code=status_code, content={"detail": detail})(
            scope,
            receive,
            send,
        )
