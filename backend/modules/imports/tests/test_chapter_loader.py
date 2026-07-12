from __future__ import annotations

from unittest.mock import Mock

import pytest

from modules.imports.chapter_loader import build_chapters_text, load_chapter_range
from modules.imports.phase2_world_extraction import _load_chapters as load_phase2_chapters
from modules.imports.scene_segmentation import SceneSegmentationService
from modules.writing.contracts import WritingDraftContract


@pytest.mark.asyncio
async def test_load_chapter_range_batches_draft_lookup_and_skips_missing(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[int]]] = []

    async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
        del db
        calls.append((novel_id, list(chapter_indices)))
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=3,
                title="第三章",
                content="第三章正文",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="第一章正文",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=2,
                title="第二章",
                content="",
            ),
        ]

    monkeypatch.setattr(
        "modules.writing.facade.list_latest_drafts_for_chapters",
        list_latest_drafts_for_chapters,
    )

    chapters = await load_chapter_range(Mock(), "novel-1", 1, 3)

    assert calls == [("novel-1", [1, 2, 3])]
    assert [chapter["chapter_index"] for chapter in chapters] == [1, 3]
    assert [chapter["title"] for chapter in chapters] == ["第一章", "第三章"]


@pytest.mark.asyncio
async def test_load_chapter_range_include_missing_keeps_full_range(
    monkeypatch,
) -> None:
    async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
        del db, chapter_indices
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=2,
                title=None,
                content=None,
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=3,
                title="第三章",
                content="第三章正文",
            ),
        ]

    monkeypatch.setattr(
        "modules.writing.facade.list_latest_drafts_for_chapters",
        list_latest_drafts_for_chapters,
    )

    chapters = await load_chapter_range(
        Mock(),
        "novel-1",
        1,
        3,
        include_missing=True,
    )

    assert chapters == [
        {
            "chapter_index": 1,
            "title": "第1章",
            "content": "",
            "source_draft_id": None,
            "source_content_hash": "",
        },
        {
            "chapter_index": 2,
            "title": "第2章",
            "content": "",
            "source_draft_id": None,
            "source_content_hash": "",
        },
        {
            "chapter_index": 3,
            "title": "第三章",
            "content": "第三章正文",
            "source_draft_id": None,
            "source_content_hash": "",
        },
    ]


def test_build_chapters_text_uses_existing_prompt_format() -> None:
    assert (
        build_chapters_text(
            [
                {"chapter_index": 1, "title": "开端", "content": "第一段"},
                {"chapter_index": 2, "title": "", "content": ""},
            ]
        )
        == "## 第1章 开端\n\n第一段\n\n## 第2章 第2章\n\n"
    )


@pytest.mark.asyncio
async def test_scene_segmentation_load_chapters_wrapper_skips_missing(
    monkeypatch,
) -> None:
    async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
        del db, chapter_indices
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="第一章正文",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=2,
                title="第二章",
                content="",
            ),
        ]

    monkeypatch.setattr(
        "modules.writing.facade.list_latest_drafts_for_chapters",
        list_latest_drafts_for_chapters,
    )

    chapters = await SceneSegmentationService()._load_chapters(Mock(), "novel-1", 1, 3)

    assert chapters == [
        {
            "chapter_index": 1,
            "title": "第一章",
            "content": "第一章正文",
            "source_draft_id": None,
            "source_content_hash": "",
        }
    ]


@pytest.mark.asyncio
async def test_phase2_load_chapters_wrapper_keeps_missing_chapters(
    monkeypatch,
) -> None:
    async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
        del db, chapter_indices
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=2,
                title="第二章",
                content="第二章正文",
            )
        ]

    monkeypatch.setattr(
        "modules.writing.facade.list_latest_drafts_for_chapters",
        list_latest_drafts_for_chapters,
    )

    chapters = await load_phase2_chapters(
        Mock(),
        "novel-1",
        chapter_start=1,
        chapter_end=2,
    )

    assert chapters == [
        {
            "chapter_index": 1,
            "title": "第1章",
            "content": "",
            "source_draft_id": None,
            "source_content_hash": "",
        },
        {
            "chapter_index": 2,
            "title": "第二章",
            "content": "第二章正文",
            "source_draft_id": None,
            "source_content_hash": "",
        },
    ]
