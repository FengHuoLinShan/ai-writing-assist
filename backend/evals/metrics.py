"""Deterministic semantic-evaluation metrics used by blocking gates."""

from __future__ import annotations

import math
from collections.abc import Sequence


def precision_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    selected = list(retrieved_ids[:k])
    if not selected:
        return 0.0
    return sum(item in relevant_ids for item in selected) / len(selected)


def recall_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    if not relevant_ids:
        return 1.0 if not retrieved_ids else 0.0
    return len(set(retrieved_ids[:k]) & relevant_ids) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: set[str]) -> float:
    for rank, item in enumerate(retrieved_ids, start=1):
        if item in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    retrieved_ids: Sequence[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    gains = [1.0 if item in relevant_ids else 0.0 for item in retrieved_ids[:k]]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_count = min(len(relevant_ids), k)
    if ideal_count == 0:
        return 1.0 if not retrieved_ids else 0.0
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal


def boundary_counts(
    predicted: Sequence[int],
    reference: Sequence[int],
    *,
    tolerance: int = 150,
) -> tuple[int, int, int]:
    remaining = list(reference)
    true_positive = 0
    for value in predicted:
        candidates = [item for item in remaining if abs(item - value) <= tolerance]
        if not candidates:
            continue
        matched = min(candidates, key=lambda item: abs(item - value))
        remaining.remove(matched)
        true_positive += 1
    return true_positive, len(predicted) - true_positive, len(remaining)


def precision_recall_f1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def cohens_kappa(left: Sequence[str], right: Sequence[str]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("label sequences must have the same non-zero length")
    labels = set(left) | set(right)
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    expected = sum(
        (left.count(label) / len(left)) * (right.count(label) / len(right))
        for label in labels
    )
    if expected == 1.0:
        return 1.0
    return (observed - expected) / (1.0 - expected)


def spearman_rho(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("score sequences must have the same length >= 2")
    left_ranks = _ranks(left)
    right_ranks = _ranks(right)
    mean_left = sum(left_ranks) / len(left_ranks)
    mean_right = sum(right_ranks) / len(right_ranks)
    numerator = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left_ranks, right_ranks)
    )
    denominator = math.sqrt(
        sum((a - mean_left) ** 2 for a in left_ranks)
        * sum((b - mean_right) ** 2 for b in right_ranks)
    )
    return numerator / denominator if denominator else 1.0


def _ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks
