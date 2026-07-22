"""
RAG 查询扩展

基于项目词典（人物、世界对象/别名）扩展查询词，适配中文小说别名/称号。
该模块是 RAG 内部唯一直接了解 world 列表容器约定的地方。
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from core.container import get as _container_get
from infrastructure.llm.redaction import redact_diagnostic

logger = logging.getLogger(__name__)

_TermLoader = Callable[[AsyncSession, uuid.UUID], Awaitable[list[dict[str, str]]]]
_PROJECT_TERMS_TTL_SECONDS = 60.0
_PROJECT_TERMS_CACHE: dict[uuid.UUID, tuple[float, list[dict[str, str]]]] = {}


def _add_term(
    terms: list[dict[str, str]],
    *,
    term: str | None,
    target_id: str,
    target_type: str,
) -> None:
    value = (term or "").strip()
    if len(value) < 2:
        return
    terms.append({"term": value, "id": target_id, "type": target_type})


async def _load_project_terms(
    db: AsyncSession,
    novel_id: uuid.UUID,
    *,
    strict: bool = False,
) -> list[dict[str, str]]:
    """加载项目词典：人物、世界对象/别名、剧情线。"""
    cached = _PROJECT_TERMS_CACHE.get(novel_id)
    now = time.monotonic()
    if cached and now - cached[0] <= _PROJECT_TERMS_TTL_SECONDS:
        return [dict(item) for item in cached[1]]

    terms: list[dict[str, str]] = []
    novel_id_str = str(novel_id)

    try:
        _list_entity_terms = _container_get("world.list_entity_terms")

        entity_terms = await _list_entity_terms(db, novel_id_str)
        for item in entity_terms:
            target_type = (
                "character" if item.get("entity_type") == "character" else "entity"
            )
            for term in item.get("terms", []):
                _add_term(
                    terms,
                    term=term,
                    target_id=str(item["id"]),
                    target_type=target_type,
                )
    except Exception as exc:
        if strict:
            _PROJECT_TERMS_CACHE.pop(novel_id, None)
            raise
        logger.warning(
            "rag_project_terms_load_failed novel_id=%s; "
            "continuing_without_world_terms reason=%s",
            novel_id,
            redact_diagnostic(exc, limit=300),
        )

    terms.sort(key=lambda x: len(x["term"]), reverse=True)
    _PROJECT_TERMS_CACHE[novel_id] = (now, [dict(item) for item in terms])
    return terms


def clear_project_terms_cache(novel_id: uuid.UUID | None = None) -> None:
    """Clear query-expansion term cache after tests or explicit invalidation."""
    if novel_id is None:
        _PROJECT_TERMS_CACHE.clear()
    else:
        _PROJECT_TERMS_CACHE.pop(novel_id, None)


def _match_project_terms(
    text: str,
    terms: list[dict[str, str]],
) -> tuple[list[str], list[str], list[str]]:
    """根据项目词典匹配文本中出现的人物/实体/剧情线 ID。"""
    character_ids: list[str] = []
    entity_ids: list[str] = []
    thread_ids: list[str] = []
    seen: set[tuple[str, str]] = set()

    for item in terms:
        term = item["term"]
        if term not in text:
            continue
        key = (item["type"], item["id"])
        if key in seen:
            continue
        seen.add(key)
        if item["type"] == "character":
            character_ids.append(item["id"])
        elif item["type"] == "entity":
            entity_ids.append(item["id"])
        elif item["type"] == "thread":
            thread_ids.append(item["id"])

    return character_ids, entity_ids, thread_ids


def _cn_ngrams(term: str, min_n: int = 2, max_n: int = 4) -> list[str]:
    """提取中文查询的 n-gram，用于模糊匹配别名。"""
    compact = re.sub(r"\s+", "", term)
    if not compact or not any("\u4e00" <= ch <= "\u9fff" for ch in compact):
        return []
    grams: list[str] = []
    seen: set[str] = set()
    for n in range(min_n, min(max_n, len(compact)) + 1):
        for i in range(0, len(compact) - n + 1):
            gram = compact[i : i + n]
            if gram not in seen:
                seen.add(gram)
                grams.append(gram)
    return grams


async def _expand_query_with_project_terms(
    db: AsyncSession,
    novel_id: uuid.UUID,
    query: str,
    *,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
) -> str:
    """用项目词典扩展查询词。"""
    terms = await _load_project_terms(db, novel_id)
    if not terms:
        return query

    requested: set[tuple[str, str]] = set()
    for cid in character_ids or []:
        requested.add(("character", cid))
    for eid in entity_ids or []:
        requested.add(("entity", eid))
    for tid in thread_ids or []:
        requested.add(("thread", tid))

    compact_query = query.replace(" ", "")
    for item in terms:
        term = item["term"]
        if term in query or term in compact_query or query in term:
            requested.add((item["type"], item["id"]))
            continue
        if any(gram in term for gram in _cn_ngrams(query)):
            requested.add((item["type"], item["id"]))

    expanded: list[str] = [query]
    for item in terms:
        if (item["type"], item["id"]) not in requested:
            continue
        if item["term"] not in expanded:
            expanded.append(item["term"])

    for gram in _cn_ngrams(query):
        if gram not in expanded:
            expanded.append(gram)

    return " ".join(expanded)


class QueryExpander:
    """可注入 term_loader 的查询扩展器，便于测试替换为 fake loader。"""

    def __init__(
        self,
        term_loader: _TermLoader | None = None,
    ) -> None:
        self._term_loader = term_loader or _load_project_terms

    async def expand(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query: str,
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
    ) -> str:
        """加载项目词典并扩展查询词。"""
        terms = await self._term_loader(db, novel_id)
        if not terms:
            return query

        requested: set[tuple[str, str]] = set()
        for cid in character_ids or []:
            requested.add(("character", cid))
        for eid in entity_ids or []:
            requested.add(("entity", eid))
        for tid in thread_ids or []:
            requested.add(("thread", tid))

        compact_query = query.replace(" ", "")
        for item in terms:
            term = item["term"]
            if term in query or term in compact_query or query in term:
                requested.add((item["type"], item["id"]))
                continue
            if any(gram in term for gram in _cn_ngrams(query)):
                requested.add((item["type"], item["id"]))

        expanded: list[str] = [query]
        for item in terms:
            if (item["type"], item["id"]) not in requested:
                continue
            if item["term"] not in expanded:
                expanded.append(item["term"])

        for gram in _cn_ngrams(query):
            if gram not in expanded:
                expanded.append(gram)

        return " ".join(expanded)
