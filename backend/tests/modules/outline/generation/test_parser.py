"""Deep-import-only PlotStructureParser tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from infrastructure.llm.schemas import LLMCallRequest
from modules.story.outline_state.generation.context_builder import PlotStructureContext
from modules.story.outline_state.generation.models import (
    SimplePlotThread,
    SimpleStructureOutput,
)
from modules.story.outline_state.generation.parser import PlotStructureParser


class _FakeLLMClient:
    def __init__(self, return_value: BaseModel | Exception | None = None) -> None:
        self.return_value = return_value
        self.calls: list[LLMCallRequest] = []

    async def generate_structured(
        self,
        request: LLMCallRequest,
        response_model: type[BaseModel],
        **_kwargs,
    ) -> BaseModel:
        self.calls.append(request)
        if isinstance(self.return_value, Exception):
            raise self.return_value
        if self.return_value is None:
            return response_model()
        return self.return_value


def _context(*, with_scene: bool) -> PlotStructureContext:
    return PlotStructureContext(
        markdown="# 已采用世界资料",
        entity_name_to_id={},
        character_name_to_id={},
        scenes=(
            [
                {
                    "scene_id": "S-1",
                    "title": "门前试探",
                    "start_chapter": 1,
                    "end_chapter": 2,
                }
            ]
            if with_scene
            else []
        ),
    )


@pytest.mark.asyncio
async def test_creative_whole_structure_path_is_retired() -> None:
    parser = PlotStructureParser(_context(with_scene=True), fast_structured=False)

    with pytest.raises(RuntimeError, match="P20 current-layer workflow"):
        await parser.parse(_FakeLLMClient(), "deepseek-v4", 1, 3)


@pytest.mark.asyncio
async def test_phase3_without_scene_evidence_returns_review_without_provider() -> None:
    parser = PlotStructureParser(_context(with_scene=False), fast_structured=True)
    client = _FakeLLMClient()

    result = await parser.parse(client, "deepseek-v4", 1, 3)

    assert result is not None
    assert result.threads == []
    assert result.diagnostics == {
        "parameter_version": "phase3_structure_simple_v1",
        "input_mode": "no_scene_evidence",
        "prompt_level": "none",
        "provider_called": False,
        "needs_review": True,
    }
    assert client.calls == []


@pytest.mark.asyncio
async def test_phase3_structures_only_scene_supported_evidence() -> None:
    parser = PlotStructureParser(_context(with_scene=True), fast_structured=True)
    client = _FakeLLMClient(
        SimpleStructureOutput(
            plot_threads=[
                SimplePlotThread(
                    title="潮门调查",
                    summary="主角循着门上的光追查失踪者。",
                    supporting_scene_ids=["S-1"],
                )
            ]
        )
    )

    result = await parser.parse(client, "deepseek-v4", 1, 3)

    assert result is not None
    assert [item.name for item in result.threads] == ["潮门调查"]
    assert result.threads[0].supporting_scene_ids == ["S-1"]
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_phase3_provider_failure_returns_none_without_creative_fallback() -> None:
    parser = PlotStructureParser(_context(with_scene=True), fast_structured=True)
    client = _FakeLLMClient(RuntimeError("provider unavailable"))

    result = await parser.parse(client, "deepseek-v4", 1, 3)

    assert result is None
    assert len(client.calls) == 1
