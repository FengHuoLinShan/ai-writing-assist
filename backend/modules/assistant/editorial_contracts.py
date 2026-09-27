"""Public request and bounded model output contracts for author editorial review."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReviewSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: UUID
    operation_id: UUID
    scope: Literal["chapter", "range", "book"]
    start_chapter: int | None = Field(default=None, ge=1, le=10000)
    end_chapter: int | None = Field(default=None, ge=1, le=10000)
    dimensions: list[Literal["structure", "scene", "line", "copy", "reader"]] = Field(
        default_factory=lambda: ["structure", "scene", "line", "copy", "reader"],
        min_length=1,
        max_length=5,
    )
    excluded_chapters: list[Annotated[int, Field(ge=1, le=10000)]] = Field(
        default_factory=list, max_length=1000
    )
    expected_brief_version: int = Field(ge=0)

    @model_validator(mode="after")
    def check_range(self):
        if self.scope == "chapter" and (
            self.start_chapter is None
            or self.end_chapter not in {None, self.start_chapter}
        ):
            raise ValueError("单章审读需要准确的章节")
        if self.scope == "range" and (
            self.start_chapter is None
            or self.end_chapter is None
            or self.end_chapter < self.start_chapter
        ):
            raise ValueError("章节区间无效")
        if self.scope == "book" and (self.start_chapter or self.end_chapter):
            raise ValueError("全书审读无需指定章节区间")
        if self.scope == "range" and self.end_chapter - self.start_chapter > 5000:
            raise ValueError("章节区间过长；请使用全书审读")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("检查层次不可重复")
        return self


class IssueDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: UUID
    expected_version: int = Field(ge=0)
    disposition: Literal[
        "prepare", "later", "intentional", "invalid", "modified", "closed"
    ]
    note: str = Field(default="", max_length=2000)


class RecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: UUID
    operation_id: UUID
    expected_version: int = Field(ge=0)


class EditorialPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    excluded_chapters: list[Annotated[int, Field(ge=1, le=10000)]] = Field(
        default_factory=list, max_length=200
    )


class EditorialPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: UUID
    expected_generation: int = Field(ge=0)
    policy: EditorialPolicy


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_index: int = Field(ge=1)
    quote: str = Field(min_length=3, max_length=240)


class ReviewContextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: Literal["world", "outline"]
    source_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=3, max_length=240)


class ReviewDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approach: str = Field(min_length=5, max_length=300)
    affected_chapters: list[Annotated[int, Field(ge=1, le=10000)]] = Field(
        default_factory=list, max_length=20
    )
    tradeoff: str = Field(min_length=3, max_length=300)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["structure", "scene", "line", "copy", "reader"]
    judgment: str = Field(min_length=5, max_length=400)
    reader_impact: str = Field(min_length=5, max_length=400)
    severity: Literal["high", "medium", "low"]
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=4)
    context_evidence: list[ReviewContextEvidence] = Field(
        default_factory=list, max_length=4
    )
    counterevidence: str = Field(default="", max_length=400)
    intent_relation: str = Field(default="", max_length=400)
    intent_quote: str = Field(default="", max_length=240)
    why_now: str = Field(default="", max_length=300)
    unchecked: str = Field(default="", max_length=400)
    directions: list[ReviewDirection] = Field(default_factory=list, max_length=3)


class ReviewPass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(default="", max_length=700)
    reader_state: str = Field(default="", max_length=700)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=8)


class RecheckOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["still", "possibly_improved", "unknown"]
    reason: str = Field(min_length=5, max_length=600)
    new_evidence: list[ReviewEvidence] = Field(default_factory=list, max_length=4)
    unchecked: str = Field(default="", max_length=400)
