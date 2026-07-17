from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class GeneratedWorldGenerationChatOutput(BaseModel):
    """Validated natural-language reply for Generation Center world chat."""

    reply: str = Field(..., min_length=1, max_length=30000)

    @field_validator("reply")
    @classmethod
    def _reply_must_not_be_blank(cls, value: str) -> str:
        reply = value.strip()
        if not reply:
            raise ValueError("reply must not be blank")
        return reply


class GeneratedWorldGenerationDecisionState(BaseModel):
    """Author-controlled state compiled from a multi-turn generation chat."""

    current_author_goal: str = Field(..., min_length=1, max_length=4000)
    confirmed_requirements: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="作者明确确认、选择或修正后仍然有效的要求。",
    )
    supported_developments: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="最近共创结果中直接落实作者要求、可继续收束的内容。",
    )
    rejected_elements: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="作者已经否定、作废、替换或明确禁止的内容。",
    )
    forbidden_exact_terms: list[str] = Field(
        default_factory=list,
        max_length=64,
        description="被作者明确作废且不得在提案中再次出现的名称或短语。",
    )
    unresolved_choices: list[str] = Field(default_factory=list, max_length=64)
    naming_policy: Literal["allowed", "unnamed_placeholder", "uncertain"] = (
        "allowed"
    )
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("forbidden_exact_terms")
    @classmethod
    def _normalize_forbidden_exact_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            term = value.strip()
            if len(term) < 2 or term in normalized:
                continue
            normalized.append(term)
        return normalized


class GeneratedWorldGenerationDecisionAudit(BaseModel):
    """Narrow semantic audit of a proposal against compiled author decisions."""

    verdict: Literal["pass", "revise"]
    violations: list[str] = Field(default_factory=list, max_length=20)


class GeneratedObjectDraftOutput(BaseModel):
    """Generation Center structured LLM output for a draft world object."""

    name: str = Field(..., min_length=1, max_length=255)
    summary: str = Field(
        ...,
        min_length=1,
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
    importance_level: Literal["core", "important", "normal", "temporary"] = "normal"
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
    review_notes: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="只记录影响作者采用的事实冲突、关键假设或未决选择。",
    )

    @field_validator("summary")
    @classmethod
    def _summary_must_not_be_blank(cls, value: str) -> str:
        summary = value.strip()
        if not summary:
            raise ValueError("summary must not be blank")
        return summary


class GeneratedWorldBibleSectionProposal(BaseModel):
    """LLM-facing section proposal without database identifiers."""

    source_section_key: str | None = Field(default=None, max_length=32)
    section_type: Literal["markdown", "checklist", "asset_collection"] = "markdown"
    title: str = Field(..., min_length=1, max_length=120)
    body_markdown: str = Field(default="", max_length=30000)
    linked_asset_keys: list[str] = Field(default_factory=list, max_length=100)


class GeneratedWorldBibleNewSectionProposal(BaseModel):
    section_type: Literal["markdown", "checklist", "asset_collection"] = "markdown"
    title: str = Field(..., min_length=1, max_length=120)
    body_markdown: str = Field(default="", max_length=30000)
    linked_asset_keys: list[str] = Field(default_factory=list, max_length=100)


class GeneratedWorldBiblePageProposal(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    page_type: str = Field(..., min_length=1, max_length=64)
    overview: str | None = Field(default=None, max_length=30000)
    sections: list[GeneratedWorldBibleSectionProposal] = Field(
        default_factory=list,
        max_length=64,
    )
    linked_asset_keys: list[str] = Field(default_factory=list, max_length=100)
    design_rationale: str = Field(default="", max_length=4000)
    review_notes: list[str] = Field(default_factory=list, max_length=20)


class GeneratedWorldBibleNewPageProposal(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    page_type: str = Field(..., min_length=1, max_length=64)
    overview: str | None = Field(default=None, max_length=30000)
    sections: list[GeneratedWorldBibleNewSectionProposal] = Field(
        default_factory=list,
        max_length=64,
    )
    linked_asset_keys: list[str] = Field(default_factory=list, max_length=100)
    design_rationale: str = Field(default="", max_length=4000)
    review_notes: list[str] = Field(default_factory=list, max_length=20)
