"""Comparative task-direct vs deterministic context planner evaluation."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from evals.metrics import precision_at_k, recall_at_k
from evals.schemas import DatasetCase, EvalSuite
from modules.context.contracts import (
    CompileOptions,
    RetrievalClause,
    RetrievalQueryPlan,
    StructureContextBundle,
)
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader


class TaskDirectPlanner:
    """Historical one-query strategy with the loader's current safety rehydrate."""

    def plan(self, options: CompileOptions) -> RetrievalQueryPlan:
        query = str(options.task or "")
        clause = RetrievalClause(
            clause_id="task_direct",
            query_text=query,
            mode="context",
            reason_code="task_direct",
            entity_ids=options.entity_ids,
            character_ids=options.character_ids,
            thread_ids=options.thread_ids,
            chapter_index=options.chapter_index,
            scene_id=(
                options.scene_id
                if options.reveal_mode == "character" and options.scene_id
                else None
            ),
            strict_scene_filter=bool(
                options.reveal_mode == "character" and options.scene_id
            ),
            priority=1.0,
            top_k=max(1, options.top_k),
        )
        payload = {
            "version": "task-direct-v1",
            "query": query,
            "content_mode": options.content_mode,
            "visibility": [
                options.visible_until_chapter,
                options.visible_until_scene_id,
                options.visible_until_offset,
            ],
        }
        return RetrievalQueryPlan(
            version="task-direct-v1",
            purpose="task_direct",
            clauses=[clause] if query else [],
            visible_until_chapter=options.visible_until_chapter,
            visible_until_scene_id=options.visible_until_scene_id,
            visible_until_offset=options.visible_until_offset,
            final_top_k=options.top_k,
            plan_hash=hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
        )


