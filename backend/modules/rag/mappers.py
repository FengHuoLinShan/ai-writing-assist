"""RAG ORM → Contract 映射器。纯函数，无副作用。"""

from __future__ import annotations

from modules.rag.contracts import RagChunkContract


def chunk_orm_to_contract(
    chunk,
    score: float | None = None,
) -> RagChunkContract:
    return RagChunkContract(
        id=str(chunk.id),
        novel_id=str(chunk.novel_id),
        source_type=chunk.source_type,
        source_id=str(chunk.source_id) if chunk.source_id else None,
        chapter_index=chunk.chapter_index,
        chunk_index=chunk.chunk_index,
        start_offset=chunk.start_offset,
        end_offset=chunk.end_offset,
        char_count=chunk.char_count,
        text=chunk.text,
        summary=chunk.summary,
        entity_ids=chunk.entity_ids or [],
        character_ids=chunk.character_ids or [],
        thread_ids=chunk.thread_ids or [],
        visibility=chunk.visibility,
        importance=chunk.importance,
        index_version=chunk.index_version,
        embedding_status=chunk.embedding_status,
        embedding_error=chunk.embedding_error,
        index_warnings=chunk.index_warnings or [],
        meta=chunk.meta or {},
        score=round(score, 4) if score is not None else None,
    )
