from __future__ import annotations

from typing import Any

import pytest

from modules.imports.llm_schemas import Phase2WorldExtractionOutput
from modules.imports.phase2_world_extraction import (
    _normalize_world_output,
    _phase2_window_max_tokens,
)
from modules.imports.scene_enrichment import Phase1bSceneEnricher
from modules.imports.scene_planning import SceneWindowPlan, build_scene_import_plan
from modules.imports.scene_slicing import (
    Phase1aSceneSlicer,
    SceneSliceCandidate,
)
from modules.imports.workflow_llm_adapters import (
    _Phase1aSceneSlicingLLM,
    _Phase1bSceneEnrichmentLLM,
    _Phase2WorldExtractionLLM,
)


def _chapters(count: int, *, chars_per_chapter: int) -> list[dict[str, Any]]:
    return [
        {
            "chapter_index": index,
            "title": f"第{index}章",
            "content": "正" * chars_per_chapter,
        }
        for index in range(1, count + 1)
    ]


def _chapters_from_char_counts(char_counts: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "chapter_index": index,
            "title": f"第{index}章",
            "content": "正" * char_count,
        }
        for index, char_count in enumerate(char_counts, start=1)
    ]


def test_phase0_plan_uses_char_budget_windows_and_token_budget() -> None:
    result = build_scene_import_plan(
        _chapters_from_char_counts(([3789] * 34) + ([3600] * 26)),
        start_chapter=1,
        end_chapter=60,
    )

    assert result.quality_stats["target_input_chars"] == 72_000
    assert result.quality_stats["max_chapters_per_window"] == 20
    assert result.quality_stats["selected_overlap"] == 2
    assert result.quality_stats["selected_window_chapter_counts"] == [19, 19, 20, 8]
    ranges = [
        (w.covered_start, w.covered_end, w.owned_start, w.owned_end)
        for w in result.windows
    ]
    assert ranges == [
        (1, 19, 1, 17),
        (18, 36, 18, 34),
        (35, 54, 35, 52),
        (53, 60, 53, 60),
    ]
    assert result.windows[0].max_tokens == 25_917
    assert result.windows[-1].max_tokens == 13_000
    assert result.quality_stats["max_tokens_per_input_char"] == 0.36
    assert result.quality_stats["min_max_tokens"] == 13_000


def test_phase0_plan_uses_project_deep_import_coefficient() -> None:
    result = build_scene_import_plan(
        _chapters(1, chars_per_chapter=10_000),
        start_chapter=1,
        end_chapter=1,
        project_settings={
            "deep_import": {
                "phase0": {
                    "max_tokens_per_input_char": 0.5,
                    "min_max_tokens": 1,
                    "max_max_tokens": 200_000,
                }
            }
        },
    )

    assert result.quality_stats["max_tokens_per_input_char"] == 0.5
    assert result.windows[0].max_tokens == 5000


def test_phase0_plan_caps_short_chapter_windows_at_twenty_chapters() -> None:
    result = build_scene_import_plan(
        _chapters(100, chars_per_chapter=100),
        start_chapter=1,
        end_chapter=100,
    )

    assert max(len(window.chapter_indices) for window in result.windows) == 20
    assert [
        (result.windows[0].covered_start, result.windows[0].covered_end),
        (result.windows[1].covered_start, result.windows[1].covered_end),
    ] == [(1, 20), (19, 38)]


def test_phase0_plan_shrinks_to_single_long_chapters() -> None:
    result = build_scene_import_plan(
        _chapters(3, chars_per_chapter=80_000),
        start_chapter=1,
        end_chapter=3,
    )

    assert [(w.covered_start, w.covered_end) for w in result.windows] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]
    assert all(len(window.chapter_indices) == 1 for window in result.windows)


def test_phase0_plan_clamps_window_max_tokens_upper_bound() -> None:
    result = build_scene_import_plan(
        _chapters(1, chars_per_chapter=100_000),
        start_chapter=1,
        end_chapter=1,
    )

    assert len(result.windows) == 1
    assert result.windows[0].max_tokens == 32_768


def test_phase2_world_token_budget_uses_higher_floor_and_cap() -> None:
    assert _phase2_window_max_tokens(26_000) == 24_576
    assert _phase2_window_max_tokens(70_000) == 25_200
    assert _phase2_window_max_tokens(100_000) == 32_768


