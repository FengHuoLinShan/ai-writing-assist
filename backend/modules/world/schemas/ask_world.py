"""Ask World 问答 schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AskWorldQuestionRequest(BaseModel):
    novel_id: str
    question: str = Field(..., min_length=2, max_length=2000)
    context_confirmation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class AskWorldCitation(BaseModel):
    citation_key: str = Field(..., min_length=1, max_length=160)
    kind: Literal["world_bible_page", "world_object", "manuscript"]
    title: str = Field(..., min_length=1, max_length=255)
    snippet: str = Field(default="", max_length=2000)
    source_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    source_version: int | None = Field(default=None, ge=1)
    page_id: str | None = None
    chapter_index: int | None = Field(default=None, ge=1)
    source_ref: dict[str, Any] | None = None
    target_ref: dict[str, Any] | None = None
    index_fresh: bool = True


class AskWorldClaim(BaseModel):
    text: str = Field(..., min_length=1, max_length=1200)
    citation_keys: list[str] = Field(..., min_length=1, max_length=3)


class AskWorldEvidenceTrace(BaseModel):
    included_titles: list[str] = Field(default_factory=list, max_length=10)
    excluded_count: int = Field(default=0, ge=0)
    truncated_titles: list[str] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=20)
    degraded: bool = False
    checks_run: list[str] = Field(default_factory=list, max_length=10)
    not_run: list[str] = Field(default_factory=list, max_length=10)


class AskWorldResponse(BaseModel):
    question: str
    answer: str
    claims: list[AskWorldClaim] = Field(default_factory=list, max_length=8)
    uncertainty: str = Field(default="", max_length=2000)
    no_answer: bool = False
    citations: list[AskWorldCitation] = Field(default_factory=list, max_length=10)
    response_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    evidence_trace: AskWorldEvidenceTrace
    model: str = ""
    provider: str = ""
    context_snapshot_id: str | None = None
    knowledge_review: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_citations(self) -> AskWorldResponse:
        known = {item.citation_key for item in self.citations}
        if any(key not in known for claim in self.claims for key in claim.citation_keys):
            raise ValueError("claim references an unknown citation")
        if self.no_answer and self.claims:
            raise ValueError("no-answer response cannot contain claims")
        return self


class AskWorldSaveRequest(BaseModel):
    novel_id: str
    question: str = Field(..., min_length=2, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=6000)
    claims: list[AskWorldClaim] = Field(..., min_length=1, max_length=8)
    uncertainty: str = Field(default="", max_length=2000)
    citations: list[AskWorldCitation] = Field(..., min_length=1, max_length=10)
    response_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_citations(self) -> AskWorldSaveRequest:
        known = {item.citation_key for item in self.citations}
        if len(known) != len(self.citations):
            raise ValueError("citation keys must be unique")
        if any(key not in known for claim in self.claims for key in claim.citation_keys):
            raise ValueError("claim references an unknown citation")
        return self


class AskWorldCitationOpenRequest(BaseModel):
    novel_id: str
    citation: AskWorldCitation


class AskWorldCitationOpenResponse(BaseModel):
    status: Literal["current", "stale", "unavailable"]
    kind: Literal["world_bible_page", "world_object", "manuscript"]
    title: str
    text: str = ""
    source_hash: str | None = None
    page_id: str | None = None
    chapter_index: int | None = None
    warnings: list[str] = Field(default_factory=list, max_length=10)
