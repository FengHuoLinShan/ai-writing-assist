"""Deterministic, LLM-free query planning for context retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata

from modules.context.contracts import (
    CompileOptions,
    RetrievalClause,
    RetrievalQueryPlan,
)

PLAN_VERSION = "context-query-v1"
_KNOWN_PURPOSES = frozenset(
    {
        "writing_generation",
        "conflict_review",
        "outline_generation",
        "cross_chapter_detection",
        "world_fusion",
        "import_scene_activation",
        "reader_context",
        "character_context",
        "manual_search",
        "generic_context",
    }
)
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
        query = _normalize_task(options.task)
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
