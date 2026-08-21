"""Project-owned runtime seam for novel-scoped business LLM calls."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from infrastructure.llm.client import LLMClient
from infrastructure.llm.profiles import LLM_API_KEY_FIELD, resolve_llm_profile
from modules.account.facade import resolve_account_llm_runtime_profile
from modules.project.contracts import ProjectLLMConfigurationError
from modules.project.services import ProjectService
from shared.deep_import_settings import (
    DEEP_IMPORT_FROZEN_SETTINGS_KEY,
    materialize_effective_deep_import_settings,
)

MAX_LLM_TIMEOUT_OVERRIDE_SECONDS = 1800
PROJECT_LLM_EXECUTION_SNAPSHOT_VERSION = "1"
_RUNTIME_SOURCES_KEY = "_llm_runtime_sources"

_service = ProjectService()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _resolve_project_runtime_profile(
    db: AsyncSession,
    novel_id: str,
    *,
    provider_id: str | None = None,
) -> tuple[dict[str, Any], Any, dict[str, str]]:
    context = await _service.get_project_context(
        db,
        novel_id,
        project_kind=None,
    )
    if context is None:
        raise NotFoundError(f"Project {novel_id} not found")

    owner_id = uuid.UUID(context.owner_id) if context.owner_id else None
    try:
        account_profile = await resolve_account_llm_runtime_profile(
            db,
            owner_id=owner_id,
            provider_id=provider_id,
        )
    except ValueError as exc:
        raise ProjectLLMConfigurationError(str(exc)) from exc
    materialized = deepcopy(context.settings or {})
    materialized["llm"] = account_profile.model_dump()
    profile = resolve_llm_profile(materialized)
    sources = {
        field_name: "account"
        for field_name in (
            "provider_id",
            "label",
            "base_url",
            "model",
            "timeout",
            "max_tokens",
            "temperature",
            "top_p",
            "extra",
            "creative_mode",
            LLM_API_KEY_FIELD,
        )
    }
    return materialized, replace(profile, sources=sources), sources


async def build_project_llm_execution_snapshot(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any]:
    """Freeze a secret-free project runtime profile for a resumable task.

    Full base URLs, arbitrary ``extra`` values, and API keys are deliberately
    excluded because task metadata is returned by the task API. Their hashes
    let restore fail closed if the endpoint or provider-specific options drift;
    the current project key may rotate without exposing or persisting it here.
    """

    materialized, profile, sources = await _resolve_project_runtime_profile(
        db,
        novel_id,
    )
    summary = profile.sanitized_summary()
    public_profile = {
        "provider_id": summary["provider_id"],
        "label": summary["label"],
        "model": summary["model"],
        "base_url_host": summary["base_url_host"],
        "base_url_hash": _stable_hash(profile.base_url),
        "timeout": summary["timeout"],
        "max_tokens": summary["max_tokens"],
        "temperature": summary["temperature"],
        "top_p": summary["top_p"],
        "api_key_configured": summary["api_key_configured"],
        "extra_keys": summary["extra_keys"],
        "extra_hash": _stable_hash(profile.extra),
        "creative_mode": getattr(profile, "creative_mode", None),
    }
    payload: dict[str, Any] = {
        "version": PROJECT_LLM_EXECUTION_SNAPSHOT_VERSION,
        "novel_id": str(novel_id),
        "profile": public_profile,
        "sources": dict(sources),
        "deep_import": materialize_effective_deep_import_settings(
            materialized,
            inherited_llm_max_tokens=profile.max_tokens,
        ),
    }
    payload["profile_hash"] = _stable_hash(payload)
    return payload


async def restore_project_llm_execution_settings(
    db: AsyncSession,
    novel_id: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Restore executable settings from a validated secret-free snapshot."""

    if not isinstance(snapshot, dict):
        raise ProjectLLMConfigurationError("Project LLM execution snapshot is required")
    if snapshot.get("version") != PROJECT_LLM_EXECUTION_SNAPSHOT_VERSION:
        raise ProjectLLMConfigurationError("Unsupported project LLM snapshot version")
    if str(snapshot.get("novel_id") or "") != str(novel_id):
        raise ProjectLLMConfigurationError(
            "Project LLM execution snapshot novel_id mismatch"
        )
    expected_hash = str(snapshot.get("profile_hash") or "")
    unsigned = {key: value for key, value in snapshot.items() if key != "profile_hash"}
    if not expected_hash or _stable_hash(unsigned) != expected_hash:
        raise ProjectLLMConfigurationError("Project LLM execution snapshot hash mismatch")

    public_profile = snapshot.get("profile")
    sources = snapshot.get("sources")
    if not isinstance(public_profile, dict) or not isinstance(sources, dict):
        raise ProjectLLMConfigurationError("Project LLM execution snapshot is invalid")
    if public_profile.get("api_key_configured") is not True:
        raise ProjectLLMConfigurationError(
            "Project LLM API key was not configured when the task started"
        )
    if not public_profile.get("model") or not public_profile.get("base_url_hash"):
        raise ProjectLLMConfigurationError("Project LLM base_url and model are required")

    materialized, current_profile, _current_sources = (
        await _resolve_project_runtime_profile(
            db,
            novel_id,
            provider_id=str(public_profile.get("provider_id") or ""),
        )
    )
    if not current_profile.api_key:
        raise ProjectLLMConfigurationError("Project LLM API key is not configured")
    if not current_profile.base_url or not public_profile.get("model"):
        raise ProjectLLMConfigurationError("Project LLM base_url and model are required")
    if _stable_hash(current_profile.base_url) != public_profile.get("base_url_hash"):
        raise ProjectLLMConfigurationError(
            "Project LLM base_url changed after the task started"
        )
    if _stable_hash(current_profile.extra) != public_profile.get("extra_hash"):
        raise ProjectLLMConfigurationError(
            "Project LLM extra settings changed after the task started"
        )

    current_llm = dict(materialized.get("llm") or {})
    restored_llm: dict[str, Any] = {
        "provider_id": public_profile.get("provider_id"),
        "label": public_profile.get("label"),
        "base_url": current_profile.base_url,
        "model": public_profile.get("model"),
        "timeout": public_profile.get("timeout"),
        "max_tokens": public_profile.get("max_tokens"),
        "temperature": public_profile.get("temperature"),
        "top_p": public_profile.get("top_p"),
        "extra": deepcopy(current_profile.extra),
        "creative_mode": public_profile.get("creative_mode"),
        LLM_API_KEY_FIELD: current_llm.get(LLM_API_KEY_FIELD),
    }
    restored_llm = {
        key: value for key, value in restored_llm.items() if value is not None
    }
    return {
        "llm": restored_llm,
        "deep_import": deepcopy(snapshot.get("deep_import") or {}),
        DEEP_IMPORT_FROZEN_SETTINGS_KEY: True,
        _RUNTIME_SOURCES_KEY: dict(sources),
        "_llm_execution_profile_hash": expected_hash,
    }


