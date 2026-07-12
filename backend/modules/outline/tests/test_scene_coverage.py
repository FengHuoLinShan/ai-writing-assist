from __future__ import annotations

import uuid

import pytest

from modules.outline.facade import get_scene_span_coverage
from modules.outline.models import Scene, SceneSpan


@pytest.mark.asyncio
async def test_scene_span_coverage_isolated_by_content_mode(
    db_session,
    test_project_id: str,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    scenes = [
        Scene(novel_id=novel_id, scene_index=index, status="draft") for index in range(3)
    ]
    db_session.add_all(scenes)
    await db_session.flush()
    source_id = uuid.uuid4()
    source_hash = "a" * 64
    db_session.add_all(
        [
            SceneSpan(
                novel_id=novel_id,
                scene_id=scenes[0].id,
                chapter_index=1,
                content_mode="canonical",
                source_draft_id=source_id,
                source_content_hash=source_hash,
                start_offset=0,
                end_offset=20,
                part_no=0,
                mapping_status="exact",
                status="draft",
            ),
            SceneSpan(
                novel_id=novel_id,
                scene_id=scenes[0].id,
                chapter_index=2,
                content_mode="canonical",
                source_draft_id=source_id,
                source_content_hash=source_hash,
                start_offset=5,
                end_offset=25,
                part_no=1,
                mapping_status="reanchored",
                status="draft",
            ),
            SceneSpan(
                novel_id=novel_id,
                scene_id=scenes[1].id,
                chapter_index=2,
                content_mode="canonical",
                part_no=0,
                mapping_status="chapter_only",
                status="canonical",
            ),
            SceneSpan(
                novel_id=novel_id,
                scene_id=scenes[1].id,
                chapter_index=3,
                content_mode="canonical",
                part_no=1,
                mapping_status="unresolved",
                status="draft",
            ),
            SceneSpan(
                novel_id=novel_id,
                scene_id=scenes[2].id,
                chapter_index=1,
                content_mode="working",
                source_draft_id=uuid.uuid4(),
                source_content_hash="b" * 64,
                start_offset=0,
                end_offset=10,
                part_no=0,
                mapping_status="exact",
                status="draft",
            ),
        ]
    )
    await db_session.flush()

    coverage = await get_scene_span_coverage(
        db_session,
        test_project_id,
        content_mode="canonical",
    )

    assert coverage.scene_count == 3
    assert coverage.scene_with_span_count == 2
    assert coverage.scene_without_span_count == 1
    assert coverage.total_span_count == 4
    assert coverage.exact_count == 1
    assert coverage.reanchored_count == 1
    assert coverage.chapter_only_count == 1
    assert coverage.unresolved_count == 1
    assert coverage.precise_span_count == 2
    assert coverage.imprecise_span_count == 2
    assert coverage.precise_span_rate == 0.5
    assert {span.mapping_status for span in coverage.precise_spans} == {
        "exact",
        "reanchored",
    }
