"""
LLM 调用相关的 Pydantic schema

定义 LLM 调用的入参和出参结构。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LLMToolCall(BaseModel):
    """Provider tool call; arguments remain JSON until tool schema validation."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    arguments: str = Field(default="{}", max_length=100000)


class LLMToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    description: str = Field(default="", max_length=8000)
    parameters: dict[str, Any]


class LLMToolDelta(BaseModel):
    """Incomplete JSON is permitted only while assembling a provider stream."""

    index: int = Field(ge=0)
    id: str | None = None
    name: str | None = None
    arguments: str | None = None


class LLMMessage(BaseModel):
    """LLM 对话消息"""

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str = ""
    tool_calls: list[LLMToolCall] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    tool_call_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    reasoning_content: str | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_tool_role(self) -> LLMMessage:
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages can request tools")
        if (self.role == "tool") != bool(self.tool_call_id):
            raise ValueError("Tool results require a paired tool call ID")
        return self

    def provider_message(self) -> dict[str, Any]:
        result = self.model_dump()
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in self.tool_calls
            ]
        if self.reasoning_content is not None:
            result["reasoning_content"] = self.reasoning_content
        return result


class LLMCallRequest(BaseModel):
    """LLM 调用请求参数"""

    model: str = "deepseek-flash"
    """模型名称"""
    messages: list[LLMMessage] = Field(default_factory=list)
    """对话消息列表"""
    temperature: float | None = 0.7
    """生成温度"""
    max_tokens: int | None = None
    """最大输出 token 数；None 表示继承当前 LLMClient 的默认值"""
    response_format: dict[str, str] | None = None
    """响应格式约束，如 {"type": "json_object"}"""
    stop: list[str] | None = None
    """停止序列"""
    top_p: float | None = None
    """Top-p 采样"""
    frequency_penalty: float | None = None
    """频率惩罚"""
    presence_penalty: float | None = None
    """存在惩罚"""
    seed: int | None = None
    """随机种子（用于可复现生成）"""
    extra: dict[str, Any] = Field(default_factory=dict)
    """额外 provider 特定参数"""
    tools: list[LLMToolDefinition] = Field(default_factory=list)
    tool_choice: Literal["auto", "none", "required"] | None = None

    @model_validator(mode="after")
    def validate_tool_history(self) -> LLMCallRequest:
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("Tool names must be unique")
        pending: set[str] = set()
        seen: set[str] = set()
        for message in self.messages:
            if message.role == "tool":
                if message.tool_call_id not in pending:
                    raise ValueError("Unpaired or duplicate tool result")
                pending.remove(message.tool_call_id)
            else:
                if pending:
                    raise ValueError(
                        "Tool calls must be resolved before the next message"
                    )
                for call in message.tool_calls:
                    if call.id in seen:
                        raise ValueError("Tool call IDs must be unique")
                    seen.add(call.id)
                    pending.add(call.id)
        if pending:
            raise ValueError("Unresolved tool calls cannot be sent to the model")
        return self


class LLMUsage(BaseModel):
    """LLM 调用 token 用量"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMCallResponse(BaseModel):
    """LLM 调用响应"""

    content: str = ""
    """生成的文本内容"""
    finish_reason: str = ""
    """结束原因：stop / length / content_filter / tool_calls"""
    usage: LLMUsage = Field(default_factory=LLMUsage)
    """token 用量统计"""
    model: str = ""
    """实际使用的模型名称"""
    provider: str = ""
    """使用的 provider 名称"""
    latency_ms: float = 0.0
    """调用耗时（毫秒）"""
    raw: dict[str, Any] = Field(default_factory=dict)
    """原始响应（调试用）"""
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    reasoning_content: str | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def unique_tool_calls(self):
        if len({call.id for call in self.tool_calls}) != len(self.tool_calls):
            raise ValueError("Provider returned duplicate tool call IDs in one response")
        return self


class LLMStreamChunk(BaseModel):
    """流式输出片段"""

    content: str = ""
    """当前片段文本"""
    reasoning_chars: int = Field(default=0, ge=0, exclude=True)
    """Internal count only; never forward reasoning text or add it to browser wire."""
    finish_reason: str | None = None
    """如果该片段是最后一个，提供结束原因"""
    usage: LLMUsage | None = None
    """最后一块可能包含用量信息"""
    tool_deltas: list[LLMToolDelta] = Field(default_factory=list)
    reasoning_content: str | None = Field(default=None, exclude=True, repr=False)
