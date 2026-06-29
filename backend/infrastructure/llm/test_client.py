"""LLM client structured-output behavior tests."""

from __future__ import annotations

from types import MethodType

import pytest
from pydantic import BaseModel, Field

from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMUsage,
)


class _StructuredPayload(BaseModel):
    value: str = Field(..., min_length=1)


@pytest.mark.asyncio
async def test_generate_structured_retries_truncated_json_with_larger_budget() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            return LLMCallResponse(
                content='{"value": "unfinished',
                finish_reason="length",
                usage=LLMUsage(completion_tokens=20000, total_tokens=20000),
                model="fake",
                provider="fake",
            )
        return LLMCallResponse(
            content='{"value": "complete"}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=8, total_tokens=8),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(
            model="fake",
            messages=[LLMMessage(role="user", content="return json")],
            max_tokens=20000,
        ),
        _StructuredPayload,
    )

    assert result.value == "complete"
    assert len(requests) == 2
    assert requests[1].max_tokens == 40000
    assert requests[1].messages[-1].role == "user"
    assert "上一轮输出被截断" in requests[1].messages[-1].content
    assert "从头重新输出完整 JSON" in requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_generate_structured_validation_retry_keeps_existing_fix_path() -> None:
    client = LLMClient()
    requests: list[LLMCallRequest] = []

    async def fake_generate(self: LLMClient, request: LLMCallRequest) -> LLMCallResponse:
        requests.append(request.model_copy(deep=True))
        if len(requests) == 1:
            return LLMCallResponse(
                content='{"value": ""}',
                finish_reason="stop",
                usage=LLMUsage(completion_tokens=5, total_tokens=5),
                model="fake",
                provider="fake",
            )
        return LLMCallResponse(
            content='{"value": "valid"}',
            finish_reason="stop",
            usage=LLMUsage(completion_tokens=5, total_tokens=5),
            model="fake",
            provider="fake",
        )

    client.generate = MethodType(fake_generate, client)  # type: ignore[method-assign]

    result = await client.generate_structured(
        LLMCallRequest(
            model="fake",
            messages=[LLMMessage(role="user", content="return json")],
            max_tokens=20000,
        ),
        _StructuredPayload,
    )

    assert result.value == "valid"
    assert len(requests) == 2
    assert requests[1].max_tokens == 20000
    assert "Your previous response failed validation" in requests[1].messages[-1].content
