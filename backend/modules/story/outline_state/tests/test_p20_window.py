"""BR-6 滚动规划窗口的确定性硬校验单测。"""

from __future__ import annotations

import uuid

import pytest

from modules.story.outline_state.p20_schemas import (
    OutlineLayerGenerateRequest,
    P20OutlineArcOutput,
    P20PlannedSceneOutput,
    P20PlotThreadOutput,
)
from modules.story.outline_state.p20_window import (
    ARC_WINDOW_MAX,
    SCENE_WINDOW_MAX,
    apply_planning_window,
    entry_limit,
    window_bounds,
    window_limit_violation,
    window_prompt_directive,
)


def _request(target: str, *, start: int | None, end: int | None = None, **extra):
    payload = {
        "novel_id": str(uuid.uuid4()),
        "context_confirmation_id": str(uuid.uuid4()),
        "target": target,
        "mode": "create",
        "instruction": "推进最近几章。",
        "rolling_window": start is not None,
    }
    if start is not None:
        payload["start_chapter"] = start
    if end is not None:
        payload["end_chapter"] = end
    return OutlineLayerGenerateRequest.model_validate({**payload, **extra})


def _arc(ref: str, *, start: int | None, end: int | None = None) -> dict:
    return {
        "proposal_ref": ref,
        "title": f"篇章{ref}",
        "start_chapter": start,
        "end_chapter": end,
        "basis": "承接总纲推进",
        "confidence": 0.8,
    }


def _scene(ref: str, *, start: int | None, end: int | None = None) -> dict:
    return {
        "proposal_ref": ref,
        "title": f"场景{ref}",
        "planned_start_chapter": start,
        "planned_end_chapter": end,
        "core_conflict_status": "not_applicable",
        "basis": "紧邻下一章的目标",
        "confidence": 0.8,
    }


def _thread(ref: str, *, start: int | None, payoff: int | None = None) -> dict:
    return {
        "proposal_ref": ref,
        "name": f"剧情线{ref}",
        "thread_type": "main",
        "start_chapter": start,
        "planned_payoff_chapter": payoff,
        "basis": "长期推进",
        "confidence": 0.8,
    }


def test_window_bounds_use_per_layer_defaults() -> None:
    assert window_bounds("outline_arc", 4) == (4, 6)
    assert window_bounds("plot_thread", 4) == (4, 6)
    assert window_bounds("planned_scene", 4) == (4, 4)
    assert window_bounds("outline_arc", None) is None


def test_window_limit_violation_caps_arc_five_and_scene_two() -> None:
    assert ARC_WINDOW_MAX == 5
    assert SCENE_WINDOW_MAX == 2
    assert window_limit_violation("outline_arc", 1, 5) is None
    assert window_limit_violation("outline_arc", 1, 6) is not None
    assert window_limit_violation("planned_scene", 5, 6) is None
    assert window_limit_violation("planned_scene", 5, 7) is not None
    assert entry_limit("planned_scene", 5, 6) == 4


def test_prompt_directive_names_window_and_disappears_without_it() -> None:
    windowed = window_prompt_directive(_request("outline_arc", start=4, end=6))
    assert "第 4 至 6 章" in windowed
    assert "已写成正文" in windowed
    assert window_prompt_directive(_request("outline_arc", start=None)) == ""


def test_entries_outside_window_are_dropped_with_explanation() -> None:
    request = _request("outline_arc", start=4, end=6)
    output = P20OutlineArcOutput(
        result="proposed",
        arcs=[
            _arc("A1", start=4, end=5),
            _arc("A2", start=3, end=6),
            _arc("A3", start=7, end=9),
        ],
    )
    filtered, report = apply_planning_window(request, output)

    assert [arc.proposal_ref for arc in filtered.arcs] == ["A1"]
    assert report["applied"] is True
    assert report["window"] == {"start": 4, "end": 6}
    reasons = {item["proposal_ref"]: item["reason"] for item in report["dropped"]}
    assert reasons == {"A2": "chapter_outside_window", "A3": "chapter_outside_window"}
    assert all("第 4 至 6 章" in item["detail"] for item in report["dropped"])


def test_create_mode_entries_pointing_at_written_chapters_are_dropped() -> None:
    request = _request("outline_arc", start=2, end=4)
    output = P20OutlineArcOutput(
        result="proposed",
        arcs=[_arc("A1", start=2, end=3), _arc("A2", start=4, end=4)],
    )
    filtered, report = apply_planning_window(
        request,
        output,
        written_chapters=frozenset({1, 2, 3}),
    )

    assert [arc.proposal_ref for arc in filtered.arcs] == ["A2"]
    assert report["dropped"][0]["reason"] == "chapter_points_to_written"
    assert report["dropped"][0]["chapters"] == [2, 3]


