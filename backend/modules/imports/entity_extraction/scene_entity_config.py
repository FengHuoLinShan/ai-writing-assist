"""Phase 2 scene entity extraction configuration constants."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from shared.deep_import_settings import (
    deep_import_bool_setting,
    deep_import_float_setting,
    deep_import_int_setting,
)

MAX_PHASE2_SCENE_RETRIES = 3
MAX_PHASE2_CONSECUTIVE_TRANSPORT_FAILURES = 3
PHASE2_SCENE_TIMEOUT_GRACE_SECONDS = 15
PHASE2_BULK_MAX_SCENES = 12
PHASE2_BULK_GROUP_SIZE = 1
PHASE2_BULK_LLM_TIMEOUT_SECONDS = 60
PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS = 45
PHASE2_BULK_MAX_TOKENS = 32_768
PHASE2_BATCH_SIZE_SCENES = 12
PHASE2_BATCH_CONCURRENCY = 6
PHASE2_BOUNDARY_SCENES = 2
PHASE2_BOUNDARY_SUPPLEMENT_ENABLED = False
PHASE2_BOUNDARY_TOTAL_TIMEOUT_SECONDS = 120.0
PHASE2_PARALLEL_SCENE_CONCURRENCY = 20
PHASE2_PARALLEL_SCENE_MAX_TOKENS = 32_768
PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS = 240
PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS = 270
PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS = 240
PHASE2_ALIAS_RELATION_CONCURRENCY = 4
PHASE2_ALIAS_RELATION_LLM_TIMEOUT_SECONDS = 75
PHASE2_ALIAS_RELATION_SCENE_CHAR_LIMIT = 3200
PHASE2_ALIAS_RELATION_ENTITY_INDEX_CHAR_LIMIT = 3600
PHASE2_ALIAS_RELATION_ENTITY_INDEX_FALLBACK_LIMIT = 30
PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED = False
PHASE2_POSTPROCESS_TIMEOUT_SECONDS = 30.0
PHASE2_SMALL_SAMPLE_MIN_SCENES = 8
PHASE2_SMALL_SAMPLE_MIN_ENTITIES = 18
PHASE2_SMALL_SAMPLE_TARGET_ENTITIES = 29
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS = 90
PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT = 4200
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT = 36000

_phase2_project_settings: ContextVar[dict[str, Any] | None] = ContextVar(
    "phase2_project_settings",
    default=None,
)
_phase2_novel_id: ContextVar[str | None] = ContextVar(
    "phase2_novel_id",
    default=None,
)
_phase2_request_model: ContextVar[str | None] = ContextVar(
    "phase2_request_model",
    default=None,
)


@contextmanager
def phase2_project_settings_context(
    project_settings: dict[str, Any] | None,
    *,
    novel_id: str | None = None,
    request_model: str | None = None,
):
    settings_token = _phase2_project_settings.set(project_settings)
    novel_token = _phase2_novel_id.set(novel_id)
    model_token = _phase2_request_model.set(request_model)
    try:
        yield
    finally:
        _phase2_request_model.reset(model_token)
        _phase2_novel_id.reset(novel_token)
        _phase2_project_settings.reset(settings_token)


def _project_settings() -> dict[str, Any] | None:
    return _phase2_project_settings.get()


def current_phase2_project_settings() -> dict[str, Any] | None:
    return _project_settings()


def current_phase2_novel_id() -> str | None:
    return _phase2_novel_id.get()


def current_phase2_request_model() -> str | None:
    return _phase2_request_model.get()


def phase2_batch_size_scenes() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "batch_size_scenes",
        env_name="PHASE2_BATCH_SIZE_SCENES",
        default=PHASE2_BATCH_SIZE_SCENES,
    )


def phase2_batch_concurrency() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "batch_concurrency",
        env_name="PHASE2_BATCH_CONCURRENCY",
        default=PHASE2_BATCH_CONCURRENCY,
    )


def phase2_boundary_scenes() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "boundary_scenes",
        env_name="PHASE2_BOUNDARY_SCENES",
        default=PHASE2_BOUNDARY_SCENES,
    )


def phase2_batch_tuning_group() -> str:
    configured = os.getenv("PHASE2_BATCH_TUNING_GROUP")
    if configured and configured.strip():
        return configured.strip()
    return f"{phase2_batch_size_scenes()}x{phase2_batch_concurrency()}"


def phase2_parallel_scene_concurrency() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "parallel_scene_concurrency",
        env_name="PHASE2_PARALLEL_SCENE_CONCURRENCY",
        default=PHASE2_PARALLEL_SCENE_CONCURRENCY,
    )


def phase2_parallel_scene_max_tokens() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "parallel_scene_max_tokens",
        env_name="PHASE2_PARALLEL_SCENE_MAX_TOKENS",
        default=PHASE2_PARALLEL_SCENE_MAX_TOKENS,
    )


def phase2_parallel_provider_timeout_seconds() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "parallel_provider_timeout_seconds",
        env_name="PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS",
        default=PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS,
    )


def phase2_parallel_llm_timeout_seconds() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "parallel_llm_timeout_seconds",
        env_name="PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS",
        default=PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
    )


def phase2_alias_relation_total_timeout_seconds() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "alias_relation_total_timeout_seconds",
        env_name="PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS",
        default=PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS,
    )


def phase2_alias_relation_concurrency() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "alias_relation_concurrency",
        env_name="PHASE2_ALIAS_RELATION_CONCURRENCY",
        default=PHASE2_ALIAS_RELATION_CONCURRENCY,
    )


def phase2_alias_relation_llm_timeout_seconds() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "alias_relation_llm_timeout_seconds",
        env_name="PHASE2_ALIAS_RELATION_LLM_TIMEOUT_SECONDS",
        default=PHASE2_ALIAS_RELATION_LLM_TIMEOUT_SECONDS,
    )


def phase2_alias_relation_scene_char_limit() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "alias_relation_scene_char_limit",
        env_name="PHASE2_ALIAS_RELATION_SCENE_CHAR_LIMIT",
        default=PHASE2_ALIAS_RELATION_SCENE_CHAR_LIMIT,
    )


def phase2_alias_relation_entity_index_char_limit() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "alias_relation_entity_index_char_limit",
        env_name="PHASE2_ALIAS_RELATION_ENTITY_INDEX_CHAR_LIMIT",
        default=PHASE2_ALIAS_RELATION_ENTITY_INDEX_CHAR_LIMIT,
    )


def phase2_alias_relation_entity_index_fallback_limit() -> int:
    return deep_import_int_setting(
        _project_settings(),
        "phase2",
        "alias_relation_entity_index_fallback_limit",
        env_name="PHASE2_ALIAS_RELATION_ENTITY_INDEX_FALLBACK_LIMIT",
        default=PHASE2_ALIAS_RELATION_ENTITY_INDEX_FALLBACK_LIMIT,
    )


def phase2_alias_relation_supplement_enabled() -> bool:
    return bool(
        deep_import_bool_setting(
            _project_settings(),
            "phase2",
            "alias_relation_supplement_enabled",
            env_name="PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED",
            default=PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED,
        )
    )


def phase2_postprocess_timeout_seconds() -> float:
    return deep_import_float_setting(
        _project_settings(),
        "phase2",
        "postprocess_timeout_seconds",
        env_name="PHASE2_POSTPROCESS_TIMEOUT_SECONDS",
        default=PHASE2_POSTPROCESS_TIMEOUT_SECONDS,
    )


def phase2_boundary_total_timeout_seconds() -> float:
    return deep_import_float_setting(
        _project_settings(),
        "phase2",
        "boundary_total_timeout_seconds",
        env_name="PHASE2_BOUNDARY_TOTAL_TIMEOUT_SECONDS",
        default=PHASE2_BOUNDARY_TOTAL_TIMEOUT_SECONDS,
    )


def phase2_boundary_supplement_enabled() -> bool:
    return bool(
        deep_import_bool_setting(
            _project_settings(),
            "phase2",
            "boundary_supplement_enabled",
            env_name="PHASE2_BOUNDARY_SUPPLEMENT_ENABLED",
            default=PHASE2_BOUNDARY_SUPPLEMENT_ENABLED,
        )
    )
