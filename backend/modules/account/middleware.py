"""ASGI authentication, account-state, origin, and CSRF boundary."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from core.config import get_settings
from core.database import get_manager
from core.errors import NotFoundError
from modules.account.constants import ANONYMOUS_RP_IDENTITY_TYPE, SESSION_COOKIE_NAME
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.public_demo import PublicDemoConfig, configured_public_demo
from modules.account.services import service

_PUBLIC_AUTH_PATHS = {
    "/api/auth/config",
    "/api/auth/anonymous-rp",
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
_DEMO_CORE_READ_PREFIXES = (
    "/api/evidence/",
    "/api/outline/",
    "/api/story/",
    "/api/world/",
    "/api/writing/",
)
_DEMO_SENSITIVE_READ_SEGMENTS = (
    "/conflict-checks",
    "/cocreation",
    "/runs/",
    "/suggestions",
    "/tasks",
    "/validation",
)


def _anonymous_rp_path_allowed(path: str) -> bool:
    if path in {"/api/auth/me", "/api/auth/logout", "/api/demo/rp-source"}:
        return True
    if path == "/api/interactions/demo-journeys":
        return True
    return path.startswith("/api/interactions/journeys/")


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


def _query(scope: Scope) -> dict[str, list[str]]:
    raw = scope.get("query_string", b"")
    value = raw.decode("latin1") if isinstance(raw, bytes) else ""
    return parse_qs(value, keep_blank_values=True)


def _single_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values and len(values) == 1 else None


def _has_configured_project_query(
    query: dict[str, list[str]], configured_id: str
) -> bool:
    seen = False
    for key in ("novel_id", "project_id"):
        values = query.get(key)
        if values is None:
            continue
        if len(values) != 1 or values[0] != configured_id:
            return False
        seen = True
    return seen


def _has_configured_project_path(path: str, configured_id: str) -> bool:
    return path.startswith(f"/api/novels/{configured_id}/memories/") or path.startswith(
        f"/api/world/map-atlas/{configured_id}/"
    )


def _is_demo_read_request(
    scope: Scope,
    *,
    path: str,
    method: str,
    config: PublicDemoConfig,
) -> bool:
    """Accept only server-configured, project-scoped core workspace reads."""
    if method != "GET" or not config.enabled or config.project_id is None:
        return False
    if any(segment in path for segment in _DEMO_SENSITIVE_READ_SEGMENTS):
        return False
    query = _query(scope)
    if _single_query_value(query, "demo") != "1":
        return False
    configured_id = str(config.project_id)
    if path == "/api/projects":
        return True
    if path in {
        f"/api/projects/{configured_id}",
        f"/api/projects/{configured_id}/workspace-summary",
    }:
        return True
    return _has_configured_project_path(path, configured_id) or (
        path.startswith(_DEMO_CORE_READ_PREFIXES)
        and _has_configured_project_query(query, configured_id)
    )


def _is_demo_read_post(
    scope: Scope,
    *,
    path: str,
    method: str,
    config: PublicDemoConfig,
) -> bool:
    if (
        method != "POST"
        or path != "/api/evidence/indexing/retrieve"
        or not config.enabled
        or config.project_id is None
    ):
        return False
    query = _query(scope)
    return _single_query_value(query, "demo") == "1" and _has_configured_project_query(
        query, str(config.project_id)
    )


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
            config = configured_public_demo(settings)
            demo_request = _is_demo_read_request(
                scope,
                path=path,
                method=method,
                config=config,
            ) or _is_demo_read_post(
                scope,
                path=path,
                method=method,
                config=config,
            )
            if demo_request:
                if method == "POST" and (
                    headers.get("x-requested-with") != "XMLHttpRequest"
                    or not _same_origin(
                        headers.get("origin", ""),
                        settings.public_base_url,
                        settings.allowed_origins,
                    )
                ):
                    await self._reject(scope, receive, send, 403, "Invalid demo request")
                    return
                principal = await self._demo_principal(config)
                if principal is None:
                    await self._reject(scope, receive, send, 404, "Demo unavailable")
                    return
                token = bind_principal(principal)
                try:
                    await self.app(scope, receive, send)
                finally:
                    reset_principal(token)
                return
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
        if principal.identity_type == "anonymous_rp":
            config = configured_public_demo(settings)
            demo_request = _is_demo_read_request(
                scope,
                path=path,
                method=method,
                config=config,
            ) or _is_demo_read_post(
                scope,
                path=path,
                method=method,
                config=config,
            )
            if demo_request:
                if method == "POST" and (
                    headers.get("x-requested-with") != "XMLHttpRequest"
                    or not _same_origin(
                        headers.get("origin", ""),
                        settings.public_base_url,
                        settings.allowed_origins,
                    )
                ):
                    await self._reject(scope, receive, send, 403, "Invalid demo request")
                    return
                demo_principal = await self._demo_principal(config)
                if demo_principal is None:
                    await self._reject(scope, receive, send, 404, "Demo unavailable")
                    return
                token = bind_principal(demo_principal)
                try:
                    await self.app(scope, receive, send)
                finally:
                    reset_principal(token)
                return
        if principal.status == "pending_deletion" and path not in _PENDING_ALLOWED_PATHS:
            await self._reject(scope, receive, send, 403, "Account pending deletion")
            return
        if (
            principal.identity_type == ANONYMOUS_RP_IDENTITY_TYPE
            and getattr(principal, "access_scope", None) != "demo_readonly"
            and not _anonymous_rp_path_allowed(path)
        ):
            await self._reject(
                scope,
                receive,
                send,
                403,
                "Anonymous RP access is limited",
            )
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

    @staticmethod
    async def _demo_principal(config: PublicDemoConfig) -> AccountPrincipal | None:
        """Resolve the configured source owner server-side; never trust request input."""
        if not config.enabled or config.project_id is None:
            return None
        from modules.project.facade import get_project_context

        manager = get_manager()
        try:
            async with manager.session() as db:
                context = await get_project_context(db, str(config.project_id))
        except NotFoundError:
            return None
        if context is None or context.owner_id is None:
            return None
        try:
            owner_id = uuid.UUID(context.owner_id)
        except (AttributeError, TypeError, ValueError):
            return None
        return AccountPrincipal(
            account_id=owner_id,
            status="active",
            identity_type="demo_readonly",
            support_code="",
            access_scope="demo_readonly",
            demo_project_id=config.project_id,
        )

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
