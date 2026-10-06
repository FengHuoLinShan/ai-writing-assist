"""Shared worldbuilding constants and profile registry."""

from __future__ import annotations

import re

# AO-5 / ADR-0031: Profile 注册表上移 world services 共享根（core 与
# worldbuilding 平级消费），这里保留兼容再出口。
from modules.world.services.entity_profile_registry import (
    PROFILE_REGISTRY as PROFILE_REGISTRY,
)
from modules.world.services.entity_profile_registry import (
    ProfileBinding as ProfileBinding,
)

CONFIRMED_STATUSES = {"canonical", "confirmed"}
STRONG_PROFILE_TYPES = {"species", "faction", "location", "rule", "item", "secret"}
GENERIC_PROFILE_TYPES = {
    "group",
    "creature",
    "skill",
    "other",
    "concept",
    "resource",
    "legend",
    "power_system",
}

_PROFESSION_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def normalize_profession_slug(label: str) -> str:
    slug = _PROFESSION_SLUG_RE.sub("_", label.strip().lower()).strip("_")
    return slug[:128]


__all__ = [
    "CONFIRMED_STATUSES",
    "GENERIC_PROFILE_TYPES",
    "PROFILE_REGISTRY",
    "STRONG_PROFILE_TYPES",
    "ProfileBinding",
    "normalize_profession_slug",
]
