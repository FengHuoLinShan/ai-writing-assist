#!/usr/bin/env python3
"""Wait for the production embedding service and verify its wire contract."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def main() -> int:
    base_url = os.environ["EMBEDDING_BASE_URL"].rstrip("/")
    model = os.environ["EMBEDDING_MODEL"]
    api_key = os.environ["EMBEDDING_API_KEY"]
    expected_dim = int(os.environ["EMBEDDING_DIM"])
    deadline = time.monotonic() + 900
    last_error = "service not ready"

    payload = json.dumps(
        {"model": model, "input": ["生产 embedding 健康检查"]}
    ).encode("utf-8")
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"{base_url}/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
            vector = body["data"][0]["embedding"]
            if len(vector) != expected_dim:
                raise ValueError(
                    f"embedding dimension {len(vector)} != {expected_dim}"
                )
            print(f"Embedding service ready ({expected_dim} dimensions).")
            return 0
        except (
            KeyError,
            IndexError,
            ValueError,
            OSError,
            urllib.error.URLError,
        ) as exc:
            last_error = type(exc).__name__
            time.sleep(5)

    print(f"Embedding service did not become ready: {last_error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
