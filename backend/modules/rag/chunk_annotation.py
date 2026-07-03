"""Chunk annotation for RAG chapter indexing."""

from __future__ import annotations

import uuid

from modules.rag.chunking import ChineseNovelChunk, ChunkingService
from modules.rag.query_expansion import _match_project_terms
from modules.rag.schemas import RagChunkCreate

RAG_INDEX_VERSION = "cn-novel-v1"


def resolve_scene_id_for_chunk(
    cn_chunk: ChineseNovelChunk,
    scenes_for_chapter: list[dict],
) -> uuid.UUID | None:
    """Return the first matching scene id for a chunk."""
    chunk_start = cn_chunk.start_offset
    chunk_end = cn_chunk.end_offset
    fallback_scene_id: uuid.UUID | None = None
    for scene in scenes_for_chapter:
        scene_id_str = scene.get("id")
        if not scene_id_str:
            continue
        for scene_chunk in scene.get("scene_chunks", []):
            scene_chunk_start = scene_chunk.get("start_pos")
            scene_chunk_end = scene_chunk.get("end_pos")
            if scene_chunk_start is None or scene_chunk_end is None:
                if fallback_scene_id is None:
                    fallback_scene_id = uuid.UUID(hex=scene_id_str)
                continue
            if chunk_start < scene_chunk_end and chunk_end > scene_chunk_start:
                return uuid.UUID(hex=scene_id_str)
    return fallback_scene_id


def chunk_importance(
    entity_ids: list[str],
    entity_importance_map: dict[str, dict[str, object]],
) -> float:
    if not entity_ids or not entity_importance_map:
        return 0.5
    max_importance = 0.5
    has_core = False
    for entity_id in entity_ids:
        info = entity_importance_map.get(entity_id)
        if not info:
            continue
        importance_value = float(info["importance"])
        if importance_value > max_importance:
            max_importance = importance_value
        if info.get("importance_level") == "core":
            has_core = True
    return min(1.0, max_importance + (0.2 if has_core else 0.0))


def build_chunk_create(
    cn_chunk: ChineseNovelChunk,
    *,
    chapter_index: int,
    chunking: ChunkingService,
    project_terms: list[dict[str, str]],
    entity_importance_map: dict[str, dict[str, object]],
    scenes_for_chapter: list[dict],
    chunk_index: int | None = None,
) -> RagChunkCreate:
    character_ids, entity_ids, thread_ids = _match_project_terms(
        cn_chunk.text,
        project_terms,
    )
    scene_id = resolve_scene_id_for_chunk(cn_chunk, scenes_for_chapter)
    return RagChunkCreate(
        source_type="chapter_text",
        chapter_index=chapter_index,
        chunk_index=cn_chunk.chunk_index if chunk_index is None else chunk_index,
        start_offset=cn_chunk.start_offset,
        end_offset=cn_chunk.end_offset,
        char_count=cn_chunk.char_count,
        text=cn_chunk.text,
        summary=chunking.extract_summary(cn_chunk.text),
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        scene_id=str(scene_id) if scene_id else None,
        visibility="author_only",
        importance=chunk_importance(entity_ids, entity_importance_map),
        index_version=RAG_INDEX_VERSION,
        embedding_status="pending",
        meta={
            "chapter_index": chapter_index,
            "chunk_index": cn_chunk.chunk_index if chunk_index is None else chunk_index,
        },
    )
