"""Deterministic dataset quality checks and calibration helpers."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from typing import Any

from rapidfuzz.fuzz import ratio

from evals.corpus import CorpusSnapshot
from evals.metrics import cohens_kappa, spearman_rho
from evals.schemas import DatasetCase, DatasetSplit, RiskLevel

_NORMALIZE_QUERY = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


def run_deterministic_qc(
    cases: list[DatasetCase],
    *,
    corpora: dict[str, CorpusSnapshot],
    source_texts: dict[str, str] | None = None,
    near_duplicate_threshold: float = 0.94,
) -> dict[str, Any]:
    errors: dict[str, list[str]] = defaultdict(list)
    warnings: dict[str, list[str]] = defaultdict(list)
    case_ids = Counter(case.case_id for case in cases)

    normalized_queries: dict[str, list[str]] = defaultdict(list)
    source_group_splits: dict[str, set[DatasetSplit]] = defaultdict(set)
    for case in cases:
        if case_ids[case.case_id] > 1:
            errors[case.case_id].append("duplicate_case_id")
        query = _query_text(case)
        if not query:
            errors[case.case_id].append("missing_query")
        else:
            normalized_queries[_duplicate_key(case)].append(case.case_id)
        source_group_splits[case.source_group_id].add(case.split)
        _validate_source_refs(
            case,
            corpora,
            source_texts,
            errors[case.case_id],
        )
        _validate_visibility(case, errors[case.case_id])
        _validate_reference(case, errors[case.case_id], warnings[case.case_id])
        if source_texts is not None:
            _validate_source_semantics(
                case,
                corpora,
                source_texts,
                errors[case.case_id],
                warnings[case.case_id],
            )
        if (
            case.risk_level == RiskLevel.safety_critical
            and case.human_review.status == "unreviewed"
        ):
            errors[case.case_id].append("safety_critical_requires_human_review")

    for ids in normalized_queries.values():
        if len(ids) > 1:
            for case_id in ids:
                errors[case_id].append("exact_duplicate_query")

    for group_id, splits in source_group_splits.items():
        if len(splits) > 1:
            for case in cases:
                if case.source_group_id == group_id:
                    errors[case.case_id].append("source_group_split_leakage")

    near_duplicate_pairs = _near_duplicate_pairs(cases, near_duplicate_threshold)
    for left_id, right_id, score in near_duplicate_pairs:
        warnings[left_id].append(f"near_duplicate:{right_id}:{score:.3f}")
        warnings[right_id].append(f"near_duplicate:{left_id}:{score:.3f}")

    accepted = [case.case_id for case in cases if not errors[case.case_id]]
    return {
        "case_count": len(cases),
        "accepted_count": len(accepted),
        "rejected_count": len(cases) - len(accepted),
        "accepted_case_ids": accepted,
        "errors": {key: value for key, value in errors.items() if value},
        "warnings": {key: value for key, value in warnings.items() if value},
        "near_duplicate_pairs": near_duplicate_pairs,
        "exact_duplicate_count": sum(
            max(0, len(ids) - 1) for ids in normalized_queries.values()
        ),
        "split_leakage_group_count": sum(
            len(splits) > 1 for splits in source_group_splits.values()
        ),
    }


def calibration_report(
    judge_binary: list[str],
    human_binary: list[str],
    judge_scores: list[float],
    human_scores: list[float],
) -> dict[str, float | bool]:
    kappa = cohens_kappa(judge_binary, human_binary)
    rho = spearman_rho(judge_scores, human_scores)
    return {
        "cohens_kappa": kappa,
        "spearman_rho": rho,
        "binary_gate_passed": kappa >= 0.75,
        "ordinal_gate_passed": rho >= 0.70,
        "llm_metrics_blocking": kappa >= 0.75 and rho >= 0.70,
    }


def _validate_source_refs(
    case: DatasetCase,
    corpora: dict[str, CorpusSnapshot],
    source_texts: dict[str, str] | None,
    errors: list[str],
) -> None:
    for ref in [*case.source_refs, *case.hard_negative_refs]:
        corpus = corpora.get(ref.source_alias)
        if corpus is None:
            errors.append(f"unknown_source_alias:{ref.source_alias}")
            continue
        chapter = next(
            (item for item in corpus.chapters if item.chapter_index == ref.chapter_index),
            None,
        )
        if chapter is None:
            errors.append(f"missing_chapter:{ref.chapter_index}")
            continue
        if chapter.content_hash != ref.content_hash:
            errors.append(f"content_hash_mismatch:{ref.chapter_index}")
        if chapter.source_group_id != ref.source_group_id:
            errors.append(f"source_group_mismatch:{ref.chapter_index}")
        if ref.start_offset is None:
            if ref.range_hash is not None:
                errors.append(f"range_hash_without_offsets:{ref.chapter_index}")
            continue
        chapter_length = chapter.end_offset - chapter.start_offset
        if ref.end_offset is None or ref.end_offset > chapter_length:
            errors.append(f"range_out_of_bounds:{ref.chapter_index}")
            continue
        if ref.range_hash is None:
            errors.append(f"range_hash_missing:{ref.chapter_index}")
            continue
        if source_texts is None:
            errors.append(f"source_text_missing:{ref.source_alias}")
            continue
        source_text = source_texts.get(ref.source_alias)
        if source_text is None:
            errors.append(f"source_text_missing:{ref.source_alias}")
            continue
        chapter_text = source_text[chapter.start_offset : chapter.end_offset]
        range_text = chapter_text[ref.start_offset : ref.end_offset]
        actual_range_hash = hashlib.sha256(range_text.encode("utf-8")).hexdigest()
        if actual_range_hash != ref.range_hash:
            errors.append(f"range_hash_mismatch:{ref.chapter_index}")


def _validate_visibility(case: DatasetCase, errors: list[str]) -> None:
    cutoff = case.visibility.visible_until_chapter
    if case.scenario == "visibility_cutoff" and cutoff is None:
        errors.append("missing_visibility_cutoff")
        return
    if cutoff is None:
        return
    if any(ref.chapter_index > cutoff for ref in case.source_refs):
        errors.append("future_evidence_leakage")


def _validate_reference(
    case: DatasetCase,
    errors: list[str],
    warnings: list[str],
) -> None:
    no_answer = bool(case.reference.get("no_answer"))
    if no_answer and case.source_refs:
        errors.append("no_answer_has_positive_source_refs")
    if not no_answer and not case.reference:
        errors.append("missing_reference")
    if not no_answer and not case.source_refs:
        warnings.append("answerable_case_without_source_refs")
    positive_keys = {
        (ref.source_alias, ref.chapter_index, ref.start_offset, ref.end_offset)
        for ref in case.source_refs
    }
    negative_keys = {
        (ref.source_alias, ref.chapter_index, ref.start_offset, ref.end_offset)
        for ref in case.hard_negative_refs
    }
    if positive_keys & negative_keys:
        errors.append("hard_negative_overlaps_positive")


def _near_duplicate_pairs(
    cases: list[DatasetCase],
    threshold: float,
) -> list[tuple[str, str, float]]:
    pairs: list[tuple[str, str, float]] = []
    for index, left in enumerate(cases):
        left_query = _normalize(_query_text(left))
        if not left_query:
            continue
        for right in cases[index + 1 :]:
            if left.source_group_id != right.source_group_id:
                continue
            right_query = _normalize(_query_text(right))
            score = ratio(left_query, right_query) / 100
            if score >= threshold and left_query != right_query:
                pairs.append((left.case_id, right.case_id, score))
    return pairs


def _query_text(case: DatasetCase) -> str:
    return str(case.input.get("query") or case.input.get("text") or "").strip()


def _duplicate_key(case: DatasetCase) -> str:
    normalized_input = _normalize(_query_text(case))
    if case.suite.value == "rag":
        return f"rag:{normalized_input}"
    semantic_identity = {
        "suite": case.suite.value,
        "scenario": case.scenario,
        "input": case.input,
        "reference": case.reference,
    }
    return json.dumps(semantic_identity, ensure_ascii=False, sort_keys=True)


def _normalize(value: str) -> str:
    return _NORMALIZE_QUERY.sub("", value.casefold())


def _validate_source_semantics(
    case: DatasetCase,
    corpora: dict[str, CorpusSnapshot],
    source_texts: dict[str, str],
    errors: list[str],
    warnings: list[str],
) -> None:
    query = _normalize(_query_text(case))
    positive_text = _referenced_text(case.source_refs, corpora, source_texts)
    negative_text = _referenced_text(case.hard_negative_refs, corpora, source_texts)
    if len(query) >= 12 and query in _normalize(positive_text):
        warnings.append("query_copies_source_text")
    answer = _normalize(str(case.reference.get("answer") or ""))
    if answer and len(answer) >= 2 and case.source_refs:
        if answer not in _normalize(positive_text):
            warnings.append("reference_answer_not_verbatim")
    if answer and answer in _normalize(negative_text):
        errors.append("hard_negative_contains_reference_answer")


def _referenced_text(
    refs: list[Any],
    corpora: dict[str, CorpusSnapshot],
    source_texts: dict[str, str],
) -> str:
    parts: list[str] = []
    for ref in refs:
        corpus = corpora.get(ref.source_alias)
        source_text = source_texts.get(ref.source_alias)
        if corpus is None or source_text is None:
            continue
        chapter = next(
            (item for item in corpus.chapters if item.chapter_index == ref.chapter_index),
            None,
        )
        if chapter is None:
            continue
        chapter_text = source_text[chapter.start_offset : chapter.end_offset]
        start = ref.start_offset if ref.start_offset is not None else 0
        end = ref.end_offset if ref.end_offset is not None else len(chapter_text)
        parts.append(chapter_text[start:end])
    return "\n".join(parts)
