from __future__ import annotations

import uuid

import pytest

from modules.evidence.indexing.facade import get_scene_mapping_coverage
from modules.evidence.indexing.models import RagChunk
from modules.outline.models import Scene, SceneSpan


@pytest.mark.asyncio
async def test_scene_mapping_coverage_reconciles_expected_and_invalid_mappings(
    db_session,
    test_project_id: str,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    source_id = uuid.uuid4()
    source_hash = "a" * 64
    scene = Scene(novel_id=novel_id, scene_index=0, status="draft")
    db_session.add(scene)
    await db_session.flush()
    span = SceneSpan(
        novel_id=novel_id,
        scene_id=scene.id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=source_id,
        source_content_hash=source_hash,
        start_offset=0,
        end_offset=100,
        part_no=0,
        mapping_status="exact",
        status="draft",
    )
    db_session.add(span)
    await db_session.flush()

    def chunk(
        index: int,
        *,
        mapped_span_id: uuid.UUID | None,
        mapped_scene_id: uuid.UUID | None,
        chunk_source_id: uuid.UUID = source_id,
        chunk_hash: str = source_hash,
        start: int = 0,
        end: int = 20,
    ) -> RagChunk:
        return RagChunk(
            novel_id=novel_id,
            source_type="chapter_text",
            source_id=chunk_source_id,
            content_mode="canonical",
            source_content_hash=chunk_hash,
            chapter_index=1,
            chunk_index=index,
            start_offset=start,
            end_offset=end,
            char_count=end - start,
            text=f"chunk-{index}",
            scene_id=mapped_scene_id,
            scene_span_id=mapped_span_id,
            embedding_status="pending",
        )

    db_session.add_all(
        [
            chunk(0, mapped_span_id=span.id, mapped_scene_id=scene.id),
            chunk(1, mapped_span_id=None, mapped_scene_id=None, start=30, end=50),
            chunk(
                2,
                mapped_span_id=uuid.uuid4(),
                mapped_scene_id=scene.id,
                start=120,
                end=140,
            ),
            chunk(
                3,
                mapped_span_id=span.id,
                mapped_scene_id=scene.id,
                chunk_hash="b" * 64,
            ),
        ]
    )
    await db_session.flush()

    coverage = await get_scene_mapping_coverage(
        db_session,
        test_project_id,
        content_mode="canonical",
    )

    assert coverage.total_chapter_chunks == 4
    assert coverage.scene_mapped_chunk_count == 3
    assert coverage.span_mapped_chunk_count == 3
    assert coverage.expected_overlap_chunk_count == 2
    assert coverage.valid_span_mapped_chunk_count == 1
    assert coverage.dangling_mapping_count == 1
    assert coverage.wrong_source_mapping_count == 1
    assert coverage.overall_scene_mapping_rate == 0.75
    assert coverage.overall_span_mapping_rate == 0.75
    assert coverage.eligible_mapping_rate == 0.5
