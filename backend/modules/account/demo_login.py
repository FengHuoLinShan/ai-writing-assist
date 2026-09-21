"""Validated deployment configuration for the shared demo-account login."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.config import Settings, get_settings

_MIN_SECRET_LENGTH = 8


@dataclass(frozen=True, slots=True)
class DemoLoginConfig:
    enabled: bool
    account_id: uuid.UUID | None = None
    secret: str = ""


def configured_demo_login(settings: Settings | None = None) -> DemoLoginConfig:
    """Return a usable demo-login config, or an inert config when invalid."""
    settings = settings or get_settings()
    if not settings.public_demo_login_enabled:
        return DemoLoginConfig(enabled=False)
    try:
        account_id = uuid.UUID(settings.public_demo_login_account_id.strip())
    except (AttributeError, TypeError, ValueError):
        return DemoLoginConfig(enabled=False)
    secret = settings.public_demo_login_secret
    if len(secret) < _MIN_SECRET_LENGTH or "\x00" in secret:
        return DemoLoginConfig(enabled=False)
    return DemoLoginConfig(enabled=True, account_id=account_id, secret=secret)
