"""Source collection for RAG chapter indexing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from modules.rag.query_expansion import _load_project_terms


@dataclass(frozen=True)
class ChapterIndexSources:
    content: str
    scenes_for_chapter: list[dict]
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
) -> ChapterIndexSources | None:
    _get_latest_draft = _container_get("writing.get_latest_draft_for_chapter")
    draft = await _get_latest_draft(db, str(novel_id), chapter_index)
    if not draft or not draft.content:
        return None

    scenes_for_chapter_value, project_terms, entity_importance_map = (
        await collect_annotation_sources(db, novel_id, chapter_index)
    )

    return ChapterIndexSources(
        content=draft.content,
        scenes_for_chapter=scenes_for_chapter_value,
        project_terms=project_terms,
        entity_importance_map=entity_importance_map,
    )


async def collect_annotation_sources(
    db: AsyncSession,
    novel_id: uuid.UUID,
    chapter_index: int,
) -> tuple[
    list[dict],
    list[dict[str, str]],
    dict[str, dict[str, object]],
]:
    from modules.outline.facade import get_scenes_by_chapter

    scenes = await get_scenes_by_chapter(db, str(novel_id), chapter_index)
    project_terms = await _load_project_terms(db, novel_id)
    entity_importance_map: dict[str, dict[str, object]] = {}
    try:
        _get_importance_map = _container_get("world.get_entity_importance_map")
        entity_importance_map = await _get_importance_map(db, str(novel_id))
    except Exception:
        entity_importance_map = {}
    return scenes_for_chapter(scenes, chapter_index), project_terms, entity_importance_map
