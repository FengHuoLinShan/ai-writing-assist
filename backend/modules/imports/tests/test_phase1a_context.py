from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from modules.imports.phase1a_context import (
    PHASE1A_CONTEXT_CONTRACT_VERSION,
    Phase1aContextBuilder,
    apply_frozen_phase1a_context,
)
from modules.imports.scene_planning import build_scene_import_plan
from modules.imports.scene_slicing import _window_payload
from modules.imports.workflow import DeepImportWorkflow

NOVEL_ID = "11111111-1111-1111-1111-111111111111"


def _outline() -> SimpleNamespace:
    return SimpleNamespace(
        novel_id=NOVEL_ID,
        scenes=[
            {
                "id": "scene-1",
                "scene_index": 1,
                "chapter_indices": [2],
                "title": "Existing scene",
                "goal": "Known goal",
                "related_character_ids": ["char-05", "char-04"],
                "related_entity_ids": ["object-15", "object-14"],
            }
        ],
        arcs=[
            {
                "id": "arc-1",
                "title": "Current arc",
                "start_chapter": 1,
                "end_chapter": 10,
                "related_character_ids": [
                    "char-03",
                    "char-02",
                    "char-01",
                    "char-00",
                ],
                "related_entity_ids": [
                    *(f"object-{index:02d}" for index in range(13, -1, -1)),
                ],
            }
        ],
        plot_threads=[
            {
                "id": "thread-1",
                "name": "Main thread",
                "summary": "The current story movement",
                "current_stage": "rising",
            }
        ],
        warnings=[],
    )


def _entity_terms() -> list[dict]:
    return [
        *(
            {
                "id": f"char-{index:02d}",
                "name": f"character_name_{index:02d}",
                "entity_type": "character",
                "terms": [f"character_name_{index:02d}"],
            }
            for index in range(8)
        ),
        *(
            {
                "id": f"object-{index:02d}",
                "name": f"object_name_{index:02d}",
                "entity_type": "item",
                "terms": [f"object_name_{index:02d}"],
            }
            for index in range(18)
        ),
    ]


def _plan():
    return build_scene_import_plan(
        [
            {
                "chapter_index": 2,
                "title": "Chapter two",
                "content": (
                    "character_name_07 meets object_name_17. "
                    "character_name_06 takes object_name_16."
                ),
            }
        ],
        start_chapter=2,
        end_chapter=2,
    )


async def test_phase1a_context_freezes_bounded_ranked_author_safe_bundle() -> None:
    outline_loader = mock.AsyncMock(return_value=_outline())
    terms_loader = mock.AsyncMock(return_value=_entity_terms())

    async def _world_loader(_db, novel_id, **kwargs):
        assert novel_id == NOVEL_ID
        assert kwargs["reveal_mode"] == "author_safe"
        assert kwargs["include_review"] is False
        return SimpleNamespace(
            novel_id=NOVEL_ID,
            entities=[
                SimpleNamespace(
                    entity_id=item_id,
                    entity_type="character" if item_id.startswith("char-") else "item",
                    name=item_id,
                    summary=f"summary:{item_id}",
                    public_info=f"public:{item_id}",
                    importance_level="normal",
                    status="canonical",
                )
                for item_id in reversed(kwargs["entity_ids"])
            ],
        )

    async def _character_loader(_db, novel_id, **kwargs):
        assert novel_id == NOVEL_ID
        assert kwargs["reveal_mode"] == "author_safe"
        return SimpleNamespace(
            characters=[
                SimpleNamespace(
                    character_id=item_id,
                    name=item_id,
                    role="lead",
                    personality=None,
                    desire=None,
                    fear=None,
                    weakness=None,
                    current_goal=f"goal:{item_id}",
                    current_state=None,
                    current_emotion=None,
                    stance=None,
                    voice_style=None,
                    relationship_summary=None,
                )
                for item_id in reversed(kwargs["character_ids"])
            ]
        )

    builder = Phase1aContextBuilder(
        outline_loader=outline_loader,
        entity_terms_loader=terms_loader,
        world_context_loader=mock.AsyncMock(side_effect=_world_loader),
        character_context_loader=mock.AsyncMock(side_effect=_character_loader),
    )
    previous_text = "前" * 2_500
    frozen = await builder.compile(
        object(),
        novel_id=NOVEL_ID,
        plan=_plan(),
        boundary_chapters=[
            {"chapter_index": 1, "title": "Chapter one", "content": previous_text}
        ],
    )

    window = frozen.windows[0]
    assert window.left_boundary_context == previous_text[-2_000:]
    assert [item["id"] for item in window.reference_context["characters"]] == [
        "char-07",
        "char-06",
        "char-05",
        "char-04",
        "char-03",
        "char-02",
    ]
    assert [item["id"] for item in window.reference_context["world_objects"]] == [
        *(f"object-{index:02d}" for index in range(17, 1, -1)),
    ]
    trace = window.reference_context["selection_trace"]
    assert trace["included"]["characters"][0]["reason"] == "text_mention"
    assert trace["included"]["characters"][2]["reason"] == "scene_relation"
    assert [item["id"] for item in trace["omitted"]["characters"]] == [
        "char-01",
        "char-00",
    ]
    assert [item["id"] for item in trace["omitted"]["world_objects"]] == [
        "object-01",
        "object-00",
    ]
    assert frozen.phase1a_context["contract_version"] == (
        PHASE1A_CONTEXT_CONTRACT_VERSION
    )
    assert len(frozen.phase1a_context["fingerprint"]) == 64
    assert (
        frozen.quality_stats["phase1a_context_fingerprint"]
        == (frozen.phase1a_context["fingerprint"])
    )

    restored = apply_frozen_phase1a_context(_plan(), frozen.phase1a_context)
    assert restored.windows[0].reference_context == window.reference_context
    assert restored.windows[0].left_boundary_context == window.left_boundary_context
    provider_payload = _window_payload(
        restored.windows[0],
        restored.chapters,
        max_tokens=13_000,
    )
    assert provider_payload["left_boundary_context"] == window.left_boundary_context
    assert provider_payload["reference_context"] == window.reference_context


