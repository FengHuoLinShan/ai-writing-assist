"""PlotStructureParser 单元测试。"""

from __future__ import annotations

from unittest import mock

import pytest
from pydantic import BaseModel, ValidationError

from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMCallResponse
from modules.outline.generation.context_builder import PlotStructureContext
from modules.outline.generation.models import GeneratedOutput, GeneratedThread
from modules.outline.generation.parser import PlotStructureParser


@pytest.fixture
def context() -> PlotStructureContext:
    return PlotStructureContext(
        markdown="# 测试上下文",
        entity_name_to_id={},
        character_name_to_id={},
    )


@pytest.fixture
def parser(context: PlotStructureContext) -> PlotStructureParser:
    return PlotStructureParser(context)


class _FakeLLMClient:
    """可按场景注入返回值的假 LLMClient。"""

    def __init__(self, return_value: BaseModel | None = None) -> None:
        self.return_value = return_value
        self.calls: list[LLMCallRequest] = []

    async def generate_structured(
        self,
        request: LLMCallRequest,
        response_model: type[BaseModel],
    ) -> BaseModel:
        self.calls.append(request)
        if isinstance(self.return_value, Exception):
            raise self.return_value
        if self.return_value is None:
            return response_model()
        return self.return_value

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        self.calls.append(request)
        return LLMCallResponse(content='{"plot_threads": []}')


@pytest.mark.asyncio
async def test_parse_returns_parsed_structure(
    parser: PlotStructureParser,
) -> None:
    """正常 LLM 输出被正确解析为 ParsedPlotStructure。"""
    fake_client = _FakeLLMClient(
        return_value=GeneratedOutput(
            plot_threads=[GeneratedThread(name="主线", thread_type="main")]
        )
    )

    result = await parser.parse(fake_client, "gpt-4", 1, 3)

    assert result is not None
    assert len(result.threads) == 1
    assert result.threads[0].name == "主线"


@pytest.mark.asyncio
async def test_parse_retries_on_empty_output(
    parser: PlotStructureParser,
) -> None:
    """空 LLM 输出会重试，最终返回 None。"""
    fake_client = _FakeLLMClient(return_value=GeneratedOutput())

    result = await parser.parse(fake_client, "gpt-4", 1, 3)

    assert result is None
    assert len(fake_client.calls) == parser.MAX_EMPTY_RETRIES + 1


@pytest.mark.asyncio
async def test_parse_falls_back_to_per_item_validation(
    parser: PlotStructureParser,
) -> None:
    """结构化校验失败时降级到逐项校验。"""
    fake_client = LLMClient()

    # 第一次 generate_structured 抛 ValidationError，第二次 generate 返回合法 JSON
    with (
        mock.patch.object(
            fake_client,
            "generate_structured",
            side_effect=ValidationError.from_exception_data("GeneratedOutput", []),
        ) as mock_structured,
        mock.patch.object(
            fake_client,
            "generate",
            return_value=LLMCallResponse(
                content='{"plot_threads": [{"name": "主线", "thread_type": "main"}]}'
            ),
        ) as mock_generate,
    ):
        result = await parser.parse(fake_client, "gpt-4", 1, 3)

    assert result is not None
    assert len(result.threads) == 1
    mock_structured.assert_awaited()
    mock_generate.assert_awaited()


@pytest.mark.asyncio
async def test_parse_graceful_on_generic_llm_failure(
    parser: PlotStructureParser,
) -> None:
    """通用 LLM 异常时优雅降级为空结果。"""
    fake_client = _FakeLLMClient(return_value=Exception("LLM down"))

    result = await parser.parse(fake_client, "gpt-4", 1, 3)

    assert result is None