def create_project_snapshot_llm_client(
    project_settings: dict,
    *,
    timeout_override: int | None = None,
    novel_id: str | None = None,
) -> LLMClient:
    """Create a client from a persisted effective project profile snapshot.

    Deep-import tasks persist their effective settings before worker execution.
    This seam validates the snapshot with the same fail-closed rules as the
    database-backed context manager. The caller owns closing the returned client.
    """
    if timeout_override is not None and not (
        1 <= timeout_override <= MAX_LLM_TIMEOUT_OVERRIDE_SECONDS
    ):
        raise ProjectLLMConfigurationError(
            "timeout_override must be between 1 and "
            f"{MAX_LLM_TIMEOUT_OVERRIDE_SECONDS} seconds"
        )
    profile = resolve_llm_profile(project_settings)
    snapshot_sources = project_settings.get(_RUNTIME_SOURCES_KEY)
    if isinstance(snapshot_sources, dict):
        profile = replace(profile, sources=dict(snapshot_sources))
    if timeout_override is not None:
        sources = dict(profile.sources)
        sources["timeout"] = "timeout_override"
        profile = replace(profile, timeout=timeout_override, sources=sources)
    if not profile.api_key:
        raise ProjectLLMConfigurationError(
            "Project LLM API key is not configured",
        )
    if not profile.base_url or not profile.model:
        raise ProjectLLMConfigurationError(
            "Project LLM base_url and model are required",
        )
    client = LLMClient.from_resolved_profile(profile)
    bind_runtime_scope = getattr(client, "bind_runtime_scope", None)
    if callable(bind_runtime_scope) and novel_id is not None:
        bind_runtime_scope(
            novel_id=novel_id,
            profile_source="project_snapshot",
        )
    return client


@asynccontextmanager
async def open_project_llm_client(
    db: AsyncSession,
    novel_id: str,
    *,
    timeout_override: int | None = None,
) -> AsyncIterator[LLMClient]:
    """Open one managed client for a novel-scoped business LLM workflow.

    Provider connection fields and secrets always come from the project's owner
    account. ``novel_id`` remains the isolation and ownership gate. Callers may
    only narrow or extend the request timeout within the bounded override.
    """
    if timeout_override is not None and not (
        1 <= timeout_override <= MAX_LLM_TIMEOUT_OVERRIDE_SECONDS
    ):
        raise ProjectLLMConfigurationError(
            "timeout_override must be between 1 and "
            f"{MAX_LLM_TIMEOUT_OVERRIDE_SECONDS} seconds"
        )

    _materialized, profile, sources = await _resolve_project_runtime_profile(
        db,
        novel_id,
    )
    if timeout_override is not None:
        profile = replace(profile, timeout=timeout_override)
        sources["timeout"] = "timeout_override"
    profile = replace(profile, sources=sources)

    if not profile.api_key:
        raise ProjectLLMConfigurationError(
            "Project LLM API key is not configured",
        )
    if not profile.base_url or not profile.model:
        raise ProjectLLMConfigurationError(
            "Project LLM base_url and model are required",
        )

    client = LLMClient.from_resolved_profile(profile)
    bind_runtime_scope = getattr(client, "bind_runtime_scope", None)
    if callable(bind_runtime_scope):
        bind_runtime_scope(
            novel_id=novel_id,
            profile_source=str(sources.get("model") or "system"),
        )
    try:
        yield client
    finally:
        await client.close()