async def evaluate_context_planner_cases(
    db: AsyncSession,
    novel_id: str,
    cases: list[DatasetCase],
    *,
    dataset_version: str,
    sut_profile: str,
) -> dict[str, Any]:
    started_at = datetime.now(UTC)

    async def discard_trace(*_args: Any, **_kwargs: Any) -> None:
        return None

    strategies = {
        "task-direct": RagChunksLoader(
            planner=TaskDirectPlanner(), trace_recorder=discard_trace
        ),
        "planner-v1": RagChunksLoader(trace_recorder=discard_trace),
    }
    results: dict[str, list[dict[str, Any]]] = {name: [] for name in strategies}
    projection_unavailable: list[dict[str, str]] = []
    rag_cases = [case for case in cases if case.suite == EvalSuite.rag]
    for case in rag_cases:
        options, projection_error = _project_options(case, novel_id=novel_id)
        if options is None:
            projection_unavailable.append(
                {
                    "case_id": case.case_id,
                    "purpose": _purpose(case),
                    "reason": projection_error or "unsupported_projection",
                }
            )
            continue
        prefix = _logical_context_prefix(set(case.reference.get("context_ids") or []))
        relevant = set(case.reference.get("context_ids") or [])
        for strategy, loader in strategies.items():
            bundle = StructureContextBundle(
                novel_id=novel_id,
                task=options.task,
                scope=options.scope,
                chapter_index=options.chapter_index,
            )
            started = time.perf_counter()
            await loader.load(db, options, bundle)
            elapsed_ms = (time.perf_counter() - started) * 1000
            retrieved = list(
                dict.fromkeys(
                    _logical_chunk_id(chunk, prefix) for chunk in bundle.rag_chunks
                )
            )
            no_answer = bool(case.reference.get("no_answer"))
            cutoff = case.visibility.visible_until_chapter
            leakage = sum(
                cutoff is not None and int(chunk.get("chapter_index") or 0) > int(cutoff)
                for chunk in bundle.rag_chunks
            )
            reasons = [
                reason
                for chunk in bundle.rag_chunks
                for reason in chunk.get("activation_reasons", [])
            ]
            results[strategy].append(
                {
                    "case_id": case.case_id,
                    "purpose": options.retrieval_purpose,
                    "no_answer": no_answer,
                    "retrieved_ids": retrieved,
                    "p_at_5": precision_at_k(retrieved, relevant, 5),
                    "r_at_10": recall_at_k(retrieved, relevant, 10),
                    "visibility_leakage": leakage,
                    "reason_coverage": (
                        sum(
                            bool(chunk.get("activation_reasons"))
                            for chunk in bundle.rag_chunks
                        )
                        / len(bundle.rag_chunks)
                        if bundle.rag_chunks
                        else 1.0
                    ),
                    "safe_empty_classified": bool(
                        bundle.rag_chunks
                        or bundle.retrieval_trace.get("safe_empty_reason")
                    ),
                    "safe_empty_reason": bundle.retrieval_trace.get("safe_empty_reason"),
                    "retrieve_call_count": len(
                        bundle.retrieval_trace.get("clause_summaries") or []
                    ),
                    "reason_codes": list(dict.fromkeys(reasons)),
                    "latency_ms": elapsed_ms,
                }
            )

    summaries = {strategy: _summarize(items) for strategy, items in results.items()}
    direct = summaries["task-direct"]
    planner = summaries["planner-v1"]
    relaxed_precision_strata = _precision_strata_within_tolerance(
        direct,
        planner,
        tolerance=0.01,
    )
    gates = {
        "visibility_leakage_zero": planner["visibility_leakage_count"] == 0,
        "no_answer_fp_not_worse": (
            planner["no_answer_false_positive_rate"]
            <= direct["no_answer_false_positive_rate"]
        ),
        "hydrated_p_at_5_not_worse": planner["p_at_5"] >= direct["p_at_5"],
        "r_at_10_drop_within_5pp": planner["r_at_10"] >= direct["r_at_10"] - 0.05,
        "reason_coverage_complete": planner["reason_coverage"] == 1.0,
        "empty_reason_classification_complete": (
            planner["safe_empty_classification_rate"] == 1.0
        ),
        "latency_ratio_within_1_8": (
            direct["latency_p95_ms"] == 0
            or planner["latency_p95_ms"] / direct["latency_p95_ms"] <= 1.8
        ),
        "precision_strata_within_relaxed_1pp_tolerance": relaxed_precision_strata,
    }
    strict_targets = {
        "no_answer_false_positive_rate_lte_0_20": (
            planner["no_answer_false_positive_rate"] <= 0.20
        ),
        "precision_first_strata_gain_20pct_or_p_at_5_0_80": (
            _strict_precision_strata_target(direct, planner)
        ),
    }
    unavailable_by_purpose: dict[str, int] = {}
    for item in projection_unavailable:
        purpose = item["purpose"]
        unavailable_by_purpose[purpose] = unavailable_by_purpose.get(purpose, 0) + 1
    return {
        "schema_version": "context-planner-eval-v1",
        "dataset_version": dataset_version,
        "sut_profile": sut_profile,
        "novel_id": novel_id,
        "case_count": len(rag_cases),
        "evaluated_case_count": len(results["planner-v1"]),
        "projection_unavailable_count": len(projection_unavailable),
        "projection_unavailable_by_purpose": unavailable_by_purpose,
        "strategies": summaries,
        "delta": {
            "p_at_5": planner["p_at_5"] - direct["p_at_5"],
            "r_at_10": planner["r_at_10"] - direct["r_at_10"],
            "no_answer_false_positive_rate": (
                planner["no_answer_false_positive_rate"]
                - direct["no_answer_false_positive_rate"]
            ),
            "latency_p95_ratio": (
                planner["latency_p95_ms"] / direct["latency_p95_ms"]
                if direct["latency_p95_ms"]
                else None
            ),
        },
        "gates": gates,
        "strict_targets": strict_targets,
        "passed": all(gates.values()),
        "acceptance_status": (
            "pass_with_known_quality_and_dataset_limits"
            if all(gates.values())
            and (projection_unavailable or not all(strict_targets.values()))
            else ("passed" if all(gates.values()) else "failed")
        ),
        "notes": [
            "This result measures context planning, fusion and source rehydrate.",
            "It does not replace the official direct RAG baseline.",
            "Missing structured fusion anchors are reported as projection "
            "unavailable, not as zero-score retrieval.",
            "Strict quality targets are reported separately and are not relaxed "
            "into a claim that RAG quality is satisfactory.",
        ],
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "case_results": results,
        "projection_unavailable": projection_unavailable,
    }


