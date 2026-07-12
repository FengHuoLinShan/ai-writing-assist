from __future__ import annotations

from typing import Any

import pytest

from modules.imports.llm_schemas import (
    Phase2WorldExtractionOutput,
    SceneAnchorRepairOutput,
    SceneChunk,
)
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
    assert result.windows[0].max_tokens == 32_768
    assert result.windows[-1].max_tokens == 28_800
    assert result.quality_stats["max_tokens_per_input_char"] == 1.0
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


def test_phase2_world_token_budget_uses_full_generation_bound() -> None:
    assert _phase2_window_max_tokens(26_000) == 32_768
    assert _phase2_window_max_tokens(70_000) == 32_768
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


def test_anchor_repair_output_trims_long_boundaries_toward_scene_edges() -> None:
    start = "起" * 90
    end = "终" * 90

    output = SceneAnchorRepairOutput(start_anchor=start, end_anchor=end)

    assert output.start_anchor == start[:80]
    assert output.end_anchor == end[-80:]


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
    fallback = next(
        candidate for candidate in result.candidates if candidate.start_chapter == 3
    )
    assert fallback.diagnostics["fallback"] is True
    assert fallback.scene_chunks[0].start_offset == 0
    assert fallback.scene_chunks[0].end_offset == 1000
    assert result.quality_stats["fallback_chapter_indices"] == [3, 4, 5]


@pytest.mark.asyncio
async def test_phase1a_recovers_missing_chapter_with_bounded_single_chapter_retry():
    chapters = [
        {
            "chapter_index": 1,
            "title": "第一章",
            "content": "第一章唯一开始。事件推进。第一章唯一结束。",
        },
        {
            "chapter_index": 2,
            "title": "第二章",
            "content": "第二章唯一开始。冲突持续。第二章唯一结束。",
        },
    ]
    plan = build_scene_import_plan(chapters, start_chapter=1, end_chapter=2)

    class LLM:
        async def __call__(self, _payload):
            return {
                "scenes": [
                    {
                        "title": "已覆盖 Scene",
                        "goal": "覆盖第一章",
                        "core_conflict": "事件推进",
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "start_anchor": "第一章唯一开始",
                        "end_anchor": "第一章唯一结束",
                        "boundary_status": "complete",
                    }
                ]
            }

        async def recover_chapter(self, payload):
            assert payload["chapter"]["chapter_index"] == 2
            return {
                "scenes": [
                    {
                        "title": "恢复 Scene",
                        "goal": "覆盖第二章",
                        "core_conflict": "冲突持续",
                        "start_chapter": 2,
                        "end_chapter": 2,
                        "start_anchor": "第二章唯一开始",
                        "end_anchor": "第二章唯一结束",
                        "boundary_status": "complete",
                    }
                ]
            }

    result = await Phase1aSceneSlicer(LLM(), concurrency=1).run(plan)

    recovered = next(
        candidate for candidate in result.candidates if candidate.title == "恢复 Scene"
    )
    assert recovered.diagnostics["chapter_recovery"] is True
    assert recovered.needs_review is True
    assert all(
        chunk.start_offset is not None and chunk.end_offset is not None
        for chunk in recovered.scene_chunks
    )
    assert result.quality_stats["fallback_count"] == 0
    assert result.quality_stats["chapter_recovery_attempted_count"] == 1
    assert result.quality_stats["chapter_recovery_succeeded_count"] == 1
    assert result.quality_stats["chapter_recovery_failed_count"] == 0
    assert result.diagnostics[-1]["final_status"] == "recovered"


@pytest.mark.asyncio
async def test_phase1a_materializes_unique_same_chapter_anchors_to_exact_offsets() -> (
    None
):
    content = (
        "无关前文。\n　唯一开始锚点\n　这里起步，事件继续推进，"
        "唯一结束锚点在此收束。无关尾声。"
    )
    plan = build_scene_import_plan(
        [
            {
                "chapter_index": 1,
                "title": "第一章",
                "content": content,
                "source_draft_id": "00000000-0000-0000-0000-000000000001",
                "source_content_hash": "a" * 64,
            }
        ],
        start_chapter=1,
        end_chapter=1,
    )

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "精确 Scene",
                    "goal": "验证锚点",
                    "core_conflict": "不能依赖 LLM offset",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "start_anchor": "唯一开始锚点这里起步",
                    "end_anchor": "唯一结束锚点在此收束",
                    "boundary_status": "complete",
                }
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    candidate = result.candidates[0]
    chunk = candidate.scene_chunks[0]
    assert chunk.start_offset == content.index("唯一开始锚点")
    assert chunk.end_offset == content.index("唯一结束锚点在此收束") + len(
        "唯一结束锚点在此收束"
    )
    assert chunk.anchor_hash is not None
    assert chunk.anchor_excerpt.startswith("唯一开始锚点")
    assert chunk.source_draft_id == "00000000-0000-0000-0000-000000000001"
    assert chunk.source_content_hash == "a" * 64
    assert candidate.needs_review is False
    assert candidate.diagnostics["source_mapping"] == "exact"
    assert result.quality_stats["exact_scene_count"] == 1
    assert result.quality_stats["unresolved_scene_count"] == 0
    assert result.quality_stats["exact_span_count"] == 1


