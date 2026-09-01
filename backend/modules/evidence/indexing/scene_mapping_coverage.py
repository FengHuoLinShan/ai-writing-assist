"""RAG chunk to Scene/SceneSpan mapping coverage."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.contracts import RagSceneMappingCoverageContract
from modules.evidence.indexing.repositories import RagChunkRepository


class RagSceneMappingCoverageService:
    def __init__(self, repository: RagChunkRepository | None = None) -> None:
        self._repo = repository or RagChunkRepository()

    async def get_coverage(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        content_mode: str,
    ) -> RagSceneMappingCoverageContract:
        from modules.story.facade import get_scene_span_coverage
        from modules.writing.facade import (
            list_effective_chapter_indices,
            list_manuscript_sources,
        )

        nid = uuid.UUID(str(novel_id))
        chapter_indices = await list_effective_chapter_indices(db, novel_id)
        sources = await list_manuscript_sources(
            db,
            novel_id,
            chapter_indices,
            content_mode=content_mode,
        )
        source_manifest = {
            uuid.UUID(source.id): source.content_hash
            for source in sources
            if source.id and source.content_hash
        }
        chunks = await self._repo.list_scene_mapping_rows(
            db,
            nid,
            content_mode=content_mode,
            source_manifest=source_manifest or None,
        )
        span_coverage = await get_scene_span_coverage(
            db,
            str(nid),
            content_mode=content_mode,
        )
        spans_by_id = {span.id: span for span in span_coverage.precise_spans}
        spans_by_chapter: dict[int, list] = {}
        for span in span_coverage.precise_spans:
            spans_by_chapter.setdefault(span.chapter_index, []).append(span)

        scene_mapped = 0
        span_mapped = 0
        expected_overlap = 0
        valid = 0
        dangling = 0
        wrong_source = 0

        for row in chunks:
            scene_id = str(row.scene_id) if row.scene_id else None
            span_id = str(row.scene_span_id) if row.scene_span_id else None
            scene_mapped += int(scene_id is not None)
            span_mapped += int(span_id is not None)

            overlaps = [
                span
                for span in spans_by_chapter.get(row.chapter_index, [])
                if _same_source(row, span) and _overlaps(row, span)
            ]
            if overlaps:
                expected_overlap += 1

            if span_id is None:
                continue
            mapped_span = spans_by_id.get(span_id)
            if mapped_span is None:
                dangling += 1
                continue
            if (
                str(mapped_span.scene_id) != scene_id
                or not _same_source(row, mapped_span)
                or not _overlaps(row, mapped_span)
            ):
                wrong_source += 1
                continue
            valid += 1

        total = len(chunks)
        return RagSceneMappingCoverageContract(
            novel_id=str(nid),
            content_mode=content_mode,
            total_chapter_chunks=total,
            scene_mapped_chunk_count=scene_mapped,
            span_mapped_chunk_count=span_mapped,
            expected_overlap_chunk_count=expected_overlap,
            valid_span_mapped_chunk_count=valid,
            dangling_mapping_count=dangling,
            wrong_source_mapping_count=wrong_source,
            overall_scene_mapping_rate=(
                round(scene_mapped / total, 4) if total else None
            ),
            overall_span_mapping_rate=(round(span_mapped / total, 4) if total else None),
            eligible_mapping_rate=(
                round(valid / expected_overlap, 4) if expected_overlap else None
            ),
        )


def _same_source(row, span) -> bool:
    return bool(
        row.source_id
        and span.source_draft_id
        and str(row.source_id) == str(span.source_draft_id)
        and row.source_content_hash
        and row.source_content_hash == span.source_content_hash
    )


def _overlaps(row, span) -> bool:
    if (
        row.start_offset is None
        or row.end_offset is None
        or span.start_offset is None
        or span.end_offset is None
    ):
        return False
    return int(row.start_offset) < int(span.end_offset) and int(row.end_offset) > int(
        span.start_offset
    )
