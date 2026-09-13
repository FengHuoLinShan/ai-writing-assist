"""Validated deployment configuration for the public read-only demo."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class PublicDemoConfig:
    enabled: bool
    project_id: uuid.UUID | None = None
    version: str | None = None
    rp_enabled: bool = False


def configured_public_demo(settings: Settings | None = None) -> PublicDemoConfig:
    """Return a usable demo config, or an inert config when deployment is invalid."""
    settings = settings or get_settings()
    if not settings.public_demo_enabled:
        return PublicDemoConfig(enabled=False)
    version = settings.public_demo_version.strip()
    raw_project_id = settings.public_demo_project_id.strip()
    if not version or "\x00" in version or len(version) > 128:
        return PublicDemoConfig(enabled=False)
    try:
        project_id = uuid.UUID(raw_project_id)
    except (AttributeError, TypeError, ValueError):
        return PublicDemoConfig(enabled=False)
    return PublicDemoConfig(
        enabled=True,
        project_id=project_id,
        version=version,
        rp_enabled=settings.public_demo_rp_enabled,
    )
