"""Content-addressed local cache for generation and judge calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class EvalCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get(self, namespace: str, key: str) -> dict[str, Any] | None:
        path = self.root / namespace / f"{key}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, namespace: str, key: str, value: dict[str, Any]) -> Path:
        path = self.root / namespace / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path
