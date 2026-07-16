"""HTTP client helpers shared by SQLite and PostgreSQL test harnesses."""

from __future__ import annotations

from httpx import AsyncClient


class XhrAsyncClient(AsyncClient):
    """Mirror the frontend CSRF marker on state-changing requests."""

    async def request(self, method: str, url, **kwargs):  # noqa: ANN001, ANN201
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("X-Requested-With", "XMLHttpRequest")
            kwargs["headers"] = headers
        return await super().request(method, url, **kwargs)
