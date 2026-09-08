from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from core.errors import ValidationError
from modules.writing.facade import (
    create_draft_only,
    create_published_draft_only,
    grep_manuscript,
    list_manuscript_sources,
    read_manuscript_range,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate
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
    retained = await create_published_draft_only(
        db_session,
        test_project_id,
        2,
        "第二章",
        "仍然有效的已发布正文",
    )
    await create_draft_only(db_session, test_project_id, 2, "第二章", "")

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
    all_canonical = await list_manuscript_sources(
        db_session,
        test_project_id,
        None,
        content_mode="canonical",
    )
    assert {item.id for item in all_canonical} == {published.id, retained.id}


@pytest.mark.asyncio
async def test_candidate_is_excluded_until_copy_on_adopt_makes_it_latest(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    async def _accept_frozen_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        _accept_frozen_candidate,
    )
    repo = WritingDraftRepository()
    await create_published_draft_only(
        db_session,
        test_project_id,
        2,
        "第二章",
        "已发布内容",
    )
    candidate = await repo.create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=2,
            title="AI 建议",
            content="待采用的关键线索",
            provenance_json={"source": "writing_generate", "model": "test"},
        ),
        status="candidate",
    )
    newer_working = await create_draft_only(
        db_session,
        test_project_id,
        2,
        "人工工作稿",
        "候选之后又保存的工作内容",
    )

    before, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "待采用的关键线索",
        content_mode="working",
    )
    assert before == []

    adopted = await WritingDraftService().adopt_candidate_to_working(
        db_session,
        str(candidate.id),
        test_project_id,
        adopted_by="test-author",
    )

    assert adopted.id != str(candidate.id)
    assert adopted.version_number > newer_working.version_number
    assert adopted.status == "draft"
    assert adopted.display_state == "active"
    assert adopted.source == "ai_generated"
    assert adopted.provenance_json["adopted_from_candidate_id"] == str(candidate.id)
    assert adopted.provenance_json["adopted_by"] == "test-author"
    assert adopted.provenance_json["model"] == "test"

    archived_candidate = await repo.get(db_session, candidate.id)
    assert archived_candidate is not None
    assert archived_candidate.status == "deprecated"
    assert archived_candidate.provenance_json["adoption_result_draft_id"] == adopted.id

    after, _, _ = await grep_manuscript(
        db_session,
        test_project_id,
        "待采用的关键线索",
        content_mode="working",
    )
    assert after[0].source_ref.draft_id == adopted.id


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


@pytest.mark.asyncio
async def test_literal_grep_can_group_occurrences_by_chapter(
    db_session,
    test_project_id,
) -> None:
    await create_published_draft_only(
        db_session,
        test_project_id,
        1,
        content="克莱恩醒来。克莱恩出门。",
    )
    await create_published_draft_only(
        db_session,
        test_project_id,
        2,
        content="第二章再次提到克莱恩。",
    )

    hits, total, missing = await grep_manuscript(
        db_session,
        test_project_id,
        "克莱恩",
        content_mode="canonical",
        group_by_chapter=True,
        limit=100,
    )

    assert total == 2
    assert missing == []
    assert [hit.source_ref.chapter_index for hit in hits] == [1, 2]
    assert [hit.match_count for hit in hits] == [2, 1]
    assert [len(hit.source_refs) for hit in hits] == [2, 1]
    assert [ref.start_offset for ref in hits[0].source_refs] == [0, 6]


@pytest.mark.asyncio
async def test_frozen_multi_term_scan_resumes_every_chapter_and_unindexed_occurrence(
    db_session, test_project_id
):
    from modules.writing.facade import (
        get_manuscript_source_manifest,
        scan_manuscript_terms,
    )

    for chapter in range(1, 5):
        await create_published_draft_only(
            db_session,
            test_project_id,
            chapter,
            content="甲" * 1400 + "未入库地点" + "乙" * 2400 + "旧称" + "丙" * 1400,
        )
    descriptors = await get_manuscript_source_manifest(db_session, test_project_id)
    manifest = {row["draft_id"]: row["source_hash"] for row in descriptors}
    cursor, hits, chapters = None, [], []
    for _ in range(20):
        batch = await scan_manuscript_terms(
            db_session,
            test_project_id,
            ["未入库地点", "旧称"],
            source_manifest=manifest,
            cursor=cursor,
            chapters_per_batch=1,
            limit=1,
            max_chars=2000,
        )
        hits.extend(batch.hits)
        chapters.extend(batch.scanned_chapters)
        cursor = batch.cursor
        if cursor is None:
            break
    assert cursor is None
    assert len(hits) == 8
    assert chapters == [1, 2, 3, 4]
    assert sum(hit.match_count for hit in hits) == 8
    assert (
        len({(hit.source_ref.draft_id, hit.source_ref.start_offset) for hit in hits}) == 8
    )


@pytest.mark.asyncio
async def test_frozen_scan_rejects_other_novel_and_changed_source(
    db_session, test_project_id
):
    from modules.writing.facade import (
        get_manuscript_source_manifest,
        scan_manuscript_terms,
    )
    from modules.writing.models import WritingDraft

    draft = await create_published_draft_only(
        db_session, test_project_id, 1, content="目标原文"
    )
    descriptors = await get_manuscript_source_manifest(db_session, test_project_id)
    manifest = {row["draft_id"]: row["source_hash"] for row in descriptors}
    with pytest.raises(ValidationError, match="stale or outside"):
        await scan_manuscript_terms(
            db_session, str(uuid.uuid4()), ["目标"], source_manifest=manifest
        )
    row = await db_session.get(WritingDraft, uuid.UUID(draft.id))
    row.content = "目标已改"
    await db_session.flush()
    with pytest.raises(ValidationError, match="changed while scanning|stale or outside"):
        await scan_manuscript_terms(
            db_session, test_project_id, ["目标"], source_manifest=manifest
        )


@pytest.mark.asyncio
async def test_scan_ranges_and_cutoff_do_not_expand_author_selected_text(
    db_session, test_project_id
):
    from dataclasses import asdict

    from modules.writing.facade import (
        build_manuscript_range_ref,
        get_manuscript_source_manifest,
        scan_manuscript_terms,
    )

    draft = await create_published_draft_only(
        db_session, test_project_id, 1, content="隐藏前史。目标在城北。目标的未来秘密。"
    )
    selected = await build_manuscript_range_ref(
        db_session,
        test_project_id,
        draft_id=draft.id,
        start_offset=5,
        end_offset=11,
        content_mode="canonical",
    )
    descriptors = await get_manuscript_source_manifest(db_session, test_project_id)
    manifest = {row["draft_id"]: row["source_hash"] for row in descriptors}
    batch = await scan_manuscript_terms(
        db_session,
        test_project_id,
        ["目标"],
        source_manifest=manifest,
        allowed_ranges=[asdict(selected)],
        visible_end_offsets={1: 11},
    )
    assert len(batch.hits) == 1
    ref = batch.hits[0].source_ref
    assert ref.start_offset >= 5 and ref.end_offset <= 11
    assert batch.hits[0].match_count == 1
