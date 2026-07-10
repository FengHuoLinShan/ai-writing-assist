from __future__ import annotations

from dataclasses import replace

import pytest

from core.errors import ValidationError
from modules.writing.facade import (
    create_draft_only,
    create_published_draft_only,
    grep_manuscript,
    read_manuscript_range,
)
from modules.writing.schemas import WritingDraftUpdate
from modules.writing.services import WritingDraftService


@pytest.mark.asyncio
async def test_canonical_and_working_sources_are_distinct(
    db_session,
    test_project_id,
) -> None:
    published = await create_published_draft_only(
        db_session,
        test_project_id,
        1,
        "第一章",
        "旧正文\n第二段",
    )
    await create_draft_only(
        db_session,
        test_project_id,
        1,
        "第一章",
        "新工作稿\n第二段",
    )

    canonical, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "旧正文",
        content_mode="canonical",
    )
    working, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "新工作稿",
        content_mode="working",
    )

    assert canonical[0].source_ref.draft_id == published.id
    assert working[0].source_ref.draft_id != published.id


@pytest.mark.asyncio
async def test_canonical_missing_does_not_fall_back_to_working(
    db_session,
    test_project_id,
) -> None:
    await create_draft_only(
        db_session,
        test_project_id,
        5,
        content="只存在于工作稿的线索",
    )

    canonical, total, missing = await grep_manuscript(
        db_session,
        test_project_id,
        "工作稿的线索",
        content_mode="canonical",
        chapter_from=5,
        chapter_to=5,
    )

    assert canonical == []
    assert total == 0
    assert missing == [5]


@pytest.mark.asyncio
async def test_published_edit_is_copy_on_write_and_old_range_stays_readable(
    db_session,
    test_project_id,
) -> None:
    published = await create_published_draft_only(
        db_session,
        test_project_id,
        1,
        "第一章",
        "甲段\n乙段出现秘密\n丙段",
    )
    hits, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "秘密",
        content_mode="canonical",
    )

    updated = await WritingDraftService().update_draft(
        db_session,
        published.id or "",
        WritingDraftUpdate(content="工作稿已修改"),
        test_project_id,
    )
    read = await read_manuscript_range(
        db_session,
        test_project_id,
        hits[0].source_ref,
        before=1,
        after=1,
    )

    assert updated.id != published.id
    assert updated.status == "draft"
    assert "秘密" in read.text
    assert read.text[read.highlight_start : read.highlight_end] == "秘密"


@pytest.mark.asyncio
async def test_read_rejects_tampered_source_hash(
    db_session,
    test_project_id,
) -> None:
    await create_published_draft_only(
        db_session,
        test_project_id,
        1,
        content="可验证原文",
    )
    hits, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "原文",
    )
    tampered = replace(hits[0].source_ref, source_hash="0" * 64)

    with pytest.raises(ValidationError, match="source hash mismatch"):
        await read_manuscript_range(
            db_session,
            test_project_id,
            tampered,
        )


@pytest.mark.asyncio
async def test_literal_grep_reads_raw_source_across_derived_chunk_boundaries(
    db_session,
    test_project_id,
) -> None:
    content = "甲" * 1398 + "跨界命中" + "乙" * 300
    await create_published_draft_only(
        db_session,
        test_project_id,
        12,
        content=content,
    )

    hits, total, missing = await grep_manuscript(
        db_session,
        test_project_id,
        "甲甲跨界命中乙乙",
        content_mode="canonical",
    )

    assert total == 1
    assert missing == []
    assert hits[0].source_ref.start_offset == 1396
