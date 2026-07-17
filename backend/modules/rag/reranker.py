"""Mode-aware, evidence-oriented LLM reranking for RAG candidates."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from infrastructure.llm.agent_step_harness import (
    AgentPermissionLevel,
    ContextBudget,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

RERANKER_STEP_NAME = "rag.reranker.generate"
RERANKER_PROMPT_NAME = "rag_reranker"
RERANKER_TOTAL_TIMEOUT_SECONDS = 1800
RERANKER_UNSUPPORTED_CONFIDENCE = 0.8
# Search mode may keep genuinely useful thematic context, but very low-value
# topical mentions are retrieval noise rather than evidence. Direct,
# supporting, and counterevidence decisions are never removed by this floor.
RERANKER_TOPICAL_MIN_SCORE = 0.2
RERANKER_CONTEXT_BUDGET = ContextBudget(
    max_input_chars=4_000_000,
    max_output_chars=1_000_000,
    context_limit_tokens=1_000_000,
    trigger_ratio=0.95,
)


class RerankerSupportStatus(StrEnum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    uncertain = "uncertain"


class RerankerEvidenceRole(StrEnum):
    direct = "direct"
    supporting = "supporting"
    counterevidence = "counterevidence"
    topical_only = "topical_only"
    irrelevant = "irrelevant"


RERANKER_ROLE_PRIORITY = {
    RerankerEvidenceRole.direct: 0,
    RerankerEvidenceRole.counterevidence: 0,
    RerankerEvidenceRole.supporting: 1,
    RerankerEvidenceRole.topical_only: 2,
}


class RerankerCandidateDecision(BaseModel):
    """One evidence-value judgment, referenced only by a server short key."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(
        min_length=1,
        pattern=r"^candidate-[0-9]{3}$",
    )
    evidence_role: RerankerEvidenceRole
    relevance_score: float = Field(strict=True, ge=0.0, le=1.0)
    basis: str = Field(min_length=1)
    uncertain: bool = False

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _reject_bool_score(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("relevance_score must be a JSON number")
        if isinstance(value, int | float) and not math.isfinite(float(value)):
            raise ValueError("relevance_score must be finite")
        return value


class RerankerOutput(BaseModel):
    """Strict P21 output for support, ranking, and abstention decisions."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    support_status: RerankerSupportStatus
    confidence: float = Field(strict=True, ge=0.0, le=1.0)
    basis: str = Field(min_length=1)
    ranked_candidates: list[RerankerCandidateDecision]
    uncertainties: list[str] = Field(default_factory=list)

    @field_validator("confidence", mode="before")
    @classmethod
    def _reject_bool_confidence(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("confidence must be a JSON number")
        if isinstance(value, int | float) and not math.isfinite(float(value)):
            raise ValueError("confidence must be finite")
        return value

    @model_validator(mode="after")
    def _validate_semantics(self) -> RerankerOutput:
        refs = [item.candidate_ref for item in self.ranked_candidates]
        if len(refs) != len(set(refs)):
            raise ValueError("ranked_candidates must not repeat candidate_ref")

        useful_roles = {
            RerankerEvidenceRole.direct,
            RerankerEvidenceRole.supporting,
            RerankerEvidenceRole.counterevidence,
            RerankerEvidenceRole.topical_only,
        }
        if self.support_status in {
            RerankerSupportStatus.supported,
            RerankerSupportStatus.partially_supported,
        } and not any(
            item.evidence_role in useful_roles for item in self.ranked_candidates
        ):
            raise ValueError("supported output requires at least one useful candidate")
        if self.support_status == RerankerSupportStatus.unsupported and any(
            item.evidence_role
            in {
                RerankerEvidenceRole.direct,
                RerankerEvidenceRole.supporting,
                RerankerEvidenceRole.counterevidence,
            }
            for item in self.ranked_candidates
        ):
            raise ValueError("unsupported output contradicts evidence roles")
        return self


@dataclass(frozen=True)
class RerankOutcome:
    """Internal reranker result without changing the public RAG bundle shape."""

    chunks: list[tuple[Any, float]]
    support_status: RerankerSupportStatus
    degraded: bool = False
    warning: str | None = None


def _safe_json_data(value: dict[str, Any]) -> str:
    """Serialize untrusted data without allowing it to close the data fence."""

    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _candidate_payload(candidate: dict[str, Any], *, index: int) -> dict[str, Any]:
    return {
        "candidate_ref": f"candidate-{index + 1:03d}",
        "full_text": str(candidate.get("text") or ""),
        "chapter_index": candidate.get("chapter_index"),
        "chunk_index": candidate.get("chunk_index"),
        "source_type": candidate.get("source_type"),
        "scene_mapped": bool(candidate.get("scene_id")),
        "original_rank": index + 1,
        "original_score": candidate.get("original_score"),
    }


def _build_user_prompt(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    retrieval_mode: str,
    retrieval_purpose: str | None,
) -> tuple[str, list[str]]:
    candidate_payloads = [
        _candidate_payload(candidate, index=index)
        for index, candidate in enumerate(candidates)
    ]
    refs = [item["candidate_ref"] for item in candidate_payloads]
    payload = {
        "query": query,
        "retrieval_mode": retrieval_mode,
        "retrieval_purpose": retrieval_purpose or "unspecified",
        "candidates": candidate_payloads,
    }
    return (
        "<RAG_RERANK_INPUT_JSON>\n"
        f"{_safe_json_data(payload)}\n"
        "</RAG_RERANK_INPUT_JSON>\n\n"
        "比较完整候选集合，输出整体支持状态，并按证据价值列出所有值得保留的 "
        "candidate_ref；无实际价值的候选可以省略。",
        refs,
    )


def _validate_candidate_references(output: RerankerOutput, refs: list[str]) -> None:
    actual = [item.candidate_ref for item in output.ranked_candidates]
    unknown = sorted(set(actual) - set(refs))
    if unknown:
        raise ValueError(
            "reranker returned unknown candidate_ref values: "
            f"unknown={unknown}"
        )


async def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    retrieval_mode: str = "search",
    retrieval_purpose: str | None = None,
    llm_client: LLMClient | None = None,
    model: str | None = None,
) -> RerankerOutput:
    """Judge evidence value for the complete deterministic candidate pool."""

    if not candidates:
        return RerankerOutput(
            support_status=RerankerSupportStatus.unsupported,
            confidence=1.0,
            basis="没有候选片段可供判断。",
            ranked_candidates=[],
            uncertainties=[],
        )
    if llm_client is None:
        raise ValueError("rerank requires a project-scoped llm_client")

    user_prompt, refs = _build_user_prompt(
        query,
        candidates,
        retrieval_mode=retrieval_mode,
        retrieval_purpose=retrieval_purpose,
    )
    output = await run_managed_structured(
        llm_client,
        LLMCallRequest(
            model=model or llm_client.model_name,
            messages=[
                LLMMessage(role="system", content=load_prompt(RERANKER_PROMPT_NAME)),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        ),
        RerankerOutput,
        step_name=RERANKER_STEP_NAME,
        max_fix_attempts=2,
        format_repair_attempts=1,
        permission_level=AgentPermissionLevel.read,
        read_only=True,
        timeout=RERANKER_TOTAL_TIMEOUT_SECONDS,
        context_budget=RERANKER_CONTEXT_BUDGET,
    )
    _validate_candidate_references(output, refs)
    return output


def _retained_roles(retrieval_mode: str) -> set[RerankerEvidenceRole]:
    roles = {
        RerankerEvidenceRole.direct,
        RerankerEvidenceRole.supporting,
        RerankerEvidenceRole.counterevidence,
    }
    if retrieval_mode in {"search", "context"}:
        roles.add(RerankerEvidenceRole.topical_only)
    return roles


async def rerank_results(
    query: str,
    scored_chunks: list[tuple[Any, float]],
    *,
    top_k: int = 12,
    retrieval_mode: str = "search",
    retrieval_purpose: str | None = None,
    llm_client: LLMClient | None = None,
    model: str | None = None,
) -> RerankOutcome:
    """Rerank candidates, filter non-evidence, and support explicit abstention."""

    if len(scored_chunks) <= top_k:
        return RerankOutcome(
            chunks=scored_chunks,
            support_status=RerankerSupportStatus.uncertain,
        )

    candidates = [
        {
            "text": chunk.text,
            "chapter_index": getattr(chunk, "chapter_index", None),
            "chunk_index": getattr(chunk, "chunk_index", None),
            "source_type": getattr(chunk, "source_type", None),
            "scene_id": getattr(chunk, "scene_id", None),
            "original_score": score,
        }
        for chunk, score in scored_chunks
    ]
    output = await rerank(
        query,
        candidates,
        retrieval_mode=retrieval_mode,
        retrieval_purpose=retrieval_purpose,
        llm_client=llm_client,
        model=model,
    )

    if output.support_status == RerankerSupportStatus.uncertain:
        return RerankOutcome(
            chunks=scored_chunks[:top_k],
            support_status=output.support_status,
            degraded=True,
            warning="LLM 重排序无法可靠判断，已保留原始排序",
        )
    if output.support_status == RerankerSupportStatus.unsupported:
        if output.confidence >= RERANKER_UNSUPPORTED_CONFIDENCE:
            return RerankOutcome(
                chunks=[],
                support_status=output.support_status,
                warning="当前候选不足以支持检索意图",
            )
        return RerankOutcome(
            chunks=scored_chunks[:top_k],
            support_status=output.support_status,
            degraded=True,
            warning="LLM 对无证据判断置信不足，已保留原始排序",
        )

    by_ref = {
        f"candidate-{index + 1:03d}": (chunk, original_score, index)
        for index, (chunk, original_score) in enumerate(scored_chunks)
    }
    retained: list[tuple[Any, float, float, int, int, RerankerEvidenceRole]] = []
    allowed_roles = _retained_roles(retrieval_mode)
    for decision_rank, decision in enumerate(output.ranked_candidates):
        if decision.evidence_role not in allowed_roles:
            continue
        if (
            decision.evidence_role == RerankerEvidenceRole.topical_only
            and decision.relevance_score < RERANKER_TOPICAL_MIN_SCORE
        ):
            continue
        chunk, original_score, original_index = by_ref[decision.candidate_ref]
        retained.append(
            (
                chunk,
                decision.relevance_score,
                original_score,
                original_index,
                decision_rank,
                decision.evidence_role,
            )
        )

    if not retained:
        raise ValueError("supported reranker output retained no usable evidence")

    # Evidence role is the primary tier: a high-scoring topical mention must
    # never displace direct evidence merely because both received similar
    # confidence. Within a role, preserve the model score and its explicit
    # ranking before falling back to deterministic retrieval signals.
    retained.sort(
        key=lambda item: (
            RERANKER_ROLE_PRIORITY[item[5]],
            -item[1],
            item[4],
            -item[2],
            item[3],
        )
    )
    return RerankOutcome(
        chunks=[(chunk, score) for chunk, score, *_ in retained[:top_k]],
        support_status=output.support_status,
    )
