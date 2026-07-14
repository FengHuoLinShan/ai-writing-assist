from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class GeneratedObjectDraftOutput(BaseModel):
    """Generation Center structured LLM output for a draft world object."""

    name: str = Field(..., min_length=1, max_length=255)
    summary: str = Field(
        ...,
        min_length=12,
        max_length=5000,
        description="对象概要，必须能直接显示在对象库列表和编辑弹窗中。",
    )
    public_info: str | None = Field(
        default=None,
        description="项目世界中的人物或读者当前可以知道的信息。",
    )
    hidden_truth: str | None = Field(
        default=None,
        description="只有对象确实存在隐藏层时填写，否则为 null。",
    )
    importance_level: Literal["core", "important", "normal", "temporary"] = (
        "normal"
    )
    reveal_level: Literal[
        "author_only",
        "hinted",
        "revealed",
        "fully_known",
    ] = "author_only"
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="只保留与对象类型和本次设计相关的扩展内容。",
    )
    character_card: dict[str, Any] = Field(
        default_factory=dict,
        description="仅人物对象使用，不为完整度填充无依据字段。",
    )

    @field_validator("summary")
    @classmethod
    def _summary_must_not_be_blank(cls, value: str) -> str:
        summary = value.strip()
        if not summary:
            raise ValueError("summary must not be blank")
        return summary


class GeneratedWorldBiblePagePatchOutput(BaseModel):
    """Structured output for appending AI-organized text to a World Bible page."""

    append_text: str = Field(..., min_length=1, max_length=20000)
    reason: str = Field(default="", max_length=1000)


class GeneratedWorldBibleNewPageOutput(BaseModel):
    """Structured output for a new World Bible page suggestion."""

    title: str = Field(..., min_length=1, max_length=255)
    page_type: str = Field(default="custom", min_length=1, max_length=64)
    free_text: str = Field(..., min_length=1, max_length=30000)
    reason: str = Field(default="", max_length=1000)
