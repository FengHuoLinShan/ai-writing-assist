"""Checkpoint and error helpers for Phase 2 scene entity extraction."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from modules.imports.entity_extraction.scene_entity_config import (
    PHASE2A_PROMPT_CONTRACT_VERSION,
)


def is_transport_failure(exc: Exception) -> bool:
    return isinstance(
        exc,
        (LLMConnectionError, LLMTimeoutError, LLMRateLimitError, TimeoutError),
    )


def error_kind(exc: Exception) -> str:
    if isinstance(exc, LLMConnectionError):
        return "connection_error"
    if isinstance(exc, LLMTimeoutError):
        return "timeout"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, LLMRateLimitError):
        return "rate_limit"
    if isinstance(exc, ValueError) and "valid json" in str(exc).lower():
        return "schema_error"
    return exc.__class__.__name__


def merge_alias_relation_result(
    service,
    phase2_result: dict[str, Any],
    alias_result: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(phase2_result)
    merged["total_aliases"] = int(alias_result.get("total_aliases", 0) or 0)
    merged["total_relations"] = int(merged.get("total_relations", 0) or 0) + int(
        alias_result.get("total_relations", 0) or 0
    )
    merged["alias_relation_scenes"] = int(
        alias_result.get("alias_relation_scenes", 0) or 0
    )
    merged["alias_relation_failed_scenes"] = alias_result.get(
        "alias_relation_failed_scenes",
        [],
    )
    merged["alias_relation_elapsed_s"] = alias_result.get("alias_relation_elapsed_s")
    merged["alias_relation_total_timeout_s"] = alias_result.get(
        "alias_relation_total_timeout_s"
    )
    merged["alias_relation_concurrency"] = alias_result.get("alias_relation_concurrency")
    merged["alias_relation_skipped"] = bool(alias_result.get("alias_relation_skipped"))
    merged["alias_relation_skip_reason"] = alias_result.get("alias_relation_skip_reason")
    merged["alias_relation_format_diagnostics"] = alias_result.get(
        "alias_relation_format_diagnostics",
        [],
    )
    alias_checkpoints = alias_result.get("alias_relation_checkpoints")
    if not isinstance(alias_checkpoints, dict):
        # Compatibility for older adapters/tests that returned the common key.
        alias_checkpoints = alias_result.get("checkpoints")
    if isinstance(alias_checkpoints, dict):
        merged["checkpoints"] = {
            **(merged.get("checkpoints") or {}),
            **alias_checkpoints,
        }
    if alias_result.get("degraded"):
        merged["degraded"] = True
        merged["error_kind"] = merged.get("error_kind") or alias_result.get("error_kind")
        merged["error_message"] = merged.get("error_message") or alias_result.get(
            "error_message"
        )
    return merged


def scene_id(scene: dict[str, Any]) -> str:
    if isinstance(scene, dict):
        raw_scene_id = scene.get("id") or scene.get("scene_id")
        scene_index = scene.get("scene_index", "")
    else:
        raw_scene_id = getattr(scene, "id", None) or getattr(scene, "scene_id", None)
        scene_index = getattr(scene, "scene_index", "")
    if raw_scene_id:
        return str(raw_scene_id)
    return f"scene_index:{scene_index}"


def scene_provenance_key(
    service,
    workflow_id: str | None,
    scene: dict[str, Any],
) -> str:
    return f"{workflow_id or 'manual'}:scene:{service._scene_id(scene)}"


def checkpoint_retry_count(checkpoint: dict[str, Any] | None) -> int:
    if not checkpoint:
        return 0
    try:
        return max(0, int(checkpoint.get("retry_count") or 0))
    except (TypeError, ValueError):
        return 0


_SCENE_FINGERPRINT_FIELDS = (
    "id",
    "scene_id",
    "novel_id",
    "scene_index",
    "title",
    "summary",
    "goal",
    "core_conflict",
    "conflict",
    "emotional_beat",
    "narrative_purpose",
    "narrative_tag",
    "pov_character_id",
    "must_happen",
    "must_not_happen",
    "chapter_ids",
    "scene_chunks",
    "structure_meta",
    "source",
    "status",
)


def scene_input_fingerprint(
    scene: dict[str, Any],
    scene_text: str,
    context_fingerprint: str | None = None,
) -> str:
    """Hash the semantic Scene input and exact text consumed by Phase 2."""
    payload = {
        "version": 2 if context_fingerprint else 1,
        "scene": {
            field: scene.get(field)
            for field in _SCENE_FINGERPRINT_FIELDS
            if field in scene
        },
        "scene_text": scene_text,
    }
    if context_fingerprint:
        payload["context_fingerprint"] = context_fingerprint
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def phase2a_input_fingerprint(
    scene: dict[str, Any],
    scene_text: str,
    *,
    context_fingerprint: str = "",
    base_fingerprint: str | None = None,
) -> str:
    """Hash every semantic input that can change a P13 model decision."""
    base_fingerprint = base_fingerprint or scene_input_fingerprint(scene, scene_text)
    encoded = (
        f"{base_fingerprint}:{context_fingerprint}:"
        f"{PHASE2A_PROMPT_CONTRACT_VERSION}"
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def phase2_checkpoint_by_scene(
    existing_checkpoints: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not existing_checkpoints:
        return {}

    scenes = existing_checkpoints.get("scenes")
    if scenes is None:
        phase2 = existing_checkpoints.get("phase2")
        if isinstance(phase2, dict):
            scenes = phase2.get("scenes")

    if isinstance(scenes, list):
        return {
            str(item["scene_id"]): item
            for item in scenes
            if isinstance(item, dict) and item.get("scene_id")
        }

    return {
        str(scene_id): checkpoint
        for scene_id, checkpoint in existing_checkpoints.items()
        if isinstance(checkpoint, dict)
    }


def build_scene_checkpoint(
    service,
    scene: dict[str, Any],
    *,
    status: str,
    workflow_id: str | None,
    scene_provenance_key: str,
    retry_count: int,
    created_entity_ids: list[str] | None = None,
    created_relation_ids: list[str] | None = None,
    created_delta_ids: list[str] | None = None,
    error: str | None = None,
    error_kind: str | None = None,
    activation_version: str | None = None,
    activation_source_count: int | None = None,
    input_fingerprint: str | None = None,
) -> dict[str, Any]:
    checkpoint = {
        "scene_id": service._scene_id(scene),
        "scene_index": scene.get("scene_index"),
        "status": status,
        "created_entity_ids": created_entity_ids or [],
        "created_relation_ids": created_relation_ids or [],
        "created_delta_ids": created_delta_ids or [],
        "retry_count": retry_count,
        "workflow_id": workflow_id,
        "scene_provenance_key": scene_provenance_key,
        "source": "deep_import",
        "auto_ingested": True,
    }
    if error is not None:
        checkpoint["error"] = error
    if error_kind is not None:
        checkpoint["error_kind"] = error_kind
    if activation_version is not None:
        checkpoint["activation_version"] = activation_version
    if activation_source_count is not None:
        checkpoint["activation_source_count"] = activation_source_count
    if input_fingerprint is not None:
        checkpoint["input_fingerprint"] = input_fingerprint
    return checkpoint


def filter_scenes_by_range(
    service,
    scenes: list[dict[str, Any]],
    *,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> list[dict[str, Any]]:
    if start_chapter is None and end_chapter is None:
        return scenes

    selected: list[dict[str, Any]] = []
    for scene in scenes:
        if service._scene_overlaps_chapter_range(
            scene,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        ):
            selected.append(scene)
    return selected


def scene_overlaps_chapter_range(
    scene: dict[str, Any],
    *,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> bool:
    start = start_chapter if start_chapter is not None else -(10**9)
    end = end_chapter if end_chapter is not None else 10**9
    chapter_ids = scene.get("chapter_ids") or []
    for chapter_id in chapter_ids:
        try:
            chapter_index = int(chapter_id)
        except (TypeError, ValueError):
            continue
        if start <= chapter_index <= end:
            return True
    chapter_indices: list[int] = []
    for raw in chapter_ids:
        try:
            chapter_indices.append(int(raw))
        except (TypeError, ValueError):
            continue
    source_chapter = (
        max(chapter_indices)
        if chapter_indices
        else scene.get(
            "scene_index",
            0,
        )
    )
    return start <= source_chapter <= end
