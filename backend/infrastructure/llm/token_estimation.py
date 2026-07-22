"""Token estimation helpers for prompt and context budgeting."""

from __future__ import annotations

from functools import lru_cache

import tiktoken
from tiktoken import Encoding


@lru_cache(maxsize=8)
def _encoding_by_name(name: str) -> Encoding | None:
    """Load one tokenizer without making prompt budgeting depend on the network.

    Some tiktoken wheels fetch their BPE asset on first use. Production requests
    must not fail merely because that optional download is unavailable, so a
    failed load is cached and callers use the conservative byte upper bound.
    """
    try:
        return tiktoken.get_encoding(name)
    except Exception:
        return None


@lru_cache(maxsize=128)
def _encoding_for_model(model: str | None) -> Encoding | None:
    if model:
        try:
            encoding_name = tiktoken.encoding_name_for_model(model)
        except KeyError:
            encoding_name = "cl100k_base"
    else:
        encoding_name = "cl100k_base"
    return _encoding_by_name(encoding_name)


def estimate_token_count(text: str | None, *, model: str | None = None) -> int:
    """Return an exact tokenizer count or a conservative offline upper bound."""
    if not text:
        return 0
    encoding = _encoding_for_model(model)
    if encoding is None:
        # BPE tokenizers ultimately encode bytes, so the UTF-8 byte length is
        # conservative: it may trim more context but cannot silently overfill
        # a configured token budget while the tokenizer asset is unavailable.
        return max(1, len(text.encode("utf-8")))
    return max(1, len(encoding.encode(text)))
