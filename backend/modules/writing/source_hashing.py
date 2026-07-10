"""Hash helpers for immutable manuscript source references."""

from __future__ import annotations

import hashlib


def hash_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
