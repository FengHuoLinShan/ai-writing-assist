"""Phase 2 scene entity extraction configuration constants."""

from __future__ import annotations

import os

MAX_PHASE2_SCENE_RETRIES = 3
MAX_PHASE2_CONSECUTIVE_TRANSPORT_FAILURES = 3
PHASE2_SCENE_TIMEOUT_GRACE_SECONDS = 15
PHASE2_BULK_MAX_SCENES = 12
PHASE2_BULK_GROUP_SIZE = 1
PHASE2_BULK_LLM_TIMEOUT_SECONDS = 60
PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS = 45
PHASE2_BULK_MAX_TOKENS = 4096
PHASE2_BATCH_SIZE_SCENES = 12
PHASE2_BATCH_CONCURRENCY = 6
PHASE2_BOUNDARY_SCENES = 2
PHASE2_BOUNDARY_SUPPLEMENT_ENABLED = False
PHASE2_BOUNDARY_TOTAL_TIMEOUT_SECONDS = 120.0
PHASE2_PARALLEL_SCENE_CONCURRENCY = 4
PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS = 120
PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS = 135
PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS = 240
PHASE2_ALIAS_RELATION_CONCURRENCY = 4
PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED = False
PHASE2_POSTPROCESS_TIMEOUT_SECONDS = 30.0
PHASE2_SMALL_SAMPLE_MIN_SCENES = 8
PHASE2_SMALL_SAMPLE_MIN_ENTITIES = 18
PHASE2_SMALL_SAMPLE_TARGET_ENTITIES = 29
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS = 90
PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT = 4200
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT = 36000


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def phase2_batch_size_scenes() -> int:
    return _positive_int_env("PHASE2_BATCH_SIZE_SCENES", PHASE2_BATCH_SIZE_SCENES)


def phase2_batch_concurrency() -> int:
    return _positive_int_env("PHASE2_BATCH_CONCURRENCY", PHASE2_BATCH_CONCURRENCY)


def phase2_batch_tuning_group() -> str:
    configured = os.getenv("PHASE2_BATCH_TUNING_GROUP")
    if configured and configured.strip():
        return configured.strip()
    return f"{phase2_batch_size_scenes()}x{phase2_batch_concurrency()}"


def phase2_alias_relation_total_timeout_seconds() -> int:
    return _positive_int_env(
        "PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS",
        PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS,
    )


def phase2_alias_relation_concurrency() -> int:
    return _positive_int_env(
        "PHASE2_ALIAS_RELATION_CONCURRENCY",
        PHASE2_ALIAS_RELATION_CONCURRENCY,
    )


def phase2_alias_relation_supplement_enabled() -> bool:
    return _bool_env(
        "PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED",
        PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED,
    )


def phase2_postprocess_timeout_seconds() -> float:
    return _positive_float_env(
        "PHASE2_POSTPROCESS_TIMEOUT_SECONDS",
        PHASE2_POSTPROCESS_TIMEOUT_SECONDS,
    )


def phase2_boundary_total_timeout_seconds() -> float:
    return _positive_float_env(
        "PHASE2_BOUNDARY_TOTAL_TIMEOUT_SECONDS",
        PHASE2_BOUNDARY_TOTAL_TIMEOUT_SECONDS,
    )


def phase2_boundary_supplement_enabled() -> bool:
    return _bool_env(
        "PHASE2_BOUNDARY_SUPPLEMENT_ENABLED",
        PHASE2_BOUNDARY_SUPPLEMENT_ENABLED,
    )
