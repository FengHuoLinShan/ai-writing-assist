"""Agent-facing read/search tools for deep import workflows.

The tools do not own a second text index. Search reuses RAG retrieval first and
falls back to bounded keyword scans over latest writing drafts. Read treats the
latest writing draft as the authoritative source and only uses RAG chunk text as
a degraded fallback when offsets are stale or the draft is missing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.agent_step_harness import AgentErrorKind
from modules.rag.contracts import RagChunkContract, RagResultBundle
from modules.writing.contracts import WritingDraftContract

AGENT_TEXT_TOOL_MAX_CHARS = 32000
AGENT_TEXT_SEARCH_MAX_RESULTS = 20
AGENT_TEXT_SEARCH_SNIPPET_CHARS = 400


@dataclass(frozen=True)
class NovelTextAnchor:
    chapter_index: int | None = None
    chunk_index: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    scene_id: str | None = None
    rag_chunk_id: str | None = None
    source_type: str = "writing_draft"

    @classmethod
    def from_rag_chunk(cls, chunk: RagChunkContract) -> NovelTextAnchor:
        return cls(
            chapter_index=chunk.chapter_index,
            chunk_index=chunk.chunk_index,
            start_offset=chunk.start_offset,
            end_offset=chunk.end_offset,
            scene_id=chunk.scene_id,
            rag_chunk_id=chunk.id,
            source_type=chunk.source_type or "rag_chunk",
        )

    def model_dump(self) -> dict[str, Any]:
        return {
            "chapter_index": self.chapter_index,
            "chunk_index": self.chunk_index,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "scene_id": self.scene_id,
            "rag_chunk_id": self.rag_chunk_id,
            "source_type": self.source_type,
        }


@dataclass(frozen=True)
class NovelTextSnippet:
    anchor: NovelTextAnchor
    snippet: str
    score: float | None = None
    reason: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor.model_dump(),
            "snippet": self.snippet,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NovelTextSearchResult:
    items: list[NovelTextSnippet] = field(default_factory=list)
    degraded: bool = False
    reason: str = ""
    truncated: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "items": [item.model_dump() for item in self.items],
            "degraded": self.degraded,
            "reason": self.reason,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class NovelTextReadResult:
    content: str = ""
    anchors: list[NovelTextAnchor] = field(default_factory=list)
    degraded: bool = False
    reason: str = ""
    error_kind: str | None = None
    truncated: bool = False

    def model_dump(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "anchors": [anchor.model_dump() for anchor in self.anchors],
            "degraded": self.degraded,
            "reason": self.reason,
            "error_kind": self.error_kind,
            "truncated": self.truncated,
        }


RetrieveFn = Callable[..., Awaitable[RagResultBundle]]
GetIndexStatusFn = Callable[..., Awaitable[dict[str, Any]]]
ListChapterIndicesFn = Callable[..., Awaitable[list[int]]]
GetDraftFn = Callable[[AsyncSession, str, int], Awaitable[WritingDraftContract | None]]
GetRagChunkFn = Callable[[AsyncSession, str, str], Awaitable[RagChunkContract | None]]
GetSceneFn = Callable[[AsyncSession, str, str], Awaitable[Any | None]]


class NovelTextSearchTool:
    """Search novel text through RAG first, then bounded draft keyword scan."""

    def __init__(
        self,
        *,
        retrieve_fn: RetrieveFn | None = None,
        get_index_status_fn: GetIndexStatusFn | None = None,
        list_chapter_indices_fn: ListChapterIndicesFn | None = None,
        get_draft_fn: GetDraftFn | None = None,
    ) -> None:
        self._retrieve_fn = retrieve_fn
        self._get_index_status_fn = get_index_status_fn
        self._list_chapter_indices_fn = list_chapter_indices_fn
        self._get_draft_fn = get_draft_fn

    async def search(
        self,
        db: AsyncSession,
        novel_id: str,
        query: str,
        *,
        chapter_index: int | None = None,
        top_k: int = 12,
    ) -> NovelTextSearchResult:
        top_k = max(1, min(int(top_k), AGENT_TEXT_SEARCH_MAX_RESULTS))
        query = str(query or "").strip()
        if not query:
            return NovelTextSearchResult(degraded=True, reason="empty_query")

        try:
            rag_result = await self._retrieve(
                db,
                novel_id,
                query,
                chapter_index=chapter_index,
                top_k=top_k,
            )
        except Exception as exc:
            reason = _fallback_reason_from_exception(exc)
        else:
            if rag_result.chunks:
                return NovelTextSearchResult(
                    items=[
                        _snippet_from_rag_chunk(chunk)
                        for chunk in rag_result.chunks[:top_k]
                    ],
                    degraded=bool(rag_result.degraded),
                    reason="; ".join(rag_result.warnings),
                    truncated=len(rag_result.chunks) > top_k,
                )
            reason = await self._empty_rag_reason(db, novel_id)

        fallback = await self._keyword_fallback(
            db,
            novel_id,
            query,
            chapter_index=chapter_index,
            top_k=top_k,
        )
        return NovelTextSearchResult(
            items=fallback.items,
            degraded=True,
            reason=reason or fallback.reason or "keyword_fallback",
            truncated=fallback.truncated,
        )

    async def _retrieve(
        self,
        db: AsyncSession,
        novel_id: str,
        query: str,
        *,
        chapter_index: int | None,
        top_k: int,
    ) -> RagResultBundle:
        if self._retrieve_fn is not None:
            return await self._retrieve_fn(
                db,
                novel_id,
                query,
                chapter_index=chapter_index,
                top_k=top_k,
                mode="search",
            )
        from modules.rag.facade import retrieve

        return await retrieve(
            db,
            novel_id,
            query,
            chapter_index=chapter_index,
            top_k=top_k,
            mode="search",
        )

    async def _empty_rag_reason(self, db: AsyncSession, novel_id: str) -> str:
        try:
            status = (
                await self._get_index_status_fn(db, novel_id)
                if self._get_index_status_fn is not None
                else await _get_rag_index_status(db, novel_id)
            )
        except Exception:
            return "keyword_fallback"
        if int(status.get("total") or 0) <= 0:
            return "no_rag_index"
        if int(status.get("embedding_failed_count") or 0) > 0:
            return "embedding_failed"
        return "keyword_fallback"

    async def _keyword_fallback(
        self,
        db: AsyncSession,
        novel_id: str,
        query: str,
        *,
        chapter_index: int | None,
        top_k: int,
    ) -> NovelTextSearchResult:
        indices = (
            [chapter_index]
            if chapter_index
            else await self._list_indices(db, novel_id)
        )
        lower_query = query.lower()
        results: list[NovelTextSnippet] = []
        for index in indices:
            if index is None:
                continue
            draft = await self._get_draft(db, novel_id, int(index))
            content = draft.content or "" if draft is not None else ""
            search_from = 0
            while len(results) < top_k:
                pos = content.lower().find(lower_query, search_from)
                if pos < 0:
                    break
                start = max(pos - AGENT_TEXT_SEARCH_SNIPPET_CHARS // 2, 0)
                end = min(start + AGENT_TEXT_SEARCH_SNIPPET_CHARS, len(content))
                results.append(
                    NovelTextSnippet(
                        anchor=NovelTextAnchor(
                            chapter_index=int(index),
                            start_offset=pos,
                            end_offset=pos + len(query),
                            source_type="writing_draft_keyword",
                        ),
                        snippet=content[start:end],
                        score=1.0,
                        reason="keyword_fallback",
                    )
                )
                search_from = pos + max(len(query), 1)
            if len(results) >= top_k:
                break
        return NovelTextSearchResult(
            items=results,
            degraded=True,
            reason="keyword_fallback",
            truncated=len(results) >= top_k,
        )

    async def _list_indices(self, db: AsyncSession, novel_id: str) -> list[int]:
        if self._list_chapter_indices_fn is not None:
            return await self._list_chapter_indices_fn(db, novel_id)
        from modules.writing.facade import list_chapter_indices

        return await list_chapter_indices(db, novel_id)

    async def _get_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftContract | None:
        if self._get_draft_fn is not None:
            return await self._get_draft_fn(db, novel_id, chapter_index)
        from modules.writing.facade import get_latest_draft_for_chapter

        return await get_latest_draft_for_chapter(db, novel_id, chapter_index)


class NovelTextReadTool:
    """Read authoritative text ranges from latest writing drafts."""

    def __init__(
        self,
        *,
        get_draft_fn: GetDraftFn | None = None,
        get_rag_chunk_fn: GetRagChunkFn | None = None,
        get_scene_fn: GetSceneFn | None = None,
        max_chars: int = AGENT_TEXT_TOOL_MAX_CHARS,
    ) -> None:
        self._get_draft_fn = get_draft_fn
        self._get_rag_chunk_fn = get_rag_chunk_fn
        self._get_scene_fn = get_scene_fn
        self.max_chars = max(1, min(max_chars, AGENT_TEXT_TOOL_MAX_CHARS))

    async def read(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        anchor: NovelTextAnchor | dict[str, Any] | None = None,
        rag_chunk_id: str | None = None,
        scene_id: str | None = None,
        chapter_index: int | None = None,
        start_offset: int | None = None,
        end_offset: int | None = None,
        start_paragraph: int | None = None,
        end_paragraph: int | None = None,
    ) -> NovelTextReadResult:
        if anchor is not None:
            anchor = _coerce_anchor(anchor)
            rag_chunk_id = rag_chunk_id or anchor.rag_chunk_id
            scene_id = scene_id or anchor.scene_id
            chapter_index = chapter_index or anchor.chapter_index
            start_offset = (
                start_offset if start_offset is not None else anchor.start_offset
            )
            end_offset = end_offset if end_offset is not None else anchor.end_offset

        if rag_chunk_id:
            chunk = await self._get_rag_chunk(db, novel_id, rag_chunk_id)
            if chunk is None:
                return NovelTextReadResult(
                    degraded=True,
                    reason="rag_chunk_not_found",
                    error_kind="not_found",
                )
            anchor = NovelTextAnchor.from_rag_chunk(chunk)
            return await self._read_chapter_range(
                db,
                novel_id,
                anchor=anchor,
                chapter_index=chunk.chapter_index,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                rag_fallback_text=chunk.text,
            )

        if scene_id:
            return await self._read_scene(db, novel_id, scene_id)

        if chapter_index is None:
            return NovelTextReadResult(
                degraded=True,
                reason="missing_read_scope",
                error_kind="missing_scope",
            )
        return await self._read_chapter_range(
            db,
            novel_id,
            anchor=NovelTextAnchor(
                chapter_index=chapter_index,
                start_offset=start_offset,
                end_offset=end_offset,
                source_type="writing_draft",
            ),
            chapter_index=chapter_index,
            start_offset=start_offset,
            end_offset=end_offset,
            start_paragraph=start_paragraph,
            end_paragraph=end_paragraph,
        )

    async def _read_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> NovelTextReadResult:
        scene = await self._get_scene(db, novel_id, scene_id)
        if scene is None:
            return NovelTextReadResult(
                degraded=True,
                reason="scene_not_found",
                error_kind="not_found",
            )
        chunks = getattr(scene, "scene_chunks", None)
        if chunks is None and isinstance(scene, dict):
            chunks = scene.get("scene_chunks")
        chunks = chunks or []
        if not chunks:
            return NovelTextReadResult(
                degraded=True,
                reason="scene_without_chunks",
                error_kind="missing_scope",
            )

        contents: list[str] = []
        anchors: list[NovelTextAnchor] = []
        degraded = False
        reason = ""
        for chunk in chunks:
            result = await self._read_chapter_range(
                db,
                novel_id,
                anchor=_anchor_from_scene_chunk(scene_id, chunk),
                chapter_index=_chunk_value(chunk, "chapter_index"),
                start_offset=_first_chunk_value(chunk, ("start_offset", "start_pos")),
                end_offset=_first_chunk_value(chunk, ("end_offset", "end_pos")),
                start_paragraph=_chunk_value(chunk, "start_paragraph"),
                end_paragraph=_chunk_value(chunk, "end_paragraph"),
            )
            if result.error_kind:
                degraded = True
                reason = reason or result.reason
                continue
            contents.append(result.content)
            anchors.extend(result.anchors)
            degraded = degraded or result.degraded
            reason = reason or result.reason
            if sum(len(part) for part in contents) > self.max_chars:
                joined = "\n\n".join(contents)[: self.max_chars]
                return NovelTextReadResult(
                    content=joined,
                    anchors=anchors,
                    degraded=degraded,
                    reason=reason,
                    truncated=True,
                )
        return NovelTextReadResult(
            content="\n\n".join(contents),
            anchors=anchors,
            degraded=degraded,
            reason=reason,
        )

    async def _read_chapter_range(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        anchor: NovelTextAnchor,
        chapter_index: int | None,
        start_offset: int | None = None,
        end_offset: int | None = None,
        start_paragraph: int | None = None,
        end_paragraph: int | None = None,
        rag_fallback_text: str = "",
    ) -> NovelTextReadResult:
        if chapter_index is None:
            return NovelTextReadResult(
                degraded=True,
                reason="missing_chapter_index",
                error_kind="missing_scope",
            )
        draft = await self._get_draft(db, novel_id, int(chapter_index))
        content = draft.content or "" if draft is not None else ""
        if not content and rag_fallback_text:
            return _capped_read_result(
                rag_fallback_text,
                [anchor],
                max_chars=self.max_chars,
                degraded=True,
                reason="rag_chunk_text_fallback",
            )
        if draft is None:
            return NovelTextReadResult(
                degraded=True,
                reason="chapter_not_found",
                error_kind="not_found",
            )

        has_range = (
            start_offset is not None
            or end_offset is not None
            or start_paragraph is not None
            or end_paragraph is not None
        )
        if start_offset is not None or end_offset is not None:
            if _valid_offsets(content, start_offset, end_offset):
                selected = content[int(start_offset) : int(end_offset)]
                return _capped_read_result(
                    selected,
                    [
                        NovelTextAnchor(
                            chapter_index=int(chapter_index),
                            start_offset=int(start_offset),
                            end_offset=int(end_offset),
                            scene_id=anchor.scene_id,
                            rag_chunk_id=anchor.rag_chunk_id,
                            source_type="writing_draft",
                        )
                    ],
                    max_chars=self.max_chars,
                )
            if rag_fallback_text:
                return _capped_read_result(
                    rag_fallback_text,
                    [anchor],
                    max_chars=self.max_chars,
                    degraded=True,
                    reason="stale_offset_fallback",
                )
            return NovelTextReadResult(
                degraded=True,
                reason="stale_offset",
                error_kind="stale_offset",
            )

        if start_paragraph is not None or end_paragraph is not None:
            selected, start, end = _paragraph_slice(
                content,
                start_paragraph=start_paragraph,
                end_paragraph=end_paragraph,
            )
            return _capped_read_result(
                selected,
                [
                    NovelTextAnchor(
                        chapter_index=int(chapter_index),
                        start_offset=start,
                        end_offset=end,
                        scene_id=anchor.scene_id,
                        rag_chunk_id=anchor.rag_chunk_id,
                        source_type="writing_draft",
                    )
                ],
                max_chars=self.max_chars,
            )

        if not has_range and len(content) > self.max_chars:
            return NovelTextReadResult(
                degraded=True,
                reason="read_scope_exceeds_budget",
                error_kind=AgentErrorKind.context_overflow.value,
            )
        return _capped_read_result(
            content,
            [
                NovelTextAnchor(
                    chapter_index=int(chapter_index),
                    start_offset=0,
                    end_offset=len(content),
                    scene_id=anchor.scene_id,
                    rag_chunk_id=anchor.rag_chunk_id,
                    source_type="writing_draft",
                )
            ],
            max_chars=self.max_chars,
        )

    async def _get_draft(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
    ) -> WritingDraftContract | None:
        if self._get_draft_fn is not None:
            return await self._get_draft_fn(db, novel_id, chapter_index)
        from modules.writing.facade import get_latest_draft_for_chapter

        return await get_latest_draft_for_chapter(db, novel_id, chapter_index)

    async def _get_rag_chunk(
        self,
        db: AsyncSession,
        novel_id: str,
        chunk_id: str,
    ) -> RagChunkContract | None:
        if self._get_rag_chunk_fn is not None:
            return await self._get_rag_chunk_fn(db, novel_id, chunk_id)
        from modules.rag.facade import get_chunk_contract

        return await get_chunk_contract(db, novel_id, chunk_id)

    async def _get_scene(self, db: AsyncSession, novel_id: str, scene_id: str) -> Any:
        if self._get_scene_fn is not None:
            return await self._get_scene_fn(db, novel_id, scene_id)
        from modules.outline.facade import get_scene_contract

        return await get_scene_contract(db, novel_id, scene_id)


class WorkflowReadTool:
    """Read workflow task result sections without exposing arbitrary storage."""

    allowed_keys = {
        "phase_timeline",
        "checkpoints",
        "quality_stats",
        "phase_errors",
        "diagnostic_counts",
        "llm_health",
    }

    def read(
        self,
        task_result: dict[str, Any],
        keys: list[str] | None = None,
    ) -> dict[str, Any]:
        selected = keys or sorted(self.allowed_keys)
        return {
            key: task_result.get(key)
            for key in selected
            if key in self.allowed_keys
        }


async def _get_rag_index_status(db: AsyncSession, novel_id: str) -> dict[str, Any]:
    from modules.rag.facade import get_index_status

    return await get_index_status(db, novel_id)


def _snippet_from_rag_chunk(chunk: RagChunkContract) -> NovelTextSnippet:
    text = chunk.text or chunk.summary or ""
    snippet = text[:AGENT_TEXT_SEARCH_SNIPPET_CHARS]
    return NovelTextSnippet(
        anchor=NovelTextAnchor.from_rag_chunk(chunk),
        snippet=snippet,
        score=chunk.score,
        reason="rag_retrieve",
    )


def _fallback_reason_from_exception(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if "embedding" in text:
        return "embedding_failed"
    if "index" in text:
        return "no_rag_index"
    return "keyword_fallback"


def _coerce_anchor(anchor: NovelTextAnchor | dict[str, Any]) -> NovelTextAnchor:
    if isinstance(anchor, NovelTextAnchor):
        return anchor
    return NovelTextAnchor(
        chapter_index=anchor.get("chapter_index"),
        chunk_index=anchor.get("chunk_index"),
        start_offset=anchor.get("start_offset"),
        end_offset=anchor.get("end_offset"),
        scene_id=anchor.get("scene_id"),
        rag_chunk_id=anchor.get("rag_chunk_id"),
        source_type=anchor.get("source_type") or "writing_draft",
    )


def _anchor_from_scene_chunk(scene_id: str, chunk: Any) -> NovelTextAnchor:
    return NovelTextAnchor(
        chapter_index=_chunk_value(chunk, "chapter_index"),
        start_offset=_first_chunk_value(chunk, ("start_offset", "start_pos")),
        end_offset=_first_chunk_value(chunk, ("end_offset", "end_pos")),
        scene_id=scene_id,
        source_type="scene_chunk",
    )


def _chunk_value(chunk: Any, key: str) -> Any:
    if isinstance(chunk, dict):
        return chunk.get(key)
    return getattr(chunk, key, None)


def _first_chunk_value(chunk: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = _chunk_value(chunk, key)
        if value is not None:
            return value
    return None


def _valid_offsets(
    content: str,
    start_offset: int | None,
    end_offset: int | None,
) -> bool:
    if start_offset is None or end_offset is None:
        return False
    try:
        start = int(start_offset)
        end = int(end_offset)
    except (TypeError, ValueError):
        return False
    return 0 <= start < end <= len(content)


def _paragraph_slice(
    content: str,
    *,
    start_paragraph: int | None,
    end_paragraph: int | None,
) -> tuple[str, int, int]:
    paragraphs = _paragraph_ranges(content)
    if not paragraphs:
        return "", 0, 0
    start_idx = max(int(start_paragraph or 0), 0)
    end_idx = min(
        int(end_paragraph if end_paragraph is not None else start_idx),
        len(paragraphs) - 1,
    )
    if end_idx < start_idx:
        end_idx = start_idx
    start_offset = (
        paragraphs[start_idx][0] if start_idx < len(paragraphs) else len(content)
    )
    end_offset = paragraphs[end_idx][1] if end_idx < len(paragraphs) else len(content)
    return content[start_offset:end_offset], start_offset, end_offset


def _paragraph_ranges(content: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        start = offset
        offset += len(line)
        if line.strip():
            ranges.append((start, offset))
    if not ranges and content:
        ranges.append((0, len(content)))
    return ranges


def _capped_read_result(
    content: str,
    anchors: list[NovelTextAnchor],
    *,
    max_chars: int,
    degraded: bool = False,
    reason: str = "",
) -> NovelTextReadResult:
    truncated = len(content) > max_chars
    return NovelTextReadResult(
        content=content[:max_chars] if truncated else content,
        anchors=anchors,
        degraded=degraded,
        reason=reason,
        truncated=truncated,
    )
