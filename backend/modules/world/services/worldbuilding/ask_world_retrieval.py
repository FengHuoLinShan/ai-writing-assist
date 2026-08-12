"""Conservative lexical gate for author-only world questions."""

from __future__ import annotations

import re
import unicodedata

MIN_RELEVANCE = 0.2
_QUESTION_NOISE = (
    "请问",
    "告诉我",
    "这个世界",
    "世界里",
    "设定中",
    "是什么",
    "有什么",
    "为什么",
    "怎么样",
    "如何",
    "是否",
    "哪里",
    "哪些",
    "什么",
)


def _normalized(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum() or "\u4e00" <= character <= "\u9fff"
    )


def _question_terms(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    for phrase in _QUESTION_NOISE:
        normalized = normalized.replace(phrase, " ")
    terms = set(re.findall(r"[a-z0-9_]{2,}", normalized))
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(run) <= 2:
            terms.add(run)
        else:
            terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return {term for term in terms if term}


def ask_world_relevance(question: str, title: str, content: str) -> float:
    """Require visible lexical support even when semantic retrieval returns a hit."""
    terms = _question_terms(question)
    if not terms:
        return 0.0
    haystack = _normalized(f"{title}\n{content}")
    score = sum(term in haystack for term in terms) / len(terms)
    normalized_question = _normalized(question)
    if normalized_question and normalized_question in haystack:
        score += 0.5
    normalized_title = _normalized(title)
    if normalized_title and normalized_title in normalized_question:
        score += 0.25
    return min(score, 1.0)


__all__ = ["MIN_RELEVANCE", "ask_world_relevance"]
