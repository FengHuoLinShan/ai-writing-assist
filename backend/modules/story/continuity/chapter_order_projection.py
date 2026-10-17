"""Pure projection of MemoryEvent chapter bindings across order receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class ChapterOrderReceiptLike(Protocol):
    id: object
    chapter_map_json: dict | None
    created_at: datetime | None
    restored_at: datetime | None


ChapterOrderTransition = tuple[datetime, int, str, dict[int, int]]
MAX_CHAPTER_EVENT_CANDIDATES = 500


def build_chapter_order_transitions(
    receipts: list[ChapterOrderReceiptLike],
) -> tuple[ChapterOrderTransition, ...]:
    transitions = []
    for receipt in receipts:
        mapping = {
            int(source): int(target)
            for source, target in (receipt.chapter_map_json or {}).items()
        }
        applied_at = _as_utc(receipt.created_at)
        if applied_at is not None:
            transitions.append((applied_at, 0, str(receipt.id), mapping))
        restored_at = _as_utc(receipt.restored_at)
        if restored_at is not None:
            inverse = {target: source for source, target in mapping.items()}
            transitions.append((restored_at, 1, str(receipt.id), inverse))
    return tuple(sorted(transitions))


def project_current_chapter_index(
    chapter_index: int | None,
    created_at: datetime | None,
    transitions: tuple[ChapterOrderTransition, ...],
) -> int | None:
    if chapter_index is None:
        return None
    event_time = _as_utc(created_at)
    current_index = int(chapter_index)
    for occurred_at, _phase, _receipt_id, mapping in transitions:
        if event_time is not None and event_time < occurred_at:
            current_index = mapping.get(current_index, current_index)
    return current_index


def affected_chapter_indices(
    transitions: tuple[ChapterOrderTransition, ...],
) -> set[int]:
    return {
        chapter
        for _occurred_at, _phase, _receipt_id, mapping in transitions
        for pair in mapping.items()
        for chapter in pair
    }


def candidate_chapter_indices(
    from_chapter: int,
    to_chapter: int,
    transitions: tuple[ChapterOrderTransition, ...],
) -> set[int]:
    candidates = set()
    touched = affected_chapter_indices(transitions)
    suffix_starts = [0]
    for index in range(1, len(transitions)):
        if transitions[index - 1][0] != transitions[index][0]:
            suffix_starts.append(index)
    suffix_starts.append(len(transitions))
    for original in touched:
        for start in suffix_starts:
            current = original
            for _occurred_at, _phase, _receipt_id, mapping in transitions[start:]:
                current = mapping.get(current, current)
            if from_chapter <= current <= to_chapter:
                candidates.add(original)
                break
    return candidates


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
