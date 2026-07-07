"""Lightweight CSRF guard dependencies."""

from __future__ import annotations

from fastapi import HTTPException, Request


async def require_xhr_request(request: Request) -> None:
    """Require same-origin console writes to use the XHR marker header."""
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="Missing X-Requested-With header")
