"""Async Story preview handlers registered in the application task manifest."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from infrastructure.llm.agent_step_harness import managed_llm_provenance_scope
from infrastructure.tasks.facade import require_task_checkpoint_session
from infrastructure.tasks.registry import task_handler
from modules.evidence.facade import (
    compile_from_confirmation,
    compile_with_tiers,
    create_context_snapshot,
    render_compiled_context,
)
from modules.project.facade import (
    create_project_snapshot_llm_client,
    require_active_project_exclusive,
    restore_project_llm_execution_settings,
)
from modules.story.facade import (
    STORY_CARD_TASK,
    STORY_CHARACTER_CARD_ACTION,
    STORY_ONE_CLICK_ACTION,
    STORY_ONE_CLICK_TASK,
    STORY_REACTION_ACTION,
    STORY_REACTION_TASK,
    STORY_SCRIPT_ACTION,
    STORY_SCRIPT_TASK,
    StoryConflictError,
    get_scene_story_context,
    persist_one_click_character_cards,
)
from modules.story.generation import StoryGenerationService
from modules.story.schemas import (
    OneClickTaskResult,
    StoryCardTaskRequest,
    StoryOneClickTaskRequest,
    StoryTaskRequest,
)

logger = logging.getLogger(__name__)


def _stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _outline_source_payload(scene_payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the outline input stable without feeding a card back into itself."""
    outline = scene_payload.get("outline_bundle")
    if not isinstance(outline, dict):
        return {}
    payload = dict(outline)
    # Outline's optional Story enrichment is an execution consumer, not a
    # source for the next card revision.  In particular, including the current
    # card here would make every saved card invalidate itself.
    payload.pop("story_assets", None)
    payload.pop("story_assets_hash", None)
    manifest = payload.get("upstream_manifest")
    if isinstance(manifest, list):
        payload["upstream_manifest"] = [
            item
            for item in manifest
            if not (
                isinstance(item, dict)
                and item.get("type")
                in {"story_character_card", "story_scene_script_adopted"}
            )
        ]
    return payload


def _character_card_source_hashes(
    scene_payload: dict[str, Any],
    compiled: Any,
    context_markdown: str,
    character_ids: list[str],
) -> dict[str, str]:
    """Fingerprint only external Scene/context inputs for one-click cards."""
    sections = []
    for section in getattr(compiled, "sections", []) or []:
        sections.append(
            {
                "key": section.key,
                "tier": int(section.tier),
                "content": section.content,
                "status": section.status,
                "sources": section.sources,
            }
        )
    compiled_payload = {
        "sections": sections,
        "budget_tokens": int(getattr(compiled, "budget_tokens", 0)),
        "warnings": list(getattr(compiled, "warnings", []) or []),
    }
    shared = {
        "outline_bundle": _outline_source_payload(scene_payload),
        "compiled_context_hash": _stable_hash(compiled_payload),
        "compiled_text_hash": _text_hash(context_markdown),
    }
    return {
        str(character_id): _stable_hash({**shared, "character_id": str(character_id)})
        for character_id in character_ids
    }