async def test_phase1a_context_does_not_scan_unrelated_canonical_assets() -> None:
    outline = SimpleNamespace(
        novel_id=NOVEL_ID,
        scenes=[],
        arcs=[],
        plot_threads=[],
        warnings=[],
    )
    builder = Phase1aContextBuilder(
        outline_loader=mock.AsyncMock(return_value=outline),
        entity_terms_loader=mock.AsyncMock(return_value=_entity_terms()),
        world_context_loader=mock.AsyncMock(
            side_effect=AssertionError("unrelated entities must not be loaded")
        ),
        character_context_loader=mock.AsyncMock(
            side_effect=AssertionError("unrelated characters must not be loaded")
        ),
    )
    plan = build_scene_import_plan(
        [{"chapter_index": 1, "title": "One", "content": "No known assets."}],
        start_chapter=1,
        end_chapter=1,
    )

    frozen = await builder.compile(object(), novel_id=NOVEL_ID, plan=plan)

    reference = frozen.windows[0].reference_context
    assert reference["characters"] == []
    assert reference["world_objects"] == []
    assert reference["selection_trace"]["included"] == {
        "characters": [],
        "world_objects": [],
    }


async def test_phase1a_context_rejects_cross_novel_outline_bundle() -> None:
    outline = _outline()
    outline.novel_id = "22222222-2222-2222-2222-222222222222"
    builder = Phase1aContextBuilder(
        outline_loader=mock.AsyncMock(return_value=outline),
        entity_terms_loader=mock.AsyncMock(return_value=[]),
    )

    with pytest.raises(ValueError, match="outline context novel_id mismatch"):
        await builder.compile(object(), novel_id=NOVEL_ID, plan=_plan())


async def test_regular_deep_import_freezes_phase1a_context_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chapters = [
        {"chapter_index": 1, "title": "One", "content": "Left boundary"},
        {"chapter_index": 2, "title": "Two", "content": "Owned text"},
    ]
    load = mock.AsyncMock(return_value=chapters)
    monkeypatch.setattr("modules.imports.workflow.load_chapter_range", load)
    context_builder = SimpleNamespace(
        compile=mock.AsyncMock(side_effect=lambda _db, **kwargs: kwargs["plan"])
    )
    workflow = DeepImportWorkflow(phase1a_context_builder=context_builder)
    workflow._agent_project_settings = {}  # noqa: SLF001

    plan = await workflow._run_phase0_plan(  # noqa: SLF001
        object(),
        NOVEL_ID,
        2,
        2,
    )

    load.assert_awaited_once_with(
        mock.ANY,
        NOVEL_ID,
        1,
        2,
        include_missing=False,
    )
    context_builder.compile.assert_awaited_once()
    assert [item["chapter_index"] for item in plan.chapters] == [2]
