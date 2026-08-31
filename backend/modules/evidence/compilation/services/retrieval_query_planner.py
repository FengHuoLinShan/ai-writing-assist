"""Deterministic context query planning with optional bounded LLM expansion."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, replace
from enum import StrEnum
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import (
    AgentPermissionLevel,
    ContextBudget,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.prompt_loader import load_prompt
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.evidence.compilation.contracts import (
    CompileOptions,
    RetrievalClause,
    RetrievalQueryPlan,
)

PLAN_VERSION = "context-query-v1"
LLM_PLAN_VERSION = "context-query-v2-llm"
LLM_QUERY_PLANNER_PROMPT = "rag_query_planner"
LLM_QUERY_PLANNER_STEP = "evidence.query_planner"
LLM_QUERY_PLANNER_TIMEOUT_SECONDS = 30
LLM_QUERY_PLANNER_BUDGET = ContextBudget(
    max_input_chars=8_000,
    max_output_chars=8_000,
    context_limit_tokens=16_000,
    trigger_ratio=0.95,
)
_KNOWN_PURPOSES = frozenset(
    {
        "writing_generation",
        "conflict_review",
        "outline_generation",
        "world_fusion",
        "world_generation",
        "map_atlas",
        "import_scene_activation",
        "reader_context",
        "character_context",
        "story_scene_one_click",
        "story_character_reaction",
        "story_character_card",
        "story_scene_script",
        "manual_search",
        "ask_world",
        "generic_context",
    }
)
_LLM_DISABLED_PURPOSES = frozenset(
    {"reader_context", "character_context", "import_scene_activation", "map_atlas"}
)
_LLM_COMPLEX_PURPOSES = frozenset(
    {"conflict_review", "outline_generation", "world_fusion"}
)
_TEMPORAL_MARKERS = re.compile(r"之前|之后|此前|此后|后来|当时|何时|先后|阶段|变化")
_RELATIONAL_MARKERS = re.compile(
    r"为什么|原因|导致|因此|影响|相比|区别|矛盾|冲突|反证|是否|如何"
)
_NUMBER_RE = re.compile(r"\d+")
_PREFIX_RE = re.compile(
    r"^(?:请|请你|帮我|请根据(?:以下)?资料|根据(?:以下)?资料)?"
    r"(?:生成|检查|分析|审查|判断|提取|补全|续写)\s*",
)


class RetrievalQueryPlanner:
    """Translate structured CompileOptions into at most three RAG clauses."""

    def plan(self, options: CompileOptions) -> RetrievalQueryPlan:
        purpose = (
            options.retrieval_purpose
            if options.retrieval_purpose in _KNOWN_PURPOSES
            else "generic_context"
        )
        query = _normalize_task(options.user_note or options.task)
        visible_until_chapter = (
            options.visible_until_chapter
            if options.visible_until_chapter is not None
            else options.chapter_index
        )
        drafts = self._draft_clauses(options, purpose=purpose, query=query)
        drafts = drafts[:3]
        limits = _allocate_limits(options.top_k, len(drafts))
        clauses = [
            RetrievalClause(**draft, top_k=limits[index])
            for index, draft in enumerate(drafts)
        ]
        payload = {
            "version": PLAN_VERSION,
            "purpose": purpose,
            "clauses": [clause.__dict__ for clause in clauses],
            "visible_until_chapter": visible_until_chapter,
            "visible_until_scene_id": options.visible_until_scene_id,
            "visible_until_offset": options.visible_until_offset,
            "final_top_k": options.top_k,
            "content_mode": options.content_mode,
        }
        return RetrievalQueryPlan(
            version=PLAN_VERSION,
            purpose=purpose,
            clauses=clauses,
            visible_until_chapter=visible_until_chapter,
            visible_until_scene_id=options.visible_until_scene_id,
            visible_until_offset=options.visible_until_offset,
            final_top_k=options.top_k,
            plan_hash=_hash_payload(payload),
        )

    def _draft_clauses(
        self,
        options: CompileOptions,
        *,
        purpose: str,
        query: str,
    ) -> list[dict]:
        if purpose == "manual_search":
            return [self._task_clause(options, query)] if query else []

        strict_character = purpose == "character_context" or (
            options.reveal_mode == "character" and options.scene_id is not None
        )
        clauses: list[dict] = []
        if options.scene_id:
            clauses.append(
                self._clause(
                    options,
                    clause_id="scene_local",
                    query=query or "当前场景",
                    reason_code="current_scene",
                    scene_id=options.scene_id,
                    strict_scene_filter=True,
                    priority=1.35,
                )
            )

        has_relations = bool(
            options.entity_ids or options.character_ids or options.thread_ids
        )
        if has_relations:
            clauses.append(
                self._clause(
                    options,
                    clause_id="relation_focus",
                    query=query or "相关正文证据",
                    reason_code="structured_relation_focus",
                    mode="extraction" if purpose == "world_fusion" else "context",
                    scene_id=options.scene_id if strict_character else None,
                    strict_scene_filter=strict_character,
                    priority=1.15,
                )
            )

        allow_task_fallback = purpose not in {"character_context", "world_fusion"}
        if query and allow_task_fallback:
            clauses.append(self._task_clause(options, query))

        if not clauses and query and allow_task_fallback:
            clauses.append(self._task_clause(options, query))
        return _deduplicate_drafts(clauses)

    @staticmethod
    def _task_clause(options: CompileOptions, query: str) -> dict:
        return RetrievalQueryPlanner._clause(
            options,
            clause_id="task_intent",
            query=query,
            reason_code="task_intent",
            priority=1.0,
        )

    @staticmethod
    def _clause(
        options: CompileOptions,
        *,
        clause_id: str,
        query: str,
        reason_code: str,
        mode: str = "context",
        scene_id: str | None = None,
        strict_scene_filter: bool = False,
        priority: float,
    ) -> dict:
        return {
            "clause_id": clause_id,
            "query_text": query,
            "mode": mode,
            "reason_code": reason_code,
            "entity_ids": options.entity_ids,
            "character_ids": options.character_ids,
            "thread_ids": options.thread_ids,
            "chapter_index": options.chapter_index,
            "scene_id": scene_id,
            "strict_scene_filter": strict_scene_filter,
            "priority": priority,
        }


class QueryPlannerIntent(StrEnum):
    fact = "fact"
    temporal = "temporal"
    causal = "causal"
    comparison = "comparison"
    conflict = "conflict"
    multi_hop = "multi_hop"


class QueryPlannerRole(StrEnum):
    support = "support"
    counter = "counter"


class LLMQueryVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: QueryPlannerRole
    query_text: str = Field(min_length=2, max_length=160)
    grounding_spans: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_grounding_spans(self) -> LLMQueryVariant:
        if len(self.grounding_spans) != len(set(self.grounding_spans)):
            raise ValueError("grounding_spans must be unique")
        return self


class LLMQueryPlannerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: QueryPlannerIntent
    queries: list[LLMQueryVariant] = Field(default_factory=list, max_length=2)
    uncertainties: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_queries(self) -> LLMQueryPlannerOutput:
        normalized = [_normalize_match(item.query_text) for item in self.queries]
        if len(normalized) != len(set(normalized)):
            raise ValueError("queries must be unique")
        return self


@dataclass(frozen=True)
class QueryPlanExpansionOutcome:
    plan: RetrievalQueryPlan
    invoked: bool = False
    expanded: bool = False
    degraded: bool = False
    warning_code: str | None = None
    warning: str | None = None
    latency_ms: float = 0.0


def query_complexity_score(options: CompileOptions) -> int:
    query = _normalize_task(options.task)
    focus_ids = {
        *(options.entity_ids or []),
        *(options.character_ids or []),
        *(options.thread_ids or []),
    }
    return sum(
        (
            len(query) > 40,
            bool(_TEMPORAL_MARKERS.search(query)),
            bool(_RELATIONAL_MARKERS.search(query)),
            len(focus_ids) >= 2,
            options.retrieval_purpose in _LLM_COMPLEX_PURPOSES,
        )
    )


def should_expand_query(
    options: CompileOptions,
    plan: RetrievalQueryPlan,
) -> bool:
    return bool(
        plan.clauses
        and len(plan.clauses) < 3
        and options.reveal_mode in {"author_safe", "author_full"}
        and plan.purpose not in _LLM_DISABLED_PURPOSES
        and query_complexity_score(options) >= 2
    )


async def expand_query_plan(
    db: AsyncSession,
    options: CompileOptions,
    plan: RetrievalQueryPlan,
    *,
    enabled: bool | None = None,
    llm_client: LLMClient | None = None,
) -> QueryPlanExpansionOutcome:
    if enabled is None:
        from core.config import get_settings

        enabled = get_settings().rag_query_planner_enabled
    if not enabled or not should_expand_query(options, plan):
        return QueryPlanExpansionOutcome(plan=plan)

    started = monotonic()
    try:
        if llm_client is not None:
            output = await _generate_query_expansion(llm_client, options, plan)
        else:
            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(
                db,
                options.novel_id,
                timeout_override=LLM_QUERY_PLANNER_TIMEOUT_SECONDS,
            ) as client:
                output = await _generate_query_expansion(client, options, plan)
        _validate_query_grounding(output, options.task)
        expanded_plan = _merge_llm_queries(plan, output)
        return QueryPlanExpansionOutcome(
            plan=expanded_plan,
            invoked=True,
            expanded=expanded_plan != plan,
            latency_ms=(monotonic() - started) * 1000,
        )
    except Exception as exc:
        return QueryPlanExpansionOutcome(
            plan=plan,
            invoked=True,
            degraded=True,
            warning_code="llm_query_planner_failed",
            warning=(
                "LLM 查询规划失败，已使用确定性检索计划: "
                f"{redact_diagnostic(exc, limit=200)}"
            ),
            latency_ms=(monotonic() - started) * 1000,
        )


async def _generate_query_expansion(
    client: LLMClient,
    options: CompileOptions,
    plan: RetrievalQueryPlan,
) -> LLMQueryPlannerOutput:
    payload = {
        "original_query": _normalize_task(options.task),
        "retrieval_purpose": plan.purpose,
        "existing_clause_reasons": [clause.reason_code for clause in plan.clauses],
        "maximum_additional_queries": max(0, 3 - len(plan.clauses)),
    }
    return await run_managed_structured(
        client,
        LLMCallRequest(
            model=client.model_name,
            messages=[
                LLMMessage(role="system", content=load_prompt(LLM_QUERY_PLANNER_PROMPT)),
                LLMMessage(
                    role="user",
                    content=(
                        "<QUERY_PLANNER_INPUT_JSON>\n"
                        + _safe_json_data(payload)
                        + "\n</QUERY_PLANNER_INPUT_JSON>"
                    ),
                ),
            ],
            temperature=0.0,
            max_tokens=8_192,
            response_format={"type": "json_object"},
            extra=_query_planner_request_extra(client),
        ),
        LLMQueryPlannerOutput,
        step_name=LLM_QUERY_PLANNER_STEP,
        max_fix_attempts=0,
        transport_retries=False,
        format_repair_attempts=0,
        permission_level=AgentPermissionLevel.read,
        read_only=True,
        timeout=LLM_QUERY_PLANNER_TIMEOUT_SECONDS,
        context_budget=LLM_QUERY_PLANNER_BUDGET,
    )


def _query_planner_request_extra(client: LLMClient) -> dict[str, object]:
    model = str(client.model_name)
    provider = str(getattr(client, "provider", ""))
    if provider == "deepseek" or model.startswith("deepseek"):
        return {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        }
    return {}


def _validate_query_grounding(
    output: LLMQueryPlannerOutput,
    original_query: str,
) -> None:
    normalized_original = _normalize_match(original_query)
    original_numbers = set(_NUMBER_RE.findall(normalized_original))
    for item in output.queries:
        normalized_query = _normalize_match(item.query_text)
        valid_spans = [
            _normalize_match(span)
            for span in item.grounding_spans
            if _normalize_match(span) in normalized_original
        ]
        if not valid_spans or not any(span in normalized_query for span in valid_spans):
            raise ValueError("derived query lacks an original-query grounding span")
        if set(_NUMBER_RE.findall(normalized_query)) - original_numbers:
            raise ValueError("derived query introduced an unsupported numeric fact")


def _merge_llm_queries(
    plan: RetrievalQueryPlan,
    output: LLMQueryPlannerOutput,
) -> RetrievalQueryPlan:
    remaining = max(0, 3 - len(plan.clauses))
    variants = output.queries[:remaining]
    if not variants:
        return plan
    base = next(
        (
            clause
            for reason in ("task_intent", "structured_relation_focus")
            for clause in plan.clauses
            if clause.reason_code == reason
        ),
        plan.clauses[0],
    )
    clauses = list(plan.clauses)
    for index, variant in enumerate(variants, start=1):
        clauses.append(
            replace(
                base,
                clause_id=f"llm_{variant.role.value}_{index}",
                query_text=variant.query_text,
                reason_code=f"llm_{variant.role.value}_query",
                priority=0.9,
            )
        )
    limits = _allocate_limits(plan.final_top_k, len(clauses))
    clauses = [
        replace(clause, top_k=limits[index]) for index, clause in enumerate(clauses)
    ]
    payload = {
        "version": LLM_PLAN_VERSION,
        "purpose": plan.purpose,
        "clauses": [clause.__dict__ for clause in clauses],
        "visible_until_chapter": plan.visible_until_chapter,
        "visible_until_scene_id": plan.visible_until_scene_id,
        "visible_until_offset": plan.visible_until_offset,
        "final_top_k": plan.final_top_k,
    }
    return replace(
        plan,
        version=LLM_PLAN_VERSION,
        clauses=clauses,
        plan_hash=_hash_payload(payload),
    )


def _safe_json_data(value: dict) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _normalize_match(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", str(value or "")).casefold()
        if character.isalnum() or "\u4e00" <= character <= "\u9fff"
    )


def _normalize_task(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = _PREFIX_RE.sub("", normalized).strip(" ：:，,。")
    if len(normalized) <= 160:
        return normalized
    quoted = re.findall(r"[“\"']([^”\"']{1,40})[”\"']", normalized)
    suffix = " ".join(quoted[:2])
    head = normalized[: max(80, 159 - len(suffix))].rstrip()
    return f"{head} {suffix}".strip()[:160]


def _allocate_limits(final_top_k: int, clause_count: int) -> list[int]:
    if clause_count <= 0:
        return []
    final_top_k = max(1, int(final_top_k))
    if clause_count == 1:
        return [final_top_k]
    total_budget = max(final_top_k * 2, final_top_k + 4)
    base = max(1, math.ceil(total_budget / clause_count))
    limits: list[int] = []
    remaining = total_budget
    for index in range(clause_count):
        remaining_clauses = clause_count - index
        limit = min(base, remaining - (remaining_clauses - 1))
        limits.append(max(1, limit))
        remaining -= limit
    return limits


def _deduplicate_drafts(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (
            item["query_text"],
            item["mode"],
            tuple(item.get("entity_ids") or []),
            tuple(item.get("character_ids") or []),
            tuple(item.get("thread_ids") or []),
            item.get("chapter_index"),
            item.get("scene_id"),
            item.get("strict_scene_filter"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _hash_payload(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
