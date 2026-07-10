from __future__ import annotations

import pytest

from modules.outline.generation.context_builder import PlotStructureContext
from modules.outline.generation.parser import PlotStructureParser
from modules.outline.generation.persister import PersistResult
from modules.outline.generator import PlotStructureGenerator


class FakeLLM:
    def __init__(self) -> None:
        self.requests = []

    async def generate_structured(self, request, schema, **_kwargs):
        self.requests.append(request)
        return schema.model_validate(
            {
                "plot_threads": [
                    {
                        "title": "穿越与值夜者主线",
                        "summary": "克莱恩从苏醒到加入值夜者。",
                        "thread_type": "main",
                        "current_stage": "active",
                        "supporting_scene_ids": ["scene-1", "missing"],
                    }
                ],
                "arcs": [
                    {
                        "character_name": "克莱恩",
                        "title": "身份适应弧",
                        "summary": "从求生到主动接触超凡。",
                        "confidence": 0.4,
                        "supporting_scene_ids": ["scene-1"],
                    }
                ],
                "foreshadowing": [
                    {
                        "title": "灰雾空间",
                        "summary": "灰雾建立后续塔罗会伏笔。",
                        "supporting_scene_ids": ["scene-1"],
                    }
                ],
                "reveals": [
                    {
                        "title": "罗塞尔日记",
                        "summary": "中文日记揭示穿越者线索。",
                        "supporting_scene_ids": ["scene-2"],
                    }
                ],
                "turning_points": [
                    {
                        "title": "决定加入值夜者",
                        "summary": "主角选择进入超凡组织。",
                        "supporting_scene_ids": ["scene-2"],
                    }
                ],
                "uncertain_items": [],
            }
        )


@pytest.mark.asyncio
async def test_deep_import_simple_structure_parser_converts_probe_shape() -> None:
    context = PlotStructureContext(
        markdown="## 世界对象\n- 克莱恩：主角\n",
        scenes=[
            {
                "scene_id": "scene-1",
                "scene_index": 1,
                "title": "苏醒",
                "start_chapter": 1,
                "end_chapter": 5,
            },
            {
                "scene_id": "scene-2",
                "scene_index": 2,
                "title": "加入",
                "start_chapter": 6,
                "end_chapter": 10,
            },
        ],
    )
    llm = FakeLLM()

    parsed = await PlotStructureParser(
        context,
        include_scenes=False,
        fast_structured=True,
    ).parse(llm, "deepseek-v4-pro", 1, 10)

    assert parsed is not None
    assert [thread.name for thread in parsed.threads] == ["穿越与值夜者主线"]
    assert parsed.threads[0].start_chapter == 1
    assert parsed.threads[0].supporting_scene_ids == ["scene-1"]
    assert parsed.threads[0].needs_review is True
    assert "invalid_supporting_scene_refs_removed" in (
        parsed.threads[0].review_reason
    )
    assert [arc.title for arc in parsed.arcs] == ["身份适应弧"]
    assert parsed.arcs[0].confidence == 0.4
    assert parsed.arcs[0].needs_review is True
    assert "low_confidence" in parsed.arcs[0].review_reason
    assert parsed.arcs[0].supporting_scene_ids == ["scene-1"]
    assert [item.name for item in parsed.foreshadowing_plans] == ["灰雾空间"]
    assert [item.target_name for item in parsed.reveal_plans] == ["罗塞尔日记"]
    assert parsed.turning_points[0]["title"] == "决定加入值夜者"
    assert parsed.diagnostics["parameter_version"] == "phase3_structure_simple_v1"
    assert parsed.diagnostics["invalid_scene_ref_count"] == 1
    assert parsed.diagnostics["turning_point_count"] == 1

    request = llm.requests[0]
    assert request.model == "deepseek-v4-pro"
    assert request.extra["thinking"] == {"type": "enabled"}
    assert request.extra["reasoning_effort"] == "max"
    assert request.max_tokens == 12_288
    assert request.messages[1].content.startswith("【Scene卡片 JSON】")
    assert "## 世界对象" in request.messages[1].content
    assert '"current_stage": "active|resolved|paused"' in request.messages[1].content
    assert '"status": "active|resolved|paused"' not in request.messages[1].content


@pytest.mark.asyncio
async def test_deep_import_structure_generator_high_quality_uses_pro_model() -> None:
    class FakeContextBuilder:
        async def build(self, *_args, **_kwargs):
            return PlotStructureContext(
                markdown="## 世界对象\n- 克莱恩：主角\n",
                scenes=[
                    {
                        "scene_id": "scene-1",
                        "scene_index": 1,
                        "title": "苏醒",
                        "start_chapter": 1,
                        "end_chapter": 1,
                    }
                ],
            )

    class FakePersister:
        async def persist(self, *_args, **_kwargs):
            return PersistResult(total_threads=1, total_arcs=1)

    llm = FakeLLM()
    generator = PlotStructureGenerator(
        context_builder=FakeContextBuilder(),
        llm_client=llm,
        persister=FakePersister(),
    )

    await generator.generate(
        None,
        "00000000-0000-0000-0000-000000000001",
        1,
        1,
        include_chapter_texts=False,
        include_existing_scenes=True,
        generate_scenes=False,
        fast_structured=True,
        high_quality=True,
        persist=True,
    )

    assert llm.requests[0].model == "deepseek-v4-pro"
