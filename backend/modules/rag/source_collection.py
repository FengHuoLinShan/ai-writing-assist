"""Source collection for RAG chapter indexing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from modules.rag.query_expansion import _load_project_terms


@dataclass(frozen=True)
class ChapterIndexSources:
    source_draft_id: str
    source_version_number: int
    source_content_hash: str
    content_mode: str
    content: str
    scenes_for_chapter: list[dict]
    scene_spans_for_chapter: list
    project_terms: list[dict[str, str]]
    entity_importance_map: dict[str, dict[str, object]]


def scenes_for_chapter(scenes: list[dict], chapter_index: int) -> list[dict]:
    """Return scenes that can annotate chunks for a chapter."""
    return [
        scene
        for scene in scenes
        if str(chapter_index) in (scene.get("chapter_ids") or [])
        and any(
            chunk.get("chapter_index") == chapter_index
            for chunk in (scene.get("scene_chunks") or [])
        )
    ]


async def collect_chapter_sources(
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapter_index: int,
    *,
    content_mode: str = "canonical",
) -> ChapterIndexSources | None:
    from modules.writing.facade import list_manuscript_sources

    drafts = await list_manuscript_sources(
        db,
        str(novel_id),
        [chapter_index],
        content_mode=content_mode,
    )
    draft = drafts[0] if drafts else None
    if not draft or not draft.content:
        return None

    (
        scenes_for_chapter_value,
        scene_spans_for_chapter_value,
        project_terms,
        entity_importance_map,
    ) = await collect_annotation_sources(
        db,
        novel_id,
        chapter_index,
        content_mode=content_mode,
        draft=draft,
    )

    return ChapterIndexSources(
        source_draft_id=str(draft.id),
        source_version_number=draft.version_number,
        source_content_hash=draft.content_hash,
        content_mode=content_mode,
        content=draft.content,
        scenes_for_chapter=scenes_for_chapter_value,
        scene_spans_for_chapter=scene_spans_for_chapter_value,
        project_terms=project_terms,
        entity_importance_map=entity_importance_map,
    )


async def collect_annotation_sources(
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapter_index: int,
    *,
    content_mode: str = "canonical",
    draft=None,
) -> tuple[
    list[dict],
    list,
    list[dict[str, str]],
    dict[str, dict[str, object]],
]:
    from modules.outline.facade import (
        bind_scene_spans_to_source,
        get_scene_spans_by_chapter,
        get_scenes_by_chapter,
    )

    scenes = await get_scenes_by_chapter(db, str(novel_id), chapter_index)
    if draft is not None and draft.id and draft.content:
        scene_spans = await bind_scene_spans_to_source(
            db,
            novel_id=str(novel_id),
            chapter_index=chapter_index,
            content_mode=content_mode,
            source_draft_id=str(draft.id),
            source_content_hash=draft.content_hash,
            content=draft.content,
        )
    else:
        scene_spans = await get_scene_spans_by_chapter(
            db,
            str(novel_id),
            chapter_index,
            content_mode=content_mode,
        )
    project_terms = await _load_project_terms(db, novel_id)
    entity_importance_map: dict[str, dict[str, object]] = {}
    try:
        _get_importance_map = _container_get("world.get_entity_importance_map")
        entity_importance_map = await _get_importance_map(db, str(novel_id))
    except Exception:
        entity_importance_map = {}
    return (
        scenes_for_chapter(scenes, chapter_index),
        scene_spans,
        project_terms,
        entity_importance_map,
    )
