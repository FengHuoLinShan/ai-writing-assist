"""LLM Schema 测试"""

from __future__ import annotations

from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMStreamChunk,
    LLMUsage,
)


class TestLLMMessage:
    def test_default_role(self) -> None:
        msg = LLMMessage(content="hello")
        assert msg.role == "user"

    def test_system_message(self) -> None:
        msg = LLMMessage(role="system", content="be helpful")
        assert msg.role == "system"

    def test_serialize(self) -> None:
        msg = LLMMessage(role="user", content="hi")
        data = msg.model_dump()
        assert data == {"role": "user", "content": "hi"}


class TestLLMCallRequest:
    def test_defaults(self) -> None:
        req = LLMCallRequest()
        assert req.model == "deepseek-v4-flash"
        assert req.messages == []
        assert req.temperature == 0.7
        assert req.max_tokens is None

    def test_with_messages(self) -> None:
        req = LLMCallRequest(
            model="deepseek-v4-flash",
            messages=[LLMMessage(role="user", content="hello")],
            temperature=0.3,
        )
        assert req.model == "deepseek-v4-flash"
        assert len(req.messages) == 1
        assert req.messages[0].content == "hello"

    def test_response_format(self) -> None:
        req = LLMCallRequest(response_format={"type": "json_object"})
        assert req.response_format == {"type": "json_object"}


class TestLLMUsage:
    def test_defaults(self) -> None:
        u = LLMUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_with_values(self) -> None:
        u = LLMUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert u.total_tokens == 30


class TestLLMCallResponse:
    def test_defaults(self) -> None:
        resp = LLMCallResponse()
        assert resp.content == ""
        assert resp.model == ""
        assert resp.latency_ms == 0.0

    def test_with_values(self) -> None:
        resp = LLMCallResponse(
            content="Hello!",
            finish_reason="stop",
            usage=LLMUsage(total_tokens=50),
            model="gpt-4o",
            provider="openai",
            latency_ms=123.4,
        )
        assert resp.content == "Hello!"
        assert resp.usage.total_tokens == 50
        assert resp.raw == {}


class TestLLMStreamChunk:
    def test_defaults(self) -> None:
        chunk = LLMStreamChunk()
        assert chunk.content == ""
        assert chunk.finish_reason is None
        assert chunk.usage is None

    def test_final_chunk(self) -> None:
        chunk = LLMStreamChunk(
            content="",
            finish_reason="stop",
            usage=LLMUsage(total_tokens=100),
        )
        assert chunk.finish_reason == "stop"
        assert chunk.usage is not None
