from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.imports import scene_entity_text
from modules.writing.contracts import WritingDraftContract


def _service() -> SimpleNamespace:
    return SimpleNamespace(
        _small_sample_chapter_indices=scene_entity_text.small_sample_chapter_indices,
        _trim_supplement_chapter_text=scene_entity_text.trim_supplement_chapter_text,
        _scene_chunks_by_chapter=scene_entity_text.scene_chunks_by_chapter,
        _scene_chapter_ids=scene_entity_text.scene_chapter_ids,
        _select_scene_text=scene_entity_text.select_scene_text,
        _scene_context_header=scene_entity_text.scene_context_header,
    )


@pytest.mark.asyncio
async def test_load_small_sample_chapters_text_batches_draft_lookup(monkeypatch) -> None:
    calls: list[tuple[str, list[int]]] = []

    async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
        calls.append((novel_id, list(chapter_indices)))
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=2,
                content="第二章正文",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=1,
                content="第一章正文",
            ),
        ]

    async def get_latest_draft_for_chapter(*args, **kwargs):
        raise AssertionError("small sample loading should use one batched draft lookup")

    import modules.writing.facade as writing_facade

    monkeypatch.setattr(
        writing_facade,
        "list_latest_drafts_for_chapters",
        list_latest_drafts_for_chapters,
    )
    monkeypatch.setattr(
        writing_facade,
        "get_latest_draft_for_chapter",
        get_latest_draft_for_chapter,
    )

    text = await scene_entity_text.load_small_sample_chapters_text(
        _service(),
        object(),
        [
            {"novel_id": "novel-1", "chapter_ids": ["1", "2"]},
            {"novel_id": "novel-1", "chapter_ids": ["2"]},
        ],
    )

    assert calls == [("novel-1", [1, 2])]
    assert text.index("## 第1章") < text.index("## 第2章")
    assert "第一章正文" in text
    assert "第二章正文" in text


@pytest.mark.asyncio
async def test_load_scene_chapters_batches_draft_lookup(monkeypatch) -> None:
    calls: list[tuple[str, list[int]]] = []

    async def list_latest_drafts_for_chapters(db, novel_id, chapter_indices):
        calls.append((novel_id, list(chapter_indices)))
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=3,
                content="第三章第一段\n\n第三章第二段",
            ),
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=1,
                content="第一章正文",
            ),
        ]

    async def get_latest_draft_for_chapter(*args, **kwargs):
        raise AssertionError("scene chapter loading should use one batched draft lookup")

    import modules.writing.facade as writing_facade

    monkeypatch.setattr(
        writing_facade,
        "list_latest_drafts_for_chapters",
        list_latest_drafts_for_chapters,
    )
    monkeypatch.setattr(
        writing_facade,
        "get_latest_draft_for_chapter",
        get_latest_draft_for_chapter,
    )

    text = await scene_entity_text.load_scene_chapters(
        _service(),
        object(),
        {
            "novel_id": "novel-1",
            "scene_index": 7,
            "title": "跨章 Scene",
            "chapter_ids": ["1", "3"],
            "scene_chunks": [
                {"chapter_index": 3, "start_paragraph": 1, "end_paragraph": 1}
            ],
        },
    )

    assert calls == [("novel-1", [1, 3])]
    assert "## Scene 上下文" in text
    assert text.index("## 第1章") < text.index("## 第3章")
    assert "第一章正文" in text
    assert "第三章第二段" in text
    assert "第三章第一段" not in text