@pytest.mark.asyncio
async def test_phase1a_repairs_unresolved_anchors_with_small_context_retry() -> None:
    content = "场景开始唯一锚点。中间发生冲突并持续推进。场景结束唯一锚点。"
    plan = build_scene_import_plan(
        [
            {
                "chapter_index": 1,
                "title": "第一章",
                "content": content,
                "source_draft_id": "00000000-0000-0000-0000-000000000002",
                "source_content_hash": "b" * 64,
            }
        ],
        start_chapter=1,
        end_chapter=1,
    )

    class LLM:
        async def __call__(self, _payload):
            return {
                "scenes": [
                    {
                        "title": "待修复 Scene",
                        "goal": "锁定语义",
                        "core_conflict": "首轮锚点无效",
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "start_anchor": "不存在的开始锚点",
                        "end_anchor": "不存在的结束锚点",
                        "boundary_status": "complete",
                    }
                ]
            }

        async def repair_anchors(self, payload):
            assert [chapter["chapter_index"] for chapter in payload["chapters"]] == [1]
            return {
                "start_anchor": "场景开始唯一锚点",
                "end_anchor": "场景结束唯一锚点",
            }

    result = await Phase1aSceneSlicer(LLM(), concurrency=1).run(plan)

    candidate = result.candidates[0]
    chunk = candidate.scene_chunks[0]
    assert chunk.start_offset == content.index("场景开始唯一锚点")
    assert chunk.end_offset == content.index("场景结束唯一锚点") + len("场景结束唯一锚点")
    assert chunk.source_draft_id == "00000000-0000-0000-0000-000000000002"
    assert chunk.source_content_hash == "b" * 64
    assert candidate.diagnostics["anchor_repair"] == {
        "status": "succeeded",
        "unresolved_chapters": [],
    }
    assert result.quality_stats["anchor_repair_attempted_count"] == 1
    assert result.quality_stats["anchor_repair_succeeded_count"] == 1
    assert result.quality_stats["anchor_repair_failed_count"] == 0


@pytest.mark.asyncio
async def test_phase1a_uses_unique_anchors_to_correct_declared_chapter_range() -> None:
    chapters = [
        {"chapter_index": 1, "title": "第一章", "content": "完全无关的第一章正文。"},
        {
            "chapter_index": 2,
            "title": "第二章",
            "content": "唯一正确开始锚点。场景正文。唯一正确结束锚点。",
        },
    ]
    plan = build_scene_import_plan(chapters, start_chapter=1, end_chapter=2)

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "模型章号错一章",
                    "goal": "以正文锚点纠正",
                    "core_conflict": "数字范围与原文冲突",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "start_anchor": "唯一正确开始锚点",
                    "end_anchor": "唯一正确结束锚点",
                    "boundary_status": "complete",
                }
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    corrected = next(
        candidate
        for candidate in result.candidates
        if candidate.title == "模型章号错一章"
    )
    assert corrected.source_chapter_indices == [2]
    assert corrected.diagnostics["declared_chapter_range"] == [1, 1]
    assert corrected.diagnostics["anchored_chapter_range"] == [2, 2]
    assert corrected.scene_chunks[0].start_offset == 0
    assert corrected.scene_chunks[0].end_offset == len(chapters[1]["content"]) - 1
    assert corrected.needs_review is True


@pytest.mark.asyncio
async def test_phase1a_materializes_cross_chapter_scene_without_future_text() -> None:
    chapters = [
        {
            "chapter_index": 1,
            "title": "第一章",
            "content": "前文。跨章场景从这个唯一锚点开始，然后继续到章末。",
        },
        {
            "chapter_index": 2,
            "title": "第二章",
            "content": "第二章全部属于这个跨章场景。",
        },
        {
            "chapter_index": 3,
            "title": "第三章",
            "content": "场景在此继续，直到这个唯一结束锚点为止。未来新场景。",
        },
    ]
    plan = build_scene_import_plan(chapters, start_chapter=1, end_chapter=3)

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "跨章 Scene",
                    "goal": "跨章推进",
                    "core_conflict": "只能读取当前 Scene",
                    "start_chapter": 1,
                    "end_chapter": 3,
                    "start_anchor": "跨章场景从这个唯一锚点开始",
                    "end_anchor": "直到这个唯一结束锚点为止",
                    "boundary_status": "complete",
                }
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    chunks = result.candidates[0].scene_chunks
    assert [
        (chunk.chapter_index, chunk.start_offset, chunk.end_offset) for chunk in chunks
    ] == [
        (1, chapters[0]["content"].index("跨章场景"), len(chapters[0]["content"])),
        (2, 0, len(chapters[1]["content"])),
        (
            3,
            0,
            chapters[2]["content"].index("直到这个唯一结束锚点为止")
            + len("直到这个唯一结束锚点为止"),
        ),
    ]
    selected_last = chapters[2]["content"][: chunks[-1].end_offset]
    assert "未来新场景" not in selected_last


