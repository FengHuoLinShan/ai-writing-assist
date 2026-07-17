"""Shared contract for project-level deep import parameters."""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from shared.constants import DEFAULT_LLM_MAX_TOKENS

DEEP_IMPORT_SETTINGS_KEY = "deep_import"
DEEP_IMPORT_FROZEN_SETTINGS_KEY = "_deep_import_settings_frozen"

DEEP_IMPORT_DEFAULT_SETTINGS: dict[str, dict[str, Any]] = {
    "global": {
        "structured_timeout_grace_seconds": 60,
        "structured_max_fix_attempts": 2,
    },
    "phase0": {
        "target_input_chars": 72_000,
        "max_chapters_per_window": 20,
        "right_overlap_chapters": 2,
        "max_tokens_per_input_char": 1.0,
        "min_max_tokens": 13_000,
        "max_max_tokens": 32_768,
        # Legacy prefetch-only fields. Hidden from the normal settings UI.
        "scene_max_tokens": 8192,
        "scene_timeout_seconds": 420,
    },
    "phase1a": {
        # Legacy reinforcement-only field. Formal slicing uses Phase 0 window budgets.
        "scene_max_tokens": 8192,
        "scene_slicing_timeout_seconds": 900,
        "structured_max_fix_attempts": 1,
    },
    "phase1b": {
        "small_sample_max_tokens": 6144,
        "small_sample_timeout_seconds": 420,
        "reducer_max_tokens": 128,
        "reducer_timeout_seconds": 420,
        "compact_text_limit": 180,
        "enrich_max_tokens": 32_768,
        "enrich_timeout_seconds": 1200,
        "use_llm": None,
    },
    "phase1c": {
        "auto_merge_confidence": 0.92,
        "boundary_context_chars": 2000,
        "concurrency": 20,
        # None means inherit the effective project/global/system LLM budget.
        "decision_max_tokens": None,
        "timeout_seconds": 1200,
    },
    "phase2": {
        "world_timeout_seconds": 1200,
        "world_min_max_tokens": 32_768,
        "world_max_max_tokens": 32_768,
        "world_max_tokens_per_source_char": 1.0,
        "world_window_concurrency": 20,
        "parallel_scene_concurrency": 25,
        "parallel_scene_max_tokens": 32_768,
        "parallel_provider_timeout_seconds": 360,
        "parallel_llm_timeout_seconds": 900,
        "batch_size_scenes": 12,
        "batch_concurrency": 6,
        "boundary_scenes": 2,
        "boundary_supplement_enabled": False,
        "boundary_total_timeout_seconds": 900.0,
        "alias_relation_total_timeout_seconds": 1200,
        "alias_relation_concurrency": 4,
        "alias_relation_llm_timeout_seconds": 600,
        "alias_relation_scene_char_limit": 3200,
        "alias_relation_entity_index_char_limit": 3600,
        "alias_relation_entity_index_fallback_limit": 30,
        "alias_relation_supplement_enabled": False,
        "postprocess_timeout_seconds": 120.0,
    },
    "phase3": {
        "structure_timeout_seconds": 1200,
        "structure_max_tokens": 32_768,
    },
}