def test_phase2_world_parser_filters_invalid_and_overlap_only_refs() -> None:
    output = Phase2WorldExtractionOutput.model_validate(
        {
            "objects": [
                {
                    "name": "克莱恩",
                    "entity_type": "character",
                    "summary": "主角身份。",
                    "supporting_scene_ids": ["s-owned"],
                },
                {
                    "name": "重叠区对象",
                    "entity_type": "item",
                    "summary": "只在 overlap 中出现。",
                    "supporting_scene_ids": ["s-overlap"],
                },
            ],
            "relations": [
                {
                    "source_name": "克莱恩",
                    "target_name": "值夜者",
                    "relation_type": "加入",
                    "description": "开始接触组织。",
                    "supporting_scene_ids": ["s-owned", "missing"],
                }
            ],
            "deltas": [
                {
                    "subject_name": "克莱恩",
                    "description": "缺少有效 Scene 支撑，应丢弃。",
                    "supporting_scene_ids": ["missing"],
                }
            ],
        }
    )

    normalized, invalid_refs, overlap_only, diagnostic = _normalize_world_output(
        output,
        scenes_by_id={
            "s-owned": {"id": "s-owned"},
            "s-overlap": {"id": "s-overlap"},
        },
        owned_scene_ids={"s-owned"},
    )

    assert [item.name for item in normalized.objects] == ["克莱恩"]
    assert len(normalized.relations) == 1
    assert normalized.relations[0].needs_review is True
    assert normalized.relations[0].supporting_scene_ids == ["s-owned"]
    assert normalized.deltas == []
    assert invalid_refs == 2
    assert overlap_only == 1
    assert diagnostic["total"] == 2


@pytest.mark.asyncio
async def test_phase1a_slicer_filters_to_owned_range_and_fallbacks_missing_chapters():
    window = SceneWindowPlan(
        window_index=1,
        window_id="B0001-1-5-owned-1-3",
        covered_start=1,
        covered_end=5,
        owned_start=1,
        owned_end=3,
        chapter_indices=[1, 2, 3, 4, 5],
        owned_chapter_indices=[1, 2, 3],
        input_chars=5000,
        max_tokens=13_000,
        batch_size=5,
        overlap=2,
    )
    plan = build_scene_import_plan(
        _chapters(5, chars_per_chapter=1000),
        start_chapter=1,
        end_chapter=5,
    )
    plan.windows = [window]

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "Owned",
                    "goal": "覆盖 owned range",
                    "core_conflict": "冲突",
                    "start_chapter": 1,
                    "end_chapter": 2,
                    "boundary_status": "complete",
                },
                {
                    "title": "Overlap-only",
                    "goal": "不应归属本窗口",
                    "core_conflict": "冲突",
                    "start_chapter": 4,
                    "end_chapter": 5,
                    "boundary_status": "complete",
                },
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    llm_candidates = [
        c for c in result.candidates if c.source_window_id == window.window_id
    ]
    assert [c.start_chapter for c in llm_candidates] == [1]
    assert {c.start_chapter for c in result.candidates} == {1, 3, 4, 5}
    assert result.quality_stats["fallback_count"] == 3


@pytest.mark.asyncio
async def test_phase1b_enrichment_retries_and_ignores_locked_fields() -> None:
    calls = 0
    scene = SceneSliceCandidate(
        candidate_id="phase1a-1",
        source_window_id="B0001",
        source_window_index=1,
        title="锁定标题",
        goal="锁定目标",
        core_conflict="锁定冲突",
        start_chapter=2,
        end_chapter=3,
        boundary_status="complete",
        source_chapter_indices=[2, 3],
    )

    async def llm(_payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "emotional_beat": "",
                "must_happen": "",
                "must_not_happen": "",
                "narrative_tag": "",
            }
        return {
            "title": "LLM 不应覆盖标题",
            "goal": "LLM 不应覆盖目标",
            "core_conflict": "LLM 不应覆盖冲突",
            "start_chapter": 99,
            "end_chapter": 100,
            "emotional_beat": "从困惑转向决断。",
            "must_happen": "必须保留关键行动。",
            "must_not_happen": "不得改写为胜利结局。",
            "narrative_tag": "turning_point",
            "confidence": 0.86,
            "needs_review": False,
            "review_reason": "",
    }

    result = await Phase1bSceneEnricher(llm, concurrency=20).run(
        scenes=[scene],
        chapters=_chapters(3, chars_per_chapter=100),
    )

    assert calls == 2
    candidate = result.candidates[0]
    assert candidate.title == "锁定标题"
    assert candidate.goal == "锁定目标"
    assert candidate.core_conflict == "锁定冲突"
    assert [chunk.chapter_index for chunk in candidate.scene_chunks] == [2, 3]
    assert candidate.narrative_tag == "turning_point"
    assert result.quality_stats["concurrency"] == 200
    assert result.quality_stats["max_retries"] == 1


def test_phase1a_and_phase1b_default_concurrency() -> None:
    async def llm(_payload):
        return {}

    assert Phase1aSceneSlicer(llm).concurrency == 50
    assert Phase1bSceneEnricher(llm).concurrency == 200