@pytest.mark.asyncio
async def test_phase1a_fills_single_owner_cross_chapter_edge_from_coverage() -> None:
    chapters = [
        {
            "chapter_index": 1,
            "title": "第一章",
            "content": "前文。唯一跨章开始。场景延续到下一章。",
        },
        {
            "chapter_index": 2,
            "title": "第二章",
            "content": "该章只由这个跨章 Scene 拥有，模型的结束锚点却无效。",
        },
    ]
    plan = build_scene_import_plan(chapters, start_chapter=1, end_chapter=2)

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "唯一跨章 Scene",
                    "goal": "覆盖两章",
                    "core_conflict": "结束锚点无法命中",
                    "start_chapter": 1,
                    "end_chapter": 2,
                    "start_anchor": "唯一跨章开始",
                    "end_anchor": "不存在的结束锚点",
                    "boundary_status": "complete",
                }
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    candidate = result.candidates[0]
    assert [
        (chunk.chapter_index, chunk.start_offset, chunk.end_offset)
        for chunk in candidate.scene_chunks
    ] == [
        (1, chapters[0]["content"].index("唯一跨章开始"), len(chapters[0]["content"])),
        (2, 0, len(chapters[1]["content"])),
    ]
    assert candidate.diagnostics["single_owner_inferred_chapters"] == [2]
    assert candidate.diagnostics["source_mapping"] == "exact"
    assert result.quality_stats["anchor_repair_attempted_count"] == 0
    assert result.quality_stats["exact_scene_rate"] == 1.0


@pytest.mark.asyncio
async def test_phase1a_keeps_ambiguous_anchor_as_reviewable_chapter_only() -> None:
    content = "重复开始锚点。中间。重复开始锚点。唯一结束锚点。"
    plan = build_scene_import_plan(
        [{"chapter_index": 1, "title": "第一章", "content": content}],
        start_chapter=1,
        end_chapter=1,
    )

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "待复核 Scene",
                    "goal": "不伪造定位",
                    "core_conflict": "锚点不唯一",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "start_anchor": "重复开始锚点",
                    "end_anchor": "唯一结束锚点",
                    "boundary_status": "uncertain",
                }
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    candidate = result.candidates[0]
    assert candidate.scene_chunks[0].start_offset is None
    assert candidate.scene_chunks[0].end_offset is None
    assert candidate.needs_review is True
    assert candidate.diagnostics["unresolved_chapters"] == [1]


@pytest.mark.asyncio
async def test_phase1a_closes_one_sided_boundary_from_adjacent_exact_scene() -> None:
    content = "甲场景开始，甲场景在此结束。乙场景正文，乙场景在此结束。"
    plan = build_scene_import_plan(
        [{"chapter_index": 1, "title": "第一章", "content": content}],
        start_chapter=1,
        end_chapter=1,
    )

    async def llm(_payload):
        return {
            "scenes": [
                {
                    "title": "甲 Scene",
                    "goal": "甲",
                    "core_conflict": "甲",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "start_anchor": "甲场景开始",
                    "end_anchor": "甲场景在此结束。",
                    "boundary_status": "complete",
                },
                {
                    "title": "乙 Scene",
                    "goal": "乙",
                    "core_conflict": "乙",
                    "start_chapter": 1,
                    "end_chapter": 1,
                    "start_anchor": "模型改写后无法命中的乙场景开始",
                    "end_anchor": "乙场景在此结束。",
                    "boundary_status": "uncertain",
                },
            ]
        }

    result = await Phase1aSceneSlicer(llm, concurrency=1).run(plan)

    first, second = [
        candidate for candidate in result.candidates if "Scene" in candidate.title
    ]
    assert first.scene_chunks[0].end_offset is not None
    assert second.scene_chunks[0].start_offset == first.scene_chunks[0].end_offset
    assert second.scene_chunks[0].end_offset == len(content)
    assert second.diagnostics["neighbor_inferred_chapters"] == [1]
    assert second.diagnostics["unresolved_chapters"] == []
    assert second.needs_review is True


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
        scene_chunks=[
            SceneChunk(
                chapter_index=2,
                start_offset=5,
                end_offset=50,
                anchor_hash="a" * 64,
                anchor_excerpt="精确起点",
            ),
            SceneChunk(
                chapter_index=3,
                start_offset=0,
                end_offset=40,
                anchor_hash="b" * 64,
                anchor_excerpt="精确续章",
            ),
        ],
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
    assert [
        (chunk.start_offset, chunk.end_offset) for chunk in candidate.scene_chunks
    ] == [
        (5, 50),
        (0, 40),
    ]
    assert candidate.narrative_tag == "turning_point"
    assert result.quality_stats["concurrency"] == 200
    assert result.quality_stats["max_retries"] == 1