DEEP_IMPORT_SETTING_LIMITS: dict[tuple[str, str], tuple[float, float]] = {
    ("global", "structured_timeout_grace_seconds"): (1, 600),
    ("global", "structured_max_fix_attempts"): (0, 10),
    ("phase0", "target_input_chars"): (1_000, 500_000),
    ("phase0", "max_chapters_per_window"): (1, 100),
    ("phase0", "right_overlap_chapters"): (0, 20),
    ("phase0", "max_tokens_per_input_char"): (0.05, 2),
    ("phase0", "min_max_tokens"): (1, 200_000),
    ("phase0", "max_max_tokens"): (1, 200_000),
    ("phase0", "scene_max_tokens"): (1, 200_000),
    ("phase0", "scene_timeout_seconds"): (1, 3600),
    ("phase1a", "scene_max_tokens"): (1, 200_000),
    ("phase1a", "scene_slicing_timeout_seconds"): (1, 7200),
    ("phase1a", "structured_max_fix_attempts"): (0, 10),
    ("phase1b", "small_sample_max_tokens"): (1, 200_000),
    ("phase1b", "small_sample_timeout_seconds"): (1, 3600),
    ("phase1b", "reducer_max_tokens"): (1, 200_000),
    ("phase1b", "reducer_timeout_seconds"): (1, 3600),
    ("phase1b", "compact_text_limit"): (10, 5000),
    ("phase1b", "enrich_max_tokens"): (1, 200_000),
    ("phase1b", "enrich_timeout_seconds"): (1, 7200),
    ("phase1c", "auto_merge_confidence"): (0.0, 1.0),
    ("phase1c", "boundary_context_chars"): (100, 100_000),
    ("phase1c", "concurrency"): (1, 100),
    ("phase1c", "decision_max_tokens"): (1, 200_000),
    ("phase1c", "timeout_seconds"): (1, 7200),
    ("phase2", "world_timeout_seconds"): (1, 7200),
    ("phase2", "world_min_max_tokens"): (1, 200_000),
    ("phase2", "world_max_max_tokens"): (1, 200_000),
    ("phase2", "world_max_tokens_per_source_char"): (0.05, 2),
    ("phase2", "world_window_concurrency"): (1, 100),
    ("phase2", "parallel_scene_concurrency"): (1, 64),
    ("phase2", "parallel_scene_max_tokens"): (1, 200_000),
    ("phase2", "parallel_provider_timeout_seconds"): (1, 1800),
    ("phase2", "parallel_llm_timeout_seconds"): (1, 1800),
    ("phase2", "batch_size_scenes"): (1, 200),
    ("phase2", "batch_concurrency"): (1, 100),
    ("phase2", "boundary_scenes"): (1, 20),
    ("phase2", "boundary_total_timeout_seconds"): (0.1, 7200),
    ("phase2", "alias_relation_total_timeout_seconds"): (1, 7200),
    ("phase2", "alias_relation_concurrency"): (1, 100),
    ("phase2", "alias_relation_llm_timeout_seconds"): (1, 3600),
    ("phase2", "alias_relation_scene_char_limit"): (100, 100_000),
    ("phase2", "alias_relation_entity_index_char_limit"): (100, 100_000),
    ("phase2", "alias_relation_entity_index_fallback_limit"): (1, 1000),
    ("phase2", "postprocess_timeout_seconds"): (0.1, 3600),
    ("phase3", "structure_timeout_seconds"): (1, 7200),
    ("phase3", "structure_max_tokens"): (1, 200_000),
}

_BOOL_SETTINGS = {
    ("phase1b", "use_llm"),
    ("phase2", "boundary_supplement_enabled"),
    ("phase2", "alias_relation_supplement_enabled"),
}

_NULLABLE_INT_SETTINGS = {
    ("phase1c", "decision_max_tokens"),
}

_FLOAT_SETTINGS = {
    ("phase0", "max_tokens_per_input_char"),
    ("phase1c", "auto_merge_confidence"),
    ("phase2", "boundary_total_timeout_seconds"),
    ("phase2", "postprocess_timeout_seconds"),
    ("phase2", "world_max_tokens_per_source_char"),
}


def deep_import_defaults() -> dict[str, dict[str, Any]]:
    return deepcopy(DEEP_IMPORT_DEFAULT_SETTINGS)


def clean_deep_import_settings(value: Any) -> dict[str, dict[str, Any]]:
    """Return only known deep import settings, coerced and range-checked."""

    if not isinstance(value, dict):
        return deep_import_defaults()

    cleaned = deep_import_defaults()
    for phase, defaults in DEEP_IMPORT_DEFAULT_SETTINGS.items():
        raw_phase = value.get(phase)
        if not isinstance(raw_phase, dict):
            continue
        for key, default in defaults.items():
            if key not in raw_phase:
                continue
            parsed = _coerce_value(phase, key, raw_phase.get(key), default)
            if parsed is not _INVALID:
                cleaned[phase][key] = parsed
    return cleaned