def test_revise_mode_may_keep_existing_written_coverage() -> None:
    request = _request(
        "outline_arc",
        start=5,
        end=7,
        mode="revise",
        selected_arc_ids=[str(uuid.uuid4())],
    )
    output = P20OutlineArcOutput(
        result="proposed",
        arcs=[{**_arc("A1", start=4, end=7), "target_arc_ref": "A1"}],
    )
    filtered, report = apply_planning_window(
        request,
        output,
        written_chapters=frozenset({4, 5}),
    )

    assert [arc.proposal_ref for arc in filtered.arcs] == ["A1"]
    assert "dropped" not in report


def test_entry_limit_keeps_head_and_reports_tail() -> None:
    request = _request("outline_arc", start=4, end=6)
    output = P20OutlineArcOutput(
        result="proposed",
        arcs=[
            _arc("A1", start=4, end=6),
            _arc("A2", start=4, end=6),
            _arc("A3", start=4, end=6),
            _arc("A4", start=4, end=6),
        ],
    )
    filtered, report = apply_planning_window(request, output)

    assert [arc.proposal_ref for arc in filtered.arcs] == ["A1", "A2", "A3"]
    overflow = [item for item in report["dropped"]]
    assert len(overflow) == 1
    assert overflow[0]["reason"] == "entry_limit_exceeded"
    assert overflow[0]["proposal_ref"] == "A4"


def test_scene_entry_limit_scales_with_window_width() -> None:
    request = _request("planned_scene", start=4, end=5)
    output = P20PlannedSceneOutput(
        result="proposed",
        scenes=[_scene(f"S{index}", start=4, end=5) for index in range(5)],
    )
    filtered, report = apply_planning_window(request, output)

    assert len(filtered.scenes) == 4
    assert report["entry_limit"] == 4
    assert len(report["dropped"]) == 1


def test_thread_payoff_may_extend_beyond_window() -> None:
    request = _request("plot_thread", start=4, end=6)
    output = P20PlotThreadOutput(
        result="proposed",
        threads=[
            _thread("P1", start=4, payoff=20),
            _thread("P2", start=2),
        ],
    )
    filtered, report = apply_planning_window(
        request,
        output,
        written_chapters=frozenset({1, 2, 3}),
    )

    assert [thread.proposal_ref for thread in filtered.threads] == ["P1"]
    assert report["dropped"][0]["reason"] == "chapter_outside_window"


def test_requests_without_window_are_untouched() -> None:
    request = _request("outline_arc", start=None)
    output = P20OutlineArcOutput(
        result="proposed",
        arcs=[_arc("A1", start=1, end=40), _arc("A2", start=41, end=80)],
    )
    filtered, report = apply_planning_window(
        request,
        output,
        written_chapters=frozenset({1, 2, 3}),
    )

    assert filtered is output
    assert report == {"policy": "p20_rolling_window_v1", "applied": False}


@pytest.mark.parametrize("target", ["outline_arc", "planned_scene"])
@pytest.mark.parametrize("mode", ["create", "revise"])
def test_new_entry_cannot_cover_a_written_chapter_inside_its_range(target, mode):
    selection = (
        {
            "selected_arc_ids" if target == "outline_arc" else "selected_scene_ids": [
                str(uuid.uuid4())
            ]
        }
        if mode == "revise"
        else {}
    )
    request = _request(target, start=6, end=8, mode=mode, **selection)
    if target == "outline_arc":
        output = P20OutlineArcOutput(result="proposed", arcs=[_arc("A1", start=6, end=8)])
        field = "arcs"
    else:
        output = P20PlannedSceneOutput(
            result="proposed", scenes=[_scene("S1", start=6, end=8)]
        )
        field = "scenes"
    filtered, report = apply_planning_window(request, output, written_chapters={7})
    assert not getattr(filtered, field)
    assert report["dropped"][0]["reason"] == "chapter_points_to_written"
    assert report["dropped"][0]["chapters"] == [7]


@pytest.mark.asyncio
async def test_window_validation_runs_in_task_handler_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """generate_layer_for_task 只在 rolling_window 请求上调用窗口校验。"""
    from modules.story.outline_state.ai_workflow_service import OutlineAIWorkflowService

    calls: list[object] = []

    async def fake_list_effective(_db, _novel_id):
        calls.append("written")
        return [1, 2, 3]

    monkeypatch.setattr(
        "modules.story.outline_state.ai_workflow_service.list_effective_chapter_indices",
        fake_list_effective,
    )
    request = _request("outline_arc", start=4, end=6)
    output = P20OutlineArcOutput(result="proposed", arcs=[_arc("A1", start=2, end=8)])
    filtered, report = await OutlineAIWorkflowService._apply_rolling_window(
        None, request, output
    )

    assert calls == ["written"]
    assert [arc.proposal_ref for arc in filtered.arcs] == []
    assert report["dropped"][0]["reason"] == "chapter_outside_window"

    unwindowed = _request("outline_arc", start=None)
    same, report_unwindowed = await OutlineAIWorkflowService._apply_rolling_window(
        None, unwindowed, output
    )
    assert same is output
    assert report_unwindowed is None