def test_phase1a_and_phase1b_default_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def llm(_payload):
        return {}

    assert Phase1aSceneSlicer(llm).concurrency == 50
    assert Phase1bSceneEnricher(llm).concurrency == 200
    monkeypatch.setenv("PHASE1B_ENRICH_MAX_TOKENS", "4096")
    assert Phase1bSceneEnricher(llm, max_tokens=32_768).max_tokens == 32_768


@pytest.mark.asyncio
async def test_high_quality_adapters_keep_model_and_use_max_deepseek_reasoning(
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
        "deepseek-v4-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash",
    ]
    assert all(request.extra["thinking"] == {"type": "enabled"} for request in captured)
    assert all(request.extra["reasoning_effort"] == "max" for request in captured)
    phase1a_prompt = captured[0].messages[1].content
    assert phase1a_prompt.startswith("## 第1章 第一章")
    assert "正文" in phase1a_prompt.split("【输入范围】")[0]
    assert "start_anchor" in phase1a_prompt
    assert "end_anchor" in phase1a_prompt
    assert "逐字复制" in phase1a_prompt
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
async def test_phase1a_anchor_repair_adapter_uses_locked_small_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    class FakeProfile:
        provider_id = "deepseek"
        model = "deepseek-v4-flash"
        extra = {}

    async def fake_call_structured(_client, request, schema, **_kwargs):
        captured.append(request)
        return schema.model_validate(
            {
                "start_anchor": "唯一开始锚点正文",
                "end_anchor": "唯一结束锚点正文",
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

    result = await _Phase1aSceneSlicingLLM().repair_anchors(
        {
            "candidate": {
                "title": "锁定标题",
                "goal": "锁定目标",
                "core_conflict": "锁定冲突",
                "start_chapter": 2,
                "end_chapter": 2,
            },
            "chapters": [{"chapter_index": 2, "title": "第二章", "content": "唯一正文"}],
        }
    )

    assert result.start_anchor == "唯一开始锚点正文"
    request = captured[0]
    assert request.model == "deepseek-v4-flash"
    assert request.max_tokens == 32_768
    assert request.extra["thinking"] == {"type": "enabled"}
    assert request.extra["reasoning_effort"] == "high"
    assert "锁定标题" in request.messages[1].content
    assert "唯一正文" in request.messages[1].content
    assert "不得改变 Scene 语义或章节范围" in request.messages[1].content


@pytest.mark.asyncio
async def test_phase1a_missing_chapter_adapter_uses_high_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = []

    class FakeProfile:
        provider_id = "deepseek"
        model = "deepseek-v4-flash"
        extra = {}

    async def fake_call_structured(_client, request, schema, **kwargs):
        captured.append((request, kwargs))
        return schema.model_validate(
            {
                "scenes": [
                    {
                        "title": "恢复 Scene",
                        "goal": "恢复覆盖",
                        "core_conflict": "避免章节缺口",
                        "start_chapter": 2,
                        "end_chapter": 2,
                        "start_anchor": "唯一开始锚点",
                        "end_anchor": "唯一结束锚点",
                        "boundary_status": "complete",
                    }
                ]
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

    result = await _Phase1aSceneSlicingLLM().recover_chapter(
        {
            "chapter": {
                "chapter_index": 2,
                "title": "第二章",
                "content": "唯一开始锚点。正文。唯一结束锚点。",
            }
        }
    )

    assert result.scenes[0].start_chapter == 2
    request, kwargs = captured[0]
    assert request.model == "deepseek-v4-flash"
    assert request.max_tokens == 8192
    assert request.extra["thinking"] == {"type": "enabled"}
    assert request.extra["reasoning_effort"] == "high"
    assert "仅切分第2章" in request.messages[1].content
    assert "普通动作和过渡应吸收" in request.messages[1].content
    assert "1-3" not in request.messages[1].content
    assert kwargs["step_name"] == "phase1a_missing_chapter_recovery"


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