def _project_options(
    case: DatasetCase,
    *,
    novel_id: str,
) -> tuple[CompileOptions | None, str | None]:
    purpose = _purpose(case)
    entity_ids = _string_list(case.input.get("entity_ids"))
    character_ids = _string_list(case.input.get("character_ids"))
    thread_ids = _string_list(case.input.get("thread_ids"))
    if purpose == "world_fusion" and not (entity_ids or character_ids or thread_ids):
        return None, "world_fusion_requires_structured_relation_anchor"
    reveal_mode = (
        "character"
        if case.visibility.mode == "character"
        else ("reader" if case.visibility.mode == "reader" else "author_safe")
    )
    return CompileOptions(
        novel_id=novel_id,
        task=str(case.input.get("query") or ""),
        scope="chapter",
        consumer_action=f"eval.{purpose}",
        retrieval_purpose=purpose,
        reveal_mode=reveal_mode,
        viewpoint_character_id=case.visibility.viewpoint_character_id,
        visible_until_chapter=case.visibility.visible_until_chapter,
        scene_id=(str(case.input["scene_id"]) if case.input.get("scene_id") else None),
        chapter_index=(
            int(case.input["chapter_index"])
            if case.input.get("chapter_index") is not None
            else None
        ),
        entity_ids=entity_ids or None,
        character_ids=character_ids or None,
        thread_ids=thread_ids or None,
        content_mode=str(case.input.get("content_mode") or "canonical"),
        top_k=10,
    ), None


def _purpose(case: DatasetCase) -> str:
    if case.visibility.mode == "character":
        return "character_context"
    if case.visibility.mode == "reader":
        return "reader_context"
    persona = str(case.rubric.get("persona") or "")
    return {
        "writing_conflict": "conflict_review",
        "evidence_fusion": "world_fusion",
        "outline_generation": "outline_generation",
    }.get(persona, "writing_generation")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _logical_context_prefix(relevant_ids: set[str]) -> str | None:
    prefixes = {
        value.rsplit(":chapter:", 1)[0] for value in relevant_ids if ":chapter:" in value
    }
    return next(iter(prefixes)) if len(prefixes) == 1 else None


def _logical_chunk_id(chunk: dict[str, Any], prefix: str | None) -> str:
    meta = dict(chunk.get("meta") or {})
    if meta.get("logical_context_id"):
        return str(meta["logical_context_id"])
    if prefix and chunk.get("chapter_index") is not None:
        return f"{prefix}:chapter:{chunk['chapter_index']}"
    return str(chunk.get("id") or "")


def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [item for item in items if not item["no_answer"]]
    no_answer = [item for item in items if item["no_answer"]]
    latencies = sorted(float(item["latency_ms"]) for item in items)
    by_purpose: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_purpose.setdefault(item["purpose"], []).append(item)
    return {
        "p_at_5": _mean([item["p_at_5"] for item in answerable]),
        "r_at_10": _mean([item["r_at_10"] for item in answerable]),
        "no_answer_false_positive_rate": _mean(
            [float(bool(item["retrieved_ids"])) for item in no_answer]
        ),
        "visibility_leakage_count": sum(item["visibility_leakage"] for item in items),
        "reason_coverage": _mean([item["reason_coverage"] for item in items]),
        "safe_empty_classification_rate": _mean(
            [float(item["safe_empty_classified"]) for item in items]
        ),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "mean_retrieve_call_count": _mean(
            [item["retrieve_call_count"] for item in items]
        ),
        "by_purpose": {
            purpose: {
                "case_count": len(values),
                "p_at_5": _mean(
                    [item["p_at_5"] for item in values if not item["no_answer"]]
                ),
                "r_at_10": _mean(
                    [item["r_at_10"] for item in values if not item["no_answer"]]
                ),
            }
            for purpose, values in sorted(by_purpose.items())
        },
    }


def _precision_strata_within_tolerance(
    direct: dict[str, Any],
    planner: dict[str, Any],
    *,
    tolerance: float,
) -> bool:
    names = {"writing_generation", "conflict_review"}
    direct_by = direct["by_purpose"]
    planner_by = planner["by_purpose"]
    present = names & set(direct_by) & set(planner_by)
    return bool(present) and all(
        planner_by[name]["p_at_5"] >= direct_by[name]["p_at_5"] - tolerance
        for name in present
    )


def _strict_precision_strata_target(
    direct: dict[str, Any],
    planner: dict[str, Any],
) -> bool:
    names = {"writing_generation", "conflict_review", "world_fusion"}
    direct_by = direct["by_purpose"]
    planner_by = planner["by_purpose"]
    if not names <= set(direct_by) or not names <= set(planner_by):
        return False
    return all(
        planner_by[name]["p_at_5"] >= 0.80
        or planner_by[name]["p_at_5"] >= direct_by[name]["p_at_5"] * 1.20
        for name in names
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, int(len(values) * percentile) - 1))
    return values[index]