def deep_import_settings_for_response(
    project_settings: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(project_settings, dict):
        return deep_import_defaults()
    return clean_deep_import_settings(project_settings.get(DEEP_IMPORT_SETTINGS_KEY))


def materialize_effective_deep_import_settings(
    project_settings: dict[str, Any] | None,
    *,
    inherited_llm_max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
) -> dict[str, dict[str, Any]]:
    """Freeze project/default/env precedence into explicit task settings."""

    settings = deep_import_settings_for_response(project_settings)
    project_view = {DEEP_IMPORT_SETTINGS_KEY: settings}
    effective = deep_import_defaults()
    for phase, phase_defaults in DEEP_IMPORT_DEFAULT_SETTINGS.items():
        for key, default in phase_defaults.items():
            env_name = _deep_import_env_name(phase, key)
            if (phase, key) in _NULLABLE_INT_SETTINGS:
                value = deep_import_int_setting(
                    project_view,
                    phase,
                    key,
                    env_name=env_name,
                    default=inherited_llm_max_tokens,
                )
            elif (phase, key) in _BOOL_SETTINGS:
                value = deep_import_bool_setting(
                    project_view,
                    phase,
                    key,
                    env_name=env_name,
                    default=default,
                )
            elif (phase, key) in _FLOAT_SETTINGS:
                value = deep_import_float_setting(
                    project_view,
                    phase,
                    key,
                    env_name=env_name,
                    default=float(default),
                )
            else:
                value = deep_import_int_setting(
                    project_view,
                    phase,
                    key,
                    env_name=env_name,
                    default=int(default),
                )
            effective[phase][key] = value
    return effective


def deep_import_int_setting(
    project_settings: dict[str, Any] | None,
    phase: str,
    key: str,
    *,
    env_name: str,
    default: int,
) -> int:
    env_value = (
        None if _settings_are_frozen(project_settings) else _int_from_env(env_name)
    )
    if env_value is not None and _within_limits(phase, key, env_value):
        return env_value
    value = _project_setting(project_settings, phase, key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed if _within_limits(phase, key, parsed) else int(default)


def deep_import_float_setting(
    project_settings: dict[str, Any] | None,
    phase: str,
    key: str,
    *,
    env_name: str,
    default: float,
) -> float:
    env_value = (
        None if _settings_are_frozen(project_settings) else _float_from_env(env_name)
    )
    if env_value is not None and _within_limits(phase, key, env_value):
        return env_value
    value = _project_setting(project_settings, phase, key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if _within_limits(phase, key, parsed) else float(default)


def deep_import_bool_setting(
    project_settings: dict[str, Any] | None,
    phase: str,
    key: str,
    *,
    env_name: str,
    default: bool | None,
) -> bool | None:
    env_value = (
        None if _settings_are_frozen(project_settings) else _bool_from_env(env_name)
    )
    if env_value is not None:
        return env_value
    value = _project_setting(project_settings, phase, key, default)
    if value is None:
        return None
    return _coerce_bool(value, default=bool(default))


def _project_setting(
    project_settings: dict[str, Any] | None,
    phase: str,
    key: str,
    default: Any,
) -> Any:
    settings = deep_import_settings_for_response(project_settings)
    return settings.get(phase, {}).get(key, default)


def _settings_are_frozen(project_settings: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(project_settings, dict)
        and project_settings.get(DEEP_IMPORT_FROZEN_SETTINGS_KEY) is True
    )


def _deep_import_env_name(phase: str, key: str) -> str:
    prefix = "DEEP_IMPORT" if phase == "global" else phase.upper()
    return f"{prefix}_{key.upper()}"


class _Invalid:
    pass


_INVALID = _Invalid()


def _coerce_value(phase: str, key: str, value: Any, default: Any) -> Any:
    if (phase, key) in _NULLABLE_INT_SETTINGS and value is None:
        return None
    if (phase, key) in _BOOL_SETTINGS:
        if value is None and default is None:
            return None
        return _coerce_bool(value, default=bool(default))

    try:
        parsed = float(value) if (phase, key) in _FLOAT_SETTINGS else int(value)
    except (TypeError, ValueError):
        return _INVALID

    if not _within_limits(phase, key, parsed):
        return _INVALID
    if (phase, key) in _FLOAT_SETTINGS:
        return parsed
    return int(parsed)


def _within_limits(phase: str, key: str, value: float | int) -> bool:
    low, high = DEEP_IMPORT_SETTING_LIMITS.get((phase, key), (None, None))
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int):
        return bool(value)
    return default


def _int_from_env(env_name: str) -> int | None:
    raw = os.getenv(env_name)
    if raw is None:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _float_from_env(env_name: str) -> float | None:
    raw = os.getenv(env_name)
    if raw is None:
        return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _bool_from_env(env_name: str) -> bool | None:
    raw = os.getenv(env_name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}
