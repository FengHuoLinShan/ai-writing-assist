from __future__ import annotations

from typing import Any

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
    public_info: str | None = None
    hidden_truth: str | None = None
    importance_level: str = Field(default="normal", max_length=16)
    reveal_level: str = Field(default="author_only", max_length=16)
    details: dict[str, Any] = Field(default_factory=dict)
    character_card: dict[str, Any] = Field(default_factory=dict)

    @field_validator("summary")
    @classmethod
    def _summary_must_not_be_blank(cls, value: str) -> str:
        summary = value.strip()
        if not summary:
            raise ValueError("summary must not be blank")
        return summary
