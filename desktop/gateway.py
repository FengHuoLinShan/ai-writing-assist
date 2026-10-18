"""One loopback origin for the desktop UI and its authenticated API."""

from __future__ import annotations

import hmac
from http.cookies import SimpleCookie

from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.staticfiles import StaticFiles


def readiness_proof(token: str) -> str:
    return hmac.digest(token.encode(), b"novelcraft-ready", "sha256").hex()


class DesktopGateway:
    def __init__(self, api, frontend, origin: str, token: str) -> None:
        self.api = api
        self.files = StaticFiles(directory=str(frontend), html=True)
        self.origin = origin
        self.host = origin.removeprefix("http://")
        self.token = token
        self.opened = False

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.api(scope, receive, send)
        if scope["type"] != "http":
            return
        headers = dict(scope.get("headers", []))
        path = scope["path"]
        if headers.get(b"host", b"").decode() != self.host:
            return await PlainTextResponse("Invalid host", 403)(scope, receive, send)
        if path == "/_desktop/ready" and scope["method"] == "GET":
            return await PlainTextResponse(readiness_proof(self.token))(
                scope, receive, send
            )
        bootstrap = path.removeprefix("/_desktop/open/")
        if (
            path.startswith("/_desktop/open/")
            and not self.opened
            and scope["method"] == "GET"
            and hmac.compare_digest(bootstrap.encode(), self.token.encode())
        ):
            self.opened = True
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(
                "novelcraft_desktop",
                self.token,
                httponly=True,
                samesite="strict",
                path="/",
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return await response(scope, receive, send)
        cookie = SimpleCookie()
        cookie.load(headers.get(b"cookie", b"").decode("latin1"))
        item = cookie.get("novelcraft_desktop")
        if not item or not hmac.compare_digest(
            item.value.encode(), self.token.encode()
        ):
            return await PlainTextResponse("Unauthorized", 401)(scope, receive, send)
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            if headers.get(b"origin", b"").decode() != self.origin:
                return await PlainTextResponse("Invalid origin", 403)(
                    scope, receive, send
                )
        if path.startswith("/api/"):
            return await self.api(scope, receive, send)
        async def secured_send(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (
                            b"content-security-policy",
                            b"default-src 'self'; script-src 'self'; "
                            b"style-src 'self' 'unsafe-inline'; "
                            b"img-src 'self' data: blob:; "
                            b"connect-src 'self'; object-src 'none'; base-uri 'self'; "
                            b"frame-ancestors 'none'",
                        ),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ]
                )
            await send(message)

        try:
            await self.files(scope, receive, secured_send)
        except HTTPException as error:
            await PlainTextResponse("Not found", error.status_code)(
                scope, receive, send
            )
