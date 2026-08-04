#!/usr/bin/env python3
"""Wait for the production embedding service and verify its wire contract."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRY_DELAY_SECONDS = 5.0
MAX_RESPONSE_BYTES = 1_048_576
PROBE_INPUT = "生产 embedding 健康检查"


def positive_seconds(value: str) -> float:
    """Parse a strictly positive CLI duration without accepting unbounded values."""
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number greater than zero") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the configured embedding endpoint and vector dimension."
    )
    parser.add_argument(
        "--timeout-seconds",
        type=positive_seconds,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="total bounded readiness budget (default: 900)",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=positive_seconds,
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        help="maximum timeout for one embedding request (default: 30)",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=positive_seconds,
        default=DEFAULT_RETRY_DELAY_SECONDS,
        help="maximum delay between failed requests (default: 5)",
    )
    return parser


def check_embedding(
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    environment: Mapping[str, str] = os.environ,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> int:
    """Probe the configured endpoint without exceeding the supplied total budget."""
    base_url = environment["EMBEDDING_BASE_URL"].rstrip("/")
    model = environment["EMBEDDING_MODEL"]
    api_key = environment["EMBEDDING_API_KEY"]
    expected_dim = int(environment["EMBEDDING_DIM"])
    deadline = monotonic() + timeout_seconds
    last_error = "service not ready"
    payload = json.dumps({"model": model, "input": [PROBE_INPUT]}).encode("utf-8")

    while True:
        remaining_budget = deadline - monotonic()
        if remaining_budget <= 0:
            break
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
            with urlopen(
                request,
                timeout=min(request_timeout_seconds, remaining_budget),
            ) as response:
                response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            if len(response_bytes) > MAX_RESPONSE_BYTES:
                raise ValueError
            body = json.loads(response_bytes)
            vector = body["data"][0]["embedding"]
            if len(vector) != expected_dim:
                raise ValueError
            print(f"Embedding service ready ({expected_dim} dimensions).")
            return 0
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            OSError,
            urllib.error.URLError,
        ) as error:
            last_error = type(error).__name__
            remaining_budget = deadline - monotonic()
            if remaining_budget <= 0:
                break
            sleep(min(retry_delay_seconds, remaining_budget))

    print(f"Embedding service did not become ready: {last_error}")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return check_embedding(
        timeout_seconds=args.timeout_seconds,
        request_timeout_seconds=args.request_timeout_seconds,
        retry_delay_seconds=args.retry_delay_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