async def _require_snapshot(
    db, task, meta: dict[str, Any], novel_id: str
) -> dict[str, Any]:
    require_task_checkpoint_session(db)
    snapshot = meta.get("llm_execution_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("llm_execution_snapshot is required for Story tasks")
    if str(snapshot.get("novel_id") or "") != str(novel_id):
        raise ValueError("llm_execution_snapshot novel_id mismatch")
    return dict(snapshot)


async def _checkpoint_before_provider(db) -> None:
    await db.commit()
    if db.in_transaction():
        raise RuntimeError(
            "Story provider execution requires a transaction-free checkpoint"
        )
    db.expire_all()


async def _prepare_task_input(
    db,
    task,
    *,
    action: str,
    request_model: type[Any],
) -> tuple[Any, str, dict[str, Any], dict[str, Any], str | None]:
    meta = dict(task.meta or {})
    if meta.get("action") != action:
        raise ValueError(f"invalid action for {task.task_type}")
    data = request_model.model_validate(meta)
    snapshot = await _require_snapshot(db, task, meta, data.novel_id)
    if action == STORY_ONE_CLICK_ACTION:
        character_ids = _require_character_ids(data.character_ids)
        compiled = await compile_with_tiers(
            db,
            data.novel_id,
            task=action,
            scope="scene",
            scene_id=data.scene_id,
            budget_tokens=8000,
            character_ids=character_ids,
            reveal_mode="author_full",
            consumer_action=action,
            retrieval_purpose="story_scene_one_click",
            user_note=data.additional_notes,
        )
    else:
        compiled = await compile_from_confirmation(
            db,
            novel_id=data.novel_id,
            action=action,
            confirmation_id=data.context_confirmation_id,
        )
    context_markdown = render_compiled_context(compiled)
    selected_ids = (
        list(data.character_ids)
        if hasattr(data, "character_ids")
        else [data.character_id]
    )
    story_context = await get_scene_story_context(
        db,
        novel_id=data.novel_id,
        scene_id=data.scene_id,
        character_ids=selected_ids,
    )
    if story_context is None:
        raise ValueError("scene does not belong to this novel")
    scene_payload = story_context.model_dump(mode="json")
    context_snapshot_id: str | None = None
    if action == STORY_ONE_CLICK_ACTION:
        section_metadata = {
            section.key: {
                "tier": int(section.tier),
                "status": section.status,
                "token_count": section.token_count,
                "source_count": len(section.sources),
            }
            for section in compiled.sections
        }
        context_snapshot = await create_context_snapshot(
            db,
            novel_id=data.novel_id,
            task_id=str(task.id),
            phase="story",
            operation=action,
            scene_id=data.scene_id,
            context_mode="working",
            include_pending_objects=False,
            prompt_name="story.one_click.simulate",
            model=str((snapshot.get("profile") or {}).get("model") or "project-default"),
            compile_options={
                "novel_id": data.novel_id,
                "task": action,
                "scope": "scene",
                "scene_id": data.scene_id,
                "character_ids": selected_ids,
                "additional_notes": getattr(data, "additional_notes", None),
                "accepted_reactions": [
                    item.model_dump(mode="json")
                    for item in getattr(data, "accepted_reactions", [])
                ],
                "accepted_beats": [
                    item.model_dump(mode="json")
                    for item in getattr(data, "accepted_beats", [])
                ],
                "budget_tokens": compiled.budget_tokens,
                "reveal_mode": "author_full",
            },
            included_asset_ids={
                "scenes": [data.scene_id],
                "characters": selected_ids,
            },
            context_summary={
                "context_hash": story_context.context_hash,
                "total_tokens": compiled.total_tokens,
                "warnings": list(compiled.warnings),
            },
            section_metadata=section_metadata,
            token_metadata={
                "total_tokens": compiled.total_tokens,
                "budget_tokens": compiled.budget_tokens,
            },
            rendered_context=context_markdown,
            retain_rendered_context=False,
        )
        context_snapshot_id = str(context_snapshot.id)
        task.meta = {
            **(task.meta or {}),
            "context_snapshot_id": context_snapshot_id,
            "character_card_source_hashes": _character_card_source_hashes(
                scene_payload,
                compiled,
                context_markdown,
                selected_ids,
            ),
        }
    runtime_settings = await restore_project_llm_execution_settings(
        db,
        data.novel_id,
        snapshot,
    )
    await _checkpoint_before_provider(db)
    return (
        data,
        context_markdown,
        scene_payload,
        runtime_settings,
        context_snapshot_id,
    )


@asynccontextmanager
async def _open_client(settings: dict[str, Any], novel_id: str) -> AsyncIterator[Any]:
    client = create_project_snapshot_llm_client(settings, novel_id=novel_id)
    try:
        yield client
    finally:
        await client.close()


def _record_provenance(task, records: list[dict[str, Any]]) -> None:
    task.meta = {**(task.meta or {}), "managed_llm_steps": records}


def _require_character_ids(values: list[str]) -> list[str]:
    if not values:
        raise ValueError("character_ids must contain at least one character")
    return list(values)


@task_handler(
    STORY_CARD_TASK,
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_story_character_card_generate(db, task):
    (
        data,
        context_markdown,
        story_context,
        settings,
        _context_snapshot_id,
    ) = await _prepare_task_input(
        db,
        task,
        action=STORY_CHARACTER_CARD_ACTION,
        request_model=StoryCardTaskRequest,
    )
    generation = StoryGenerationService()
    task.update_progress(0.1)
    async with _open_client(settings, data.novel_id) as client:
        with managed_llm_provenance_scope() as records:
            preview = await generation.card_preview(
                client,
                context_markdown=context_markdown,
                scene_context=story_context,
                character_id=data.character_id,
                additional_notes=data.additional_notes,
            )
        _record_provenance(task, records)
    task.update_progress(1.0)
    await db.flush()
    return {
        "preview": preview.model_dump(mode="json"),
        "preview_only": True,
        "writes": [],
    }


@task_handler(
    STORY_REACTION_TASK,
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_story_reaction_propose(db, task):
    (
        data,
        context_markdown,
        story_context,
        settings,
        _context_snapshot_id,
    ) = await _prepare_task_input(
        db,
        task,
        action=STORY_REACTION_ACTION,
        request_model=StoryTaskRequest,
    )
    character_ids = _require_character_ids(data.character_ids)
    generation = StoryGenerationService()
    task.update_progress(0.1)
    async with _open_client(settings, data.novel_id) as client:
        with managed_llm_provenance_scope() as records:
            preview = await generation.reaction_preview(
                client,
                context_markdown=context_markdown,
                scene_context=story_context,
                character_ids=character_ids,
                additional_notes=data.additional_notes,
            )
        _record_provenance(task, records)
    if str(preview.scene_id) != str(data.scene_id):
        raise ValueError("reaction preview scene_id mismatch")
    task.update_progress(1.0)
    await db.flush()
    return {
        "preview": preview.model_dump(mode="json"),
        "preview_only": True,
        "writes": [],
    }


@task_handler(
    STORY_SCRIPT_TASK,
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_story_scene_script_generate(db, task):
    (
        data,
        context_markdown,
        story_context,
        settings,
        _context_snapshot_id,
    ) = await _prepare_task_input(
        db,
        task,
        action=STORY_SCRIPT_ACTION,
        request_model=StoryTaskRequest,
    )
    character_ids = _require_character_ids(data.character_ids)
    generation = StoryGenerationService()
    task.update_progress(0.1)
    async with _open_client(settings, data.novel_id) as client:
        with managed_llm_provenance_scope() as records:
            preview = await generation.script_preview(
                client,
                context_markdown=context_markdown,
                scene_context=story_context,
                character_ids=character_ids,
                additional_notes=data.additional_notes,
                accepted_reactions=[
                    item.model_dump(mode="json") for item in data.accepted_reactions
                ],
                accepted_beats=[
                    item.model_dump(mode="json") for item in data.accepted_beats
                ],
            )
        _record_provenance(task, records)
    if str(preview.scene_id) != str(data.scene_id):
        raise ValueError("script preview scene_id mismatch")
    task.update_progress(1.0)
    await db.flush()
    return {
        "preview": preview.model_dump(mode="json"),
        "preview_only": True,
        "writes": [],
    }


@task_handler(
    STORY_ONE_CLICK_TASK,
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_story_one_click(db, task):
    (
        data,
        context_markdown,
        story_context,
        settings,
        context_snapshot_id,
    ) = await _prepare_task_input(
        db,
        task,
        action=STORY_ONE_CLICK_ACTION,
        request_model=StoryOneClickTaskRequest,
    )
    character_ids = _require_character_ids(data.character_ids)
    generation = StoryGenerationService()
    task.update_progress(0.1)
    async with _open_client(settings, data.novel_id) as client:
        with managed_llm_provenance_scope() as records:
            preview = await generation.one_click_preview(
                client,
                context_markdown=context_markdown,
                scene_context=story_context,
                character_ids=character_ids,
                additional_notes=data.additional_notes,
                accepted_reactions=[
                    item.model_dump(mode="json") for item in data.accepted_reactions
                ],
                accepted_beats=[
                    item.model_dump(mode="json") for item in data.accepted_beats
                ],
            )
        _record_provenance(task, records)
    if str(preview.scene_id) != str(data.scene_id):
        raise ValueError("one-click preview scene_id mismatch")
    await require_active_project_exclusive(db, data.novel_id)
    latest_context = await get_scene_story_context(
        db,
        novel_id=data.novel_id,
        scene_id=data.scene_id,
        character_ids=character_ids,
    )
    if (
        latest_context is None
        or latest_context.context_hash != story_context["context_hash"]
    ):
        raise StoryConflictError(
            "Scene, outline, or selected character cards changed while "
            "one-click was running"
        )
    latest_compiled = await compile_with_tiers(
        db,
        data.novel_id,
        task=STORY_ONE_CLICK_ACTION,
        scope="scene",
        scene_id=data.scene_id,
        budget_tokens=8000,
        character_ids=character_ids,
        reveal_mode="author_full",
        consumer_action=STORY_ONE_CLICK_ACTION,
        retrieval_purpose="story_scene_one_click",
        user_note=data.additional_notes,
    )
    latest_source_hashes = _character_card_source_hashes(
        latest_context.model_dump(mode="json"),
        latest_compiled,
        render_compiled_context(latest_compiled),
        character_ids,
    )
    expected_source_hashes = (task.meta or {}).get("character_card_source_hashes")
    if (
        isinstance(expected_source_hashes, dict)
        and expected_source_hashes != latest_source_hashes
    ):
        raise StoryConflictError(
            "Scene or compiled context changed while one-click was running"
        )
    persisted, skipped_fresh = await persist_one_click_character_cards(
        db,
        novel_id=data.novel_id,
        output=preview,
        requested_character_ids=character_ids,
        submit_authorized=bool((task.meta or {}).get("submit_authorized", False)),
        authorization_ref=f"task:{task.id}",
        source_task_id=task.id,
        context_snapshot_id=uuid.UUID(context_snapshot_id)
        if context_snapshot_id
        else None,
        source_hashes=latest_source_hashes,
    )
    task.update_progress(1.0)
    await db.flush()
    result = OneClickTaskResult(
        preview=preview,
        context_snapshot_id=uuid.UUID(context_snapshot_id)
        if context_snapshot_id
        else None,
        persisted_card_revision_ids=persisted,
        skipped_fresh_character_ids=skipped_fresh,
        preview_only_writes=[],
    )
    return result.model_dump(mode="json")
