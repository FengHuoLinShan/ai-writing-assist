"""Hash helpers for immutable manuscript source references."""

from __future__ import annotations

import hashlib


def hash_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def substantive_text(text: str | None) -> str:
    """Return the body used for automatic version-change comparisons.

    Storage keeps the author's exact text. Only automatic version detection
    ignores Unicode whitespace so formatting-only edits remain local until the
    author explicitly checkpoints them.
    """

    return "".join(char for char in (text or "") if not char.isspace())


def has_substantive_change(before: str | None, after: str | None) -> bool:
    return substantive_text(before) != substantive_text(after)
