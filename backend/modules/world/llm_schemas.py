from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    knowledge_expression_boundaries: list[Annotated[str, Field(max_length=1000)]] = Field(
        default_factory=list,
        max_length=32,
        description=(
            "本轮生成中谁可以知道什么、角色只能如何理解或表达的作者边界；"
            "不是正式人物知识或世界事实。"
        ),
    )
    naming_policy: Literal["allowed", "unnamed_placeholder", "uncertain"] = "allowed"
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

    @field_validator("knowledge_expression_boundaries")
    @classmethod
    def _normalize_knowledge_expression_boundaries(
        cls,
        values: list[str],
    ) -> list[str]:
        normalized: list[str] = []
        for value in values:
            boundary = value.strip()
            if boundary and boundary not in normalized:
                normalized.append(boundary)
        return normalized


class GeneratedWorldGenerationDecisionAudit(BaseModel):
    """Narrow semantic audit of a proposal against compiled author decisions."""

    verdict: Literal["pass", "revise"]
    violations: list[str] = Field(default_factory=list, max_length=20)


class GeneratedWorldGenerationConvergenceItem(BaseModel):
    """One author-reviewable choice inside a convergence card."""

    text: str = Field(..., min_length=1, max_length=600)
    suggested_disposition: Literal["include", "open", "discard"] = "open"
    external_disposition: (
        Literal[
            "compatible",
            "repair",
            "candidate",
            "unmapped",
            "exact_duplicate",
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "仅外部回包使用；每项必须标为兼容、最小修复、作者候选、"
            "无法映射或字节级重复之一。"
        ),
    )


class GeneratedWorldGenerationConvergenceCard(BaseModel):
    """A bounded decision surface distilled from explicit source blocks."""

    title: str = Field(..., min_length=1, max_length=160)
    common_ground: list[Annotated[str, Field(max_length=600)]] = Field(
        default_factory=list,
        max_length=8,
    )
    items: list[GeneratedWorldGenerationConvergenceItem] = Field(
        ...,
        min_length=1,
        max_length=12,
    )
    dependencies: list[Annotated[str, Field(max_length=600)]] = Field(
        default_factory=list,
        max_length=8,
    )
    affected_targets: list[
        Literal[
            "current_world_target",
            "world_bible_page",
            "outline",
            "map",
            "writing",
            "other",
        ]
    ] = Field(default_factory=lambda: ["current_world_target"], max_length=6)
    source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        ...,
        min_length=1,
        max_length=256,
    )
    why_now: str = Field(..., min_length=1, max_length=1000)


class GeneratedWorldGenerationConvergenceOutput(BaseModel):
    """Structured, read-only convergence output before any suggestion exists."""

    detail_count_before_grouping: int = Field(..., ge=0, le=10000)
    detail_count_after_deduplication: int = Field(..., ge=0, le=10000)
    retained_detail_count: int = Field(..., ge=0, le=10000)
    decision_cards: list[GeneratedWorldGenerationConvergenceCard] = Field(
        ...,
        min_length=1,
        max_length=7,
    )
    retained_source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = (
        Field(default_factory=list, max_length=256)
    )
    shared_source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=256
    )
    next_boundary: str = Field(..., min_length=1, max_length=1200)


class GeneratedWorldGenerationExplorationTarget(BaseModel):
    """One evidence-backed, adjacent world gap for the author to choose."""

    title: str = Field(..., min_length=1, max_length=160)
    gap: str = Field(..., min_length=1, max_length=800)
    why_it_matters: str = Field(..., min_length=1, max_length=1000)
    author_boundary: str = Field(..., min_length=1, max_length=800)
    reverse_check_focus: str = Field(..., min_length=1, max_length=800)
    source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        ...,
        min_length=1,
        max_length=8,
    )


class GeneratedWorldGenerationExplorationOutput(BaseModel):
    """A bounded one-hop exploration preview; zero targets is a valid stop."""

    targets: list[GeneratedWorldGenerationExplorationTarget] = Field(
        default_factory=list,
        max_length=3,
    )
    stop_reason: str = Field(..., min_length=1, max_length=1000)


class GeneratedWorldSemanticInspectionFinding(BaseModel):
    """One evidence-backed suggestion from a narrow current-page inspection."""

    author_action: Literal["needs_decision", "can_improve"]
    finding_type: Literal[
        "authority_order",
        "open_question",
        "authorization",
        "projection_lag",
        "other",
    ]
    summary: str = Field(..., min_length=1, max_length=600)
    evidence: str = Field(..., min_length=1, max_length=1200)
    location: str = Field(..., min_length=1, max_length=500)
    next_step: str = Field(..., min_length=1, max_length=800)
    source_keys: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        ...,
        min_length=1,
        max_length=8,
    )


class GeneratedWorldSemanticInspectionOutput(BaseModel):
    """Bounded diagnostic output; model findings can never be release blockers."""

    findings: list[GeneratedWorldSemanticInspectionFinding] = Field(
        default_factory=list,
        max_length=8,
    )


class GeneratedAskWorldClaim(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    citation_keys: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(
        ...,
        min_length=1,
        max_length=3,
    )


class GeneratedAskWorldOutput(BaseModel):
    """Evidence-bound answer; every substantive claim carries citations."""

    answer: str = Field(..., min_length=1, max_length=6000)
    claims: list[GeneratedAskWorldClaim] = Field(default_factory=list, max_length=8)
    uncertainty: str = Field(default="", max_length=2000)
    no_answer: bool = False

    @model_validator(mode="after")
    def validate_answer_shape(self) -> GeneratedAskWorldOutput:
        if self.no_answer and self.claims:
            raise ValueError("no-answer output cannot contain factual claims")
        if not self.no_answer and not self.claims:
            raise ValueError("answer output requires at least one cited claim")
        return self


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


class GeneratedWorldBibleSourceRevisionProposal(GeneratedWorldBiblePageProposal):
    """One complete source-page revision caused by an adjacent proposal."""


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
    source_revision: GeneratedWorldBibleSourceRevisionProposal | None = None
