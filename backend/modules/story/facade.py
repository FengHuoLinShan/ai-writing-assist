"""Stable Story facade for APIs, workers, and future Scene consumers."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.generation import (
    STORY_CARD_TASK,
    STORY_CHARACTER_CARD_ACTION,
    STORY_ONE_CLICK_ACTION,
    STORY_ONE_CLICK_TASK,
    STORY_REACTION_ACTION,
    STORY_REACTION_TASK,
    STORY_SCRIPT_ACTION,
    STORY_SCRIPT_TASK,
)
from modules.story.schemas import CharacterCardContent, OneClickOutput
from modules.story.service import (
    StoryConflictError,
    StoryNotFoundError,
    StoryService,
)

_service = StoryService()

# Story is the physical owner of the authoring workflow.  The two internal
# subdomains keep their own locality, while this root facade is the stable
# cross-module seam during and after the compatibility release.
from modules.story.continuity.facade import (  # noqa: E402,F401
    capture_snapshot,
    count_deep_import_delta_logs_by_workflow,
    create_delta_log,
    ensure_scene_checkpoints,
    get_continuity_evidence_for_writing,
    get_memory_panorama,
    get_scene_checkpoints,
    ingest_delta_events,
    replace_scene_memory_events,
    rollback_deep_import_delta_logs_by_workflow,
)
from modules.story.outline_state.facade import *  # noqa: E402,F401,F403
from modules.story.outline_state.facade import (  # noqa: E402,F401
    __all__ as _outline_state_facade_exports,
)


async def get_character_card(
    db: AsyncSession,
    novel_id: str,
    card_id: str,
):
    return await _service.get_card(db, novel_id, card_id)


async def list_character_cards(
    db: AsyncSession,
    novel_id: str,
    *,
    scene_id: str | None = None,
    character_ids: Iterable[str] | None = None,
):
    return await _service.list_cards(
        db,
        novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
    )


async def list_character_card_revisions(
    db: AsyncSession,
    novel_id: str,
    card_id: str,
):
    return await _service.list_card_revisions(db, novel_id, card_id)


async def create_manual_character_card(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    character_id: str,
    content: CharacterCardContent,
    expected_revision_id: uuid.UUID | None = None,
    source_manifest: dict[str, Any] | None = None,
    source_task_id: uuid.UUID | None = None,
    context_snapshot_id: uuid.UUID | None = None,
):
    return await _service.create_manual_card(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_id=character_id,
        content=content,
        expected_revision_id=expected_revision_id,
        source_manifest=source_manifest,
        source_task_id=source_task_id,
        context_snapshot_id=context_snapshot_id,
    )


async def restore_character_card_revision(
    db: AsyncSession,
    *,
    novel_id: str,
    card_id: str,
    revision_id: uuid.UUID,
    expected_revision_id: uuid.UUID | None,
):
    return await _service.restore_card_revision(
        db,
        novel_id=novel_id,
        card_id=card_id,
        revision_id=revision_id,
        expected_revision_id=expected_revision_id,
    )


async def archive_character_card_revision(
    db: AsyncSession,
    *,
    novel_id: str,
    card_id: str,
    revision_id: uuid.UUID,
    expected_revision_id: uuid.UUID | None,
) -> None:
    await _service.archive_card_revision(
        db,
        novel_id=novel_id,
        card_id=card_id,
        revision_id=revision_id,
        expected_revision_id=expected_revision_id,
    )


async def create_scene_script_file(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    file_key: str,
    title: str,
):
    return await _service.create_script_file(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        file_key=file_key,
        title=title,
    )


async def list_scene_script_files(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
):
    return await _service.list_script_files(db, novel_id, scene_id)


async def get_scene_script_file(db: AsyncSession, novel_id: str, file_id: str):
    return await _service.get_script_file(db, novel_id, file_id)


async def list_scene_script_revisions(
    db: AsyncSession,
    *,
    novel_id: str,
    file_id: str,
):
    return await _service.list_script_revisions(db, novel_id, file_id)


async def create_scene_script_revision(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    file_key: str,
    content: str,
    content_json: dict[str, Any] | list[Any] | None,
    expected_revision_id: uuid.UUID | None,
    adopt: bool,
    provenance: dict[str, Any] | None = None,
    expected_adopted_revision_id: uuid.UUID | None = None,
    source_task_id: uuid.UUID | None = None,
    context_snapshot_id: uuid.UUID | None = None,
):
    return await _service.create_script_revision(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        file_key=file_key,
        content=content,
        content_json=content_json,
        expected_revision_id=expected_revision_id,
        adopt=adopt,
        provenance=provenance,
        expected_adopted_revision_id=expected_adopted_revision_id,
        source_task_id=source_task_id,
        context_snapshot_id=context_snapshot_id,
    )


async def adopt_scene_script_revision(
    db: AsyncSession,
    *,
    novel_id: str,
    file_id: str,
    revision_id: uuid.UUID,
    expected_revision_id: uuid.UUID | None,
):
    return await _service.adopt_script_revision(
        db,
        novel_id=novel_id,
        file_id=file_id,
        revision_id=revision_id,
        expected_revision_id=expected_revision_id,
    )


async def archive_scene_script_revision(
    db: AsyncSession,
    *,
    novel_id: str,
    file_id: str,
    revision_id: uuid.UUID,
) -> None:
    await _service.archive_script_revision(
        db,
        novel_id=novel_id,
        file_id=file_id,
        revision_id=revision_id,
    )


async def unadopt_scene_script_file(
    db: AsyncSession,
    *,
    novel_id: str,
    file_id: str,
    expected_revision_id: uuid.UUID,
):
    return await _service.unadopt_script_file(
        db,
        novel_id=novel_id,
        file_id=file_id,
        expected_revision_id=expected_revision_id,
    )


async def get_scene_story_context(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    character_ids: Iterable[str] | None = None,
):
    return await _service.get_scene_story_context(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
    )


async def get_scene_story_assets(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    character_ids: Iterable[str] | None = None,
):
    return await _service.get_scene_story_assets(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
    )


async def get_scene_story_basis_hash(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    exclude_file_id: str | None = None,
) -> str:
    return await _service.get_scene_story_basis_hash(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        exclude_file_id=exclude_file_id,
    )


async def persist_one_click_character_cards(
    db: AsyncSession,
    *,
    novel_id: str,
    output: OneClickOutput,
    requested_character_ids: list[str],
    submit_authorized: bool,
    authorization_ref: str,
    source_task_id: uuid.UUID | None = None,
    context_snapshot_id: uuid.UUID | None = None,
    source_hashes: dict[str, str] | None = None,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    return await _service.persist_one_click_cards(
        db,
        novel_id=novel_id,
        output=output,
        requested_character_ids=requested_character_ids,
        submit_authorized=submit_authorized,
        authorization_ref=authorization_ref,
        source_task_id=source_task_id,
        context_snapshot_id=context_snapshot_id,
        source_hashes=source_hashes,
    )


__all__ = [
    "STORY_CARD_TASK",
    "STORY_CHARACTER_CARD_ACTION",
    "STORY_ONE_CLICK_ACTION",
    "STORY_ONE_CLICK_TASK",
    "STORY_REACTION_ACTION",
    "STORY_REACTION_TASK",
    "STORY_SCRIPT_ACTION",
    "STORY_SCRIPT_TASK",
    "StoryConflictError",
    "StoryNotFoundError",
    "archive_character_card_revision",
    "archive_scene_script_revision",
    "unadopt_scene_script_file",
    "adopt_scene_script_revision",
    "create_manual_character_card",
    "create_scene_script_file",
    "create_scene_script_revision",
    "get_character_card",
    "get_scene_script_file",
    "get_scene_story_assets",
    "get_scene_story_basis_hash",
    "get_scene_story_context",
    "list_character_card_revisions",
    "list_character_cards",
    "list_scene_script_files",
    "list_scene_script_revisions",
    "persist_one_click_character_cards",
    "restore_character_card_revision",
    *_outline_state_facade_exports,
    "capture_snapshot",
    "count_deep_import_delta_logs_by_workflow",
    "create_delta_log",
    "ensure_scene_checkpoints",
    "get_continuity_evidence_for_writing",
    "get_memory_panorama",
    "get_scene_checkpoints",
    "ingest_delta_events",
    "replace_scene_memory_events",
    "rollback_deep_import_delta_logs_by_workflow",
]
