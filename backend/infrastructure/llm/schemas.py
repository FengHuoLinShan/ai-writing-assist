"""
LLM 调用相关的 Pydantic schema

定义 LLM 调用的入参和出参结构。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    """LLM 对话消息"""

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str = ""


class LLMCallRequest(BaseModel):
    """LLM 调用请求参数"""

    model: str = "deepseek-v4-flash"
    """模型名称"""
    messages: list[LLMMessage] = Field(default_factory=list)
    """对话消息列表"""
    temperature: float | None = 0.7
    """生成温度"""
    max_tokens: int | None = 4096
    """最大输出 token 数"""
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


class LLMStreamChunk(BaseModel):
    """流式输出片段"""

    content: str = ""
    """当前片段文本"""
    finish_reason: str | None = None
    """如果该片段是最后一个，提供结束原因"""
    usage: LLMUsage | None = None
    """最后一块可能包含用量信息"""
