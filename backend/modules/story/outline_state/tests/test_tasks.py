from __future__ import annotations

import pytest

from modules.story.outline_state.generation.context_builder import PlotStructureContext
from modules.story.outline_state.generation.models import GeneratedThread
from modules.story.outline_state.generation.parser import PlotStructureParser


class _CaptureLLM:
    def __init__(self) -> None:
        self.request = None
        self.kwargs = None

    async def generate_structured(self, request, schema, **kwargs):
        self.request = request
        self.kwargs = kwargs
        return schema(
            plot_threads=[
                GeneratedThread(
                    name="主线：灰雾召唤",
                    thread_type="main",
                    summary="克莱恩接触灰雾空间",
                )
            ],
            scenes=[],
        )


class TestPlotStructureParserDeepImportMode:
    @pytest.mark.asyncio
    async def test_deep_import_without_scene_evidence_returns_review_empty(self) -> None:
        context = PlotStructureContext(
            markdown="## 已生成 Scene 摘要\n- S0 第1章《穿越苏醒》：克莱恩醒来\n"
        )
        llm = _CaptureLLM()

        result = await PlotStructureParser(
            context,
            include_scenes=False,
            fast_structured=True,
        ).parse(llm, "codex-5.3", 1, 7)

        assert result is not None
        assert result.threads == []
        assert result.arcs == []
        assert result.diagnostics == {
            "parameter_version": "phase3_structure_simple_v3",
            "input_mode": "no_scene_evidence",
            "prompt_level": "none",
            "provider_called": False,
            "needs_review": True,
        }
        assert llm.request is None
