"""PlotStructurePersister 单元测试。"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from modules.outline.generation.models import (
    GeneratedArc,
    GeneratedScene,
    GeneratedThread,
)
from modules.outline.generation.parser import ParsedPlotStructure
from modules.outline.generation.persister import PlotStructurePersister
from modules.outline.schemas import (
    ForeshadowingPlanResponse,
    OutlineArcResponse,
    PlotThreadResponse,
    RevealPlanResponse,
    SceneResponse,
)


@pytest.fixture
def persister() -> PlotStructurePersister:
    thread_service = mock.AsyncMock()
    thread_service.count_by_novel_and_range.return_value = 0
    arc_service = mock.AsyncMock()
    arc_service.count_by_novel_and_range.return_value = 0
    scene_service = mock.AsyncMock()
    scene_service.get_ordered.return_value = []
    return PlotStructurePersister(
        thread_service=thread_service,
        arc_service=arc_service,
        scene_service=scene_service,
        foreshadowing_service=mock.AsyncMock(),
        reveal_service=mock.AsyncMock(),
    )


@pytest.fixture
def parsed() -> ParsedPlotStructure:
    return ParsedPlotStructure(
        threads=[GeneratedThread(name="主线", thread_type="main")],
        arcs=[GeneratedArc(title="第一卷", arc_index=1)],
        scenes=[GeneratedScene(title="开场", chapter_start=1, chapter_end=1)],
        foreshadowing_plans=[],
        reveal_plans=[],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )


@pytest.mark.asyncio
async def test_persist_calls_services_in_order(
    persister: PlotStructurePersister,
    parsed: ParsedPlotStructure,
) -> None:
    """persister 按正确顺序调用各 service.create。"""
    persister._thread_service.create.return_value = PlotThreadResponse(
        id="t1",
        novel_id="n1",
        name="主线",
        thread_type="main",
    )
    persister._arc_service.create.return_value = OutlineArcResponse(
        id="a1",
        novel_id="n1",
        title="第一卷",
    )
    persister._scene_service.create.return_value = SceneResponse(
        id="s1",
        novel_id="n1",
        scene_index=0,
        title="开场",
    )
    persister._thread_service.create_batch.return_value = [
        persister._thread_service.create.return_value
    ]
    persister._arc_service.create_batch.return_value = [
        persister._arc_service.create.return_value
    ]
    persister._scene_service.batch_create_models_from_dicts.return_value = [
        persister._scene_service.create.return_value
    ]
    provenance = {
        "source": "ai_generated",
        "adopted_at": "2026-07-10T00:00:00+00:00",
        "needs_review": False,
    }

    result = await persister.persist(
        db=mock.AsyncMock(),
        novel_id=mock.Mock(hex="n1", __str__=lambda _: "n1"),
        start_chapter=1,
        end_chapter=3,
        parsed=parsed,
        entity_name_to_id={},
        character_name_to_id={},
        provenance_meta_override=provenance,
    )

    assert result.total_threads == 1
    assert result.total_arcs == 1
    assert result.total_scenes == 1
    persister._thread_service.create_batch.assert_awaited_once()
    persister._arc_service.create_batch.assert_awaited_once()
    persister._scene_service.batch_create_models_from_dicts.assert_awaited_once()
    thread_payload = persister._thread_service.create_batch.await_args.args[2][0]
    arc_payload = persister._arc_service.create_batch.await_args.args[2][0]
    scene_payload = (
        persister._scene_service.batch_create_models_from_dicts.await_args.args[2][0]
    )
    assert thread_payload.provenance_meta == provenance
    assert arc_payload.provenance_meta == provenance
    assert scene_payload["source"] == "ai_generated"
    assert scene_payload["structure_meta"] == provenance


@pytest.mark.asyncio
async def test_strict_persist_rejects_incomplete_batch(
    persister: PlotStructurePersister,
    parsed: ParsedPlotStructure,
) -> None:
    persister._thread_service.create_batch.return_value = []

    with pytest.raises(RuntimeError, match="thread batch persistence was incomplete"):
        await persister.persist(
            db=mock.AsyncMock(),
            novel_id=mock.Mock(hex="n1", __str__=lambda _: "n1"),
            start_chapter=1,
            end_chapter=3,
            parsed=parsed,
            entity_name_to_id={},
            character_name_to_id={},
            strict=True,
        )


@pytest.mark.asyncio
async def test_deep_import_persist_keeps_item_review_evidence(
    persister: PlotStructurePersister,
) -> None:
    parsed = ParsedPlotStructure(
        threads=[
            GeneratedThread(
                name="需复核主线",
                thread_type="main",
                confidence=0.45,
                needs_review=True,
                review_reason="low_confidence",
                supporting_scene_ids=["scene-1"],
            )
        ],
        arcs=[],
        scenes=[],
        foreshadowing_plans=[],
        reveal_plans=[],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )
    persister._thread_service.create_batch.return_value = [
        PlotThreadResponse(
            id="t1",
            novel_id="n1",
            name="需复核主线",
            thread_type="main",
        )
    ]

    result = await persister.persist(
        db=mock.AsyncMock(),
        novel_id=mock.Mock(hex="n1", __str__=lambda _: "n1"),
        start_chapter=1,
        end_chapter=3,
        parsed=parsed,
        entity_name_to_id={},
        character_name_to_id={},
        workflow_id="wf-review",
    )

    payload = persister._thread_service.create_batch.await_args.args[2][0]
    assert payload.provenance_meta["source"] == "deep_import"
    assert payload.provenance_meta["workflow_id"] == "wf-review"
    assert payload.provenance_meta["needs_review"] is True
    assert payload.provenance_meta["confidence"] == 0.45
    assert payload.provenance_meta["review_reason"] == "low_confidence"
    assert payload.provenance_meta["supporting_scene_ids"] == ["scene-1"]
    assert result.threads[0]["needs_review"] is True


@pytest.mark.asyncio
async def test_persist_sanitizes_invalid_arc_index(
    persister: PlotStructurePersister,
) -> None:
    """LLM 输出 arc_index=0 时会被清洗为满足 schema ge=1。"""
    parsed = ParsedPlotStructure(
        threads=[],
        arcs=[GeneratedArc(title="第一卷", arc_index=0)],
        scenes=[],
        foreshadowing_plans=[],
        reveal_plans=[],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )
    persister._arc_service.create.return_value = OutlineArcResponse(
        id="a1",
        novel_id="n1",
        title="第一卷",
    )
    persister._arc_service.create_batch.return_value = [
        persister._arc_service.create.return_value
    ]

    await persister.persist(
        db=mock.AsyncMock(),
        novel_id=mock.Mock(hex="n1", __str__=lambda _: "n1"),
        start_chapter=1,
        end_chapter=3,
        parsed=parsed,
        entity_name_to_id={},
        character_name_to_id={},
    )

    _db, _novel_id, arc_payloads = persister._arc_service.create_batch.await_args.args
    arc_data = arc_payloads[0]
    assert arc_data.arc_index is None


@pytest.mark.asyncio
async def test_persist_creates_foreshadowing_and_reveal(
    persister: PlotStructurePersister,
) -> None:
    """persister 也写入 foreshadowing / reveal plan。"""
    from modules.outline.generation.models import ForeshadowingPlan, RevealPlan

    parsed = ParsedPlotStructure(
        threads=[],
        arcs=[],
        scenes=[],
        foreshadowing_plans=[ForeshadowingPlan(name="伏笔1")],
        reveal_plans=[RevealPlan(target_name="目标")],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )
    persister._foreshadowing_service.create.return_value = ForeshadowingPlanResponse(
        id="f1",
        novel_id="n1",
        name="伏笔1",
    )
    persister._reveal_service.create.return_value = RevealPlanResponse(
        id="r1",
        novel_id="n1",
        target_type="world_entity",
        target_id="target",
        secret_summary="秘密",
    )
    persister._foreshadowing_service.create_batch.return_value = [
        persister._foreshadowing_service.create.return_value
    ]
    persister._reveal_service.create_batch.return_value = [
        persister._reveal_service.create.return_value
    ]

    result = await persister.persist(
        db=mock.AsyncMock(),
        novel_id=mock.Mock(hex="n1", __str__=lambda _: "n1"),
        start_chapter=1,
        end_chapter=3,
        parsed=parsed,
        entity_name_to_id={"目标": str(uuid.uuid4())},
        character_name_to_id={},
    )

    persister._foreshadowing_service.create_batch.assert_awaited_once()
    persister._reveal_service.create_batch.assert_awaited_once()
    assert len(result.extra_sections["foreshadowing_plans"]) == 1
    assert len(result.extra_sections["reveal_plans"]) == 1


@pytest.mark.asyncio
async def test_persist_truncates_long_narrative_tag(
    persister: PlotStructurePersister,
) -> None:
    """LLM 输出的 narrative_tag 超长时截断至 32 字符，避免 DB 截断错误。"""
    parsed = ParsedPlotStructure(
        threads=[],
        arcs=[],
        scenes=[
            GeneratedScene(
                title="开场",
                chapter_start=1,
                chapter_end=1,
                narrative_tag="daily_life_character_introduction",
            ),
        ],
        foreshadowing_plans=[],
        reveal_plans=[],
        offscreen_progress=[],
        risks=[],
        questions_for_user=[],
    )
    persister._scene_service.create.return_value = SceneResponse(
        id="s1",
        novel_id="n1",
        scene_index=0,
        title="开场",
    )
    persister._scene_service.batch_create_models_from_dicts.return_value = [
        persister._scene_service.create.return_value
    ]

    await persister.persist(
        db=mock.AsyncMock(),
        novel_id=mock.Mock(hex="n1", __str__=lambda _: "n1"),
        start_chapter=1,
        end_chapter=3,
        parsed=parsed,
        entity_name_to_id={},
        character_name_to_id={},
    )

    _db, _novel_id, scene_payloads = (
        persister._scene_service.batch_create_models_from_dicts.await_args.args
    )
    assert scene_payloads[0]["narrative_tag"] == "daily_life_character_introductio"
