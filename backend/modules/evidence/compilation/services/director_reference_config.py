"""Explicit, default-off capability switch for copied director references."""

from __future__ import annotations

import os

DIRECTOR_REFERENCE_CAPABILITIES_ENV = "NOVELCRAFT_DIRECTOR_REFERENCE_ENABLED_CAPABILITIES"
DIRECTOR_REFERENCE_CAPABILITIES = frozenset(
    {"writing.generate", "writing.targeted_revision"}
)
MAX_DIRECTOR_REFERENCE_CHARS = 20_000


def enabled_director_reference_capabilities() -> frozenset[str]:
    raw = os.environ.get(DIRECTOR_REFERENCE_CAPABILITIES_ENV, "")
    values = tuple(
        dict.fromkeys(value.strip() for value in raw.split(",") if value.strip())
    )
    unsupported = set(values) - DIRECTOR_REFERENCE_CAPABILITIES
    if unsupported:
        raise ValueError(
            f"{DIRECTOR_REFERENCE_CAPABILITIES_ENV} contains unsupported capabilities: "
            + ", ".join(sorted(unsupported))
        )
    return frozenset(values)


def director_reference_char_limit(budget_tokens: int) -> int:
    if budget_tokens <= 0:
        return MAX_DIRECTOR_REFERENCE_CHARS
    return min(MAX_DIRECTOR_REFERENCE_CHARS, max(1_000, budget_tokens * 2))
