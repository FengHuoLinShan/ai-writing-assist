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


def resolve_scene_span_for_chunk(
    cn_chunk: ChineseNovelChunk,
    scene_spans_for_chapter: list,
    *,
    source_draft_id: str | None = None,
    source_content_hash: str | None = None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return the best Scene/SceneSpan pair for a chunk."""
    chunk_start = cn_chunk.start_offset
    chunk_end = cn_chunk.end_offset
    for span in scene_spans_for_chapter:
        if getattr(span, "mapping_status", None) not in {"exact", "reanchored"}:
            continue
        if source_draft_id and str(getattr(span, "source_draft_id", "")) != str(
            source_draft_id
        ):
            continue
        if (
            source_content_hash
            and getattr(span, "source_content_hash", None) != source_content_hash
        ):
            continue
        scene_id_value = getattr(span, "scene_id", None)
        span_id_value = getattr(span, "id", None)
        if not scene_id_value or not span_id_value:
            continue
        try:
            scene_id = uuid.UUID(str(scene_id_value))
            span_id = uuid.UUID(str(span_id_value))
        except (TypeError, ValueError):
            continue
        span_start = getattr(span, "start_offset", None)
        span_end = getattr(span, "end_offset", None)
        if span_start is None or span_end is None:
            continue
        if chunk_start < span_end and chunk_end > span_start:
            return scene_id, span_id
    return None, None


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
    content_mode: str = "canonical",
    source_draft_id: str | None = None,
    source_content_hash: str | None = None,
    chunking: ChunkingService,
    project_terms: list[dict[str, str]],
    entity_importance_map: dict[str, dict[str, object]],
    scenes_for_chapter: list[dict],
    scene_spans_for_chapter: list | None = None,
    chunk_index: int | None = None,
) -> RagChunkCreate:
    character_ids, entity_ids, thread_ids = _match_project_terms(
        cn_chunk.text,
        project_terms,
    )
    scene_id, scene_span_id = resolve_scene_span_for_chunk(
        cn_chunk,
        scene_spans_for_chapter or [],
        source_draft_id=source_draft_id,
        source_content_hash=source_content_hash,
    )
    if scene_id is None and not scene_spans_for_chapter:
        scene_id = resolve_scene_id_for_chunk(cn_chunk, scenes_for_chapter)
    return RagChunkCreate(
        source_type="chapter_text",
        source_id=source_draft_id,
        content_mode=content_mode,
        source_content_hash=source_content_hash,
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
        scene_span_id=str(scene_span_id) if scene_span_id else None,
        visibility="reader_known",
        importance=chunk_importance(entity_ids, entity_importance_map),
        index_version=RAG_INDEX_VERSION,
        embedding_status="pending",
        meta={
            "chapter_index": chapter_index,
            "chunk_index": cn_chunk.chunk_index if chunk_index is None else chunk_index,
        },
    )
