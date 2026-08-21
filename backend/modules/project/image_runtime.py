"""Project-owned runtime seam for the fixed OpenAI image connection."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from infrastructure.llm.image_client import (
    OPENAI_IMAGE_BASE_URL,
    OPENAI_IMAGE_MODEL,
    OpenAIImageClient,
)
from modules.account.facade import resolve_account_image_runtime_profile
from modules.project.contracts import ProjectImageConfigurationError
from modules.project.services import ProjectService

PROJECT_IMAGE_EXECUTION_SNAPSHOT_VERSION = "1"
_service = ProjectService()


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _resolve_profile(db: AsyncSession, novel_id: str):
    context = await _service.get_project_context(db, novel_id, project_kind=None)
    if context is None:
        raise NotFoundError(f"Project {novel_id} not found")
    owner_id = uuid.UUID(context.owner_id) if context.owner_id else None
    try:
        profile = await resolve_account_image_runtime_profile(db, owner_id=owner_id)
    except ValueError as exc:
        raise ProjectImageConfigurationError(str(exc)) from exc
    return context, profile


async def build_project_image_execution_snapshot(
    db: AsyncSession,
    novel_id: str,
) -> dict[str, Any]:
    """Freeze non-secret image routing while allowing later key rotation."""
    context, profile = await _resolve_profile(db, novel_id)
    payload = {
        "version": PROJECT_IMAGE_EXECUTION_SNAPSHOT_VERSION,
        "novel_id": str(novel_id),
        "owner_id": context.owner_id,
        "provider_id": profile.provider_id,
        "model": profile.model,
        "base_url": profile.base_url,
    }
    payload["snapshot_hash"] = _snapshot_hash(payload)
    return payload


async def restore_project_image_runtime_profile(
    db: AsyncSession,
    novel_id: str,
    snapshot: dict[str, Any],
):
    if not isinstance(snapshot, dict):
        raise ProjectImageConfigurationError("Project image snapshot is required")
    unsigned = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if (
        snapshot.get("version") != PROJECT_IMAGE_EXECUTION_SNAPSHOT_VERSION
        or str(snapshot.get("novel_id") or "") != str(novel_id)
        or not snapshot.get("snapshot_hash")
        or _snapshot_hash(unsigned) != snapshot["snapshot_hash"]
    ):
        raise ProjectImageConfigurationError("Project image snapshot is invalid")
    context, profile = await _resolve_profile(db, novel_id)
    expected = {
        "owner_id": context.owner_id,
        "provider_id": profile.provider_id,
        "model": OPENAI_IMAGE_MODEL,
        "base_url": OPENAI_IMAGE_BASE_URL,
    }
    if any(snapshot.get(key) != value for key, value in expected.items()):
        raise ProjectImageConfigurationError(
            "Project image connection changed after this run started"
        )
    return profile


@asynccontextmanager
async def open_project_image_client(
    db: AsyncSession,
    novel_id: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> AsyncIterator[OpenAIImageClient]:
    """Open the owner's fixed GPT Image 2 connection for one project."""
    if snapshot is None:
        _context, profile = await _resolve_profile(db, novel_id)
    else:
        profile = await restore_project_image_runtime_profile(db, novel_id, snapshot)
    client = OpenAIImageClient(api_key=profile.api_key, timeout=profile.timeout)
    try:
        yield client
    finally:
        await client.close()