@pytest.mark.asyncio
async def test_high_quality_adapters_override_model_but_keep_deepseek_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []
    captured_kwargs = []

    class FakeProfile:
        provider_id = "deepseek"
        model = "deepseek-v4-flash"
        extra = {}

        def request_defaults(self):
            return {"model": self.model, "temperature": 0.3, "max_tokens": 8192}

    async def fake_call_structured(_client, request, schema, **_kwargs):
        captured.append(request)
        captured_kwargs.append(_kwargs)
        return schema.model_validate(
            {
                "scenes": [
                    {
                        "title": "切分",
                        "goal": "测试",
                        "core_conflict": "冲突",
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "boundary_status": "complete",
                    }
                ]
            }
            if schema.__name__ == "SceneSlicingOutput"
            else {
                "objects": [
                    {
                        "name": "克莱恩",
                        "entity_type": "character",
                        "summary": "主角。",
                        "supporting_scene_ids": ["scene-1"],
                    }
                ],
                "relations": [],
                "deltas": [],
                "uncertain_items": [],
            }
            if schema.__name__ == "Phase2WorldExtractionOutput"
            else {
                "emotional_beat": "稳定",
                "must_happen": "保留",
                "must_not_happen": "不偏离",
                "narrative_tag": "imported",
            }
        )

    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters.resolve_llm_profile",
        lambda _settings: FakeProfile(),
    )
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._llm_client_for_profile",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._call_structured",
        fake_call_structured,
    )

    await _Phase1aSceneSlicingLLM(high_quality=True)(
        {
            "chapters": [{"chapter_index": 1, "title": "第一章", "content": "正文"}],
            "window": {"owned_start": 1, "owned_end": 1},
            "max_tokens": 13_000,
        }
    )
    await _Phase1bSceneEnrichmentLLM(high_quality=True)(
        {
            "chapters": [{"chapter_index": 1, "title": "第一章", "content": "正文"}],
            "locked_scene": {
                "title": "锁定",
                "goal": "目标",
                "core_conflict": "冲突",
                "start_chapter": 1,
                "end_chapter": 1,
            },
            "max_tokens": 4096,
        }
    )
    await _Phase2WorldExtractionLLM(high_quality=True)(
        {
            "chapters": [{"chapter_index": 1, "title": "第一章", "content": "正文"}],
            "scenes": [
                {
                    "scene_id": "scene-1",
                    "title": "锁定 Scene",
                    "goal": "目标",
                    "core_conflict": "冲突",
                    "start_chapter": 1,
                    "end_chapter": 1,
                }
            ],
            "owned_scene_ids": ["scene-1"],
            "all_scene_ids": ["scene-1"],
            "window": {
                "covered_start": 1,
                "covered_end": 1,
                "owned_start": 1,
                "owned_end": 1,
            },
            "max_tokens": 24_576,
        }
    )

    assert [request.model for request in captured] == [
        "deepseek-v4-pro",
        "deepseek-v4-pro",
        "deepseek-v4-pro",
    ]
    assert all(request.extra["thinking"] == {"type": "enabled"} for request in captured)
    assert all(request.extra["reasoning_effort"] == "max" for request in captured)
    phase1a_prompt = captured[0].messages[1].content
    assert phase1a_prompt.startswith("## 第1章 第一章")
    assert "正文" in phase1a_prompt.split("【输入范围】")[0]
    for forbidden in ["10-25", "通常应输出", "少于", "Scene 数量"]:
        assert forbidden not in phase1a_prompt
    assert captured[0].max_tokens == 13_000
    assert captured[1].max_tokens == 4096
    phase2_prompt = captured[2].messages[1].content
    assert phase2_prompt.startswith("【章节正文】")
    assert "正文" in phase2_prompt.split("你是小说世界资产抽取助手")[0]
    assert "不要输出旁枝路人" in phase2_prompt
    assert captured[2].max_tokens == 24_576
    assert captured_kwargs[0]["timeout_seconds"] == 900
    assert captured_kwargs[1]["timeout_seconds"] == 300
    assert captured_kwargs[2]["timeout_seconds"] == 900


@pytest.mark.asyncio
async def test_phase1a_scene_slicing_uses_window_max_tokens_not_legacy_fixed_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    class FakeProfile:
        provider_id = "deepseek"
        model = "deepseek-v4-flash"
        extra = {}

        def request_defaults(self):
            return {"model": self.model, "temperature": 0.3, "max_tokens": 8192}

    async def fake_call_structured(_client, request, schema, **_kwargs):
        captured.append(request)
        return schema.model_validate(
            {
                "scenes": [
                    {
                        "title": "切分",
                        "goal": "测试",
                        "core_conflict": "冲突",
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "boundary_status": "complete",
                    }
                ]
            }
        )

    monkeypatch.setenv("PHASE1A_SCENE_MAX_TOKENS", "99999")
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters.resolve_llm_profile",
        lambda _settings: FakeProfile(),
    )
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._llm_client_for_profile",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "modules.imports.workflow_llm_adapters._call_structured",
        fake_call_structured,
    )

    await _Phase1aSceneSlicingLLM(
        project_settings={"deep_import": {"phase1a": {"scene_max_tokens": 88888}}},
    )(
        {
            "chapters": [{"chapter_index": 1, "title": "第一章", "content": "正文"}],
            "window": {"owned_start": 1, "owned_end": 1},
            "max_tokens": 13_000,
        }
    )

    assert captured[0].max_tokens == 13_000
