"""Byte-compatible stable hashes shared by persisted workflow fingerprints."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(
    value: Any,
    *,
    stringify_unknown: bool = True,
    passthrough_str: bool = False,
) -> str:
    if passthrough_str and isinstance(value, str):
        payload = value
    else:
        options = {"default": str} if stringify_unknown else {}
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            **options,
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
