from __future__ import annotations

import pytest

from modules.imports.entity_extraction.scene_entity_text import get_scenes
from modules.imports.workflow import DeepImportWorkflow


@pytest.mark.asyncio
async def test_phase2_scene_loader_keeps_valley_and_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    expected = [
        {"id": "valley", "narrative_tag": "valley"},
        {"id": "transition", "narrative_tag": "transition"},
    ]

    async def fake_get_scenes(_db, novel_id, **kwargs):
        captured["novel_id"] = novel_id
        captured["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(
        "modules.outline.facade.get_scenes_by_novel",
        fake_get_scenes,
    )

    scenes = await get_scenes(object(), "novel-1")  # type: ignore[arg-type]

    assert scenes == expected
    assert captured == {
        "novel_id": "novel-1",
        "kwargs": {"status_filter": ["draft", "canonical"]},
    }


@pytest.mark.asyncio
async def test_phase2_coverage_counts_valley_and_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_get_scenes(_db, novel_id, **kwargs):
        captured["novel_id"] = novel_id
        captured["kwargs"] = kwargs
        return [
            {
                "id": "valley",
                "narrative_tag": "valley",
                "chapter_ids": ["1"],
            },
            {
                "id": "transition",
                "narrative_tag": "transition",
                "chapter_ids": ["2"],
            },
        ]

    monkeypatch.setattr(
        "modules.outline.facade.get_scenes_by_novel",
        fake_get_scenes,
    )

    coverage = await DeepImportWorkflow()._scene_chapter_coverage(
        object(),  # type: ignore[arg-type]
        "novel-1",
        1,
        2,
    )

    assert coverage["coverage_complete"] is True
    assert coverage["covered_chapters"] == [1, 2]
    assert captured["kwargs"] == {"status_filter": ["draft", "canonical"]}
