"""Token estimation helpers for prompt and context budgeting."""

from __future__ import annotations

from functools import lru_cache

import tiktoken
from tiktoken import Encoding


@lru_cache(maxsize=128)
def _encoding_for_model(model: str | None) -> Encoding:
    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            pass
    return tiktoken.get_encoding("cl100k_base")


def estimate_token_count(text: str | None, *, model: str | None = None) -> int:
    """Return a tiktoken-based token estimate for prompt budgeting."""
    if not text:
        return 0
    return max(1, len(_encoding_for_model(model).encode(text)))
