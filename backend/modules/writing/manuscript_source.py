"""Stable original-text selection, literal search, and range reads."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from modules.writing.contracts import (
    ManuscriptReadContract,
    ManuscriptSearchHitContract,
    SourceRangeRefContract,
    WritingDraftContract,
)
from modules.writing.models import WritingDraft
from modules.writing.repositories import WORKING_DRAFT_STATUSES, WritingDraftRepository
from modules.writing.schemas import project_writing_draft_state
from modules.writing.source_hashing import hash_text

MAX_PATTERN_LENGTH = 200
MAX_SEARCH_LIMIT = 100
MAX_PARAGRAPH_CONTEXT = 20
SNIPPET_CONTEXT_CHARS = 120


class ManuscriptSourceService:
    """Deep manuscript interface backed by concrete writing draft versions."""

    def __init__(self, repo: WritingDraftRepository | None = None) -> None:
        self._repo = repo or WritingDraftRepository()

    async def list_sources(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_indices: list[int],
        *,
        content_mode: str = "canonical",
    ) -> list[WritingDraftContract]:
        drafts = await self._repo.list_latest_by_mode(
            db,
            _uuid(novel_id, "novel_id"),
            chapter_indices,
            content_mode=content_mode,
        )
        return [_draft_contract(draft) for draft in drafts]

    async def grep(
        self,
        db: AsyncSession,
        novel_id: str,
        pattern: str,
        *,
        content_mode: str = "canonical",
        chapter_from: int | None = None,
        chapter_to: int | None = None,
        case_sensitive: bool = False,
        visible_end_offsets: dict[int, int] | None = None,
        skip: int = 0,
        limit: int = 20,
        group_by_chapter: bool = False,
    ) -> tuple[list[ManuscriptSearchHitContract], int, list[int]]:
        pattern = pattern.strip()
        if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
            raise ValidationError(
                f"pattern length must be between 1 and {MAX_PATTERN_LENGTH}"
            )
        if skip < 0:
            raise ValidationError("skip must be >= 0")
        limit = max(1, min(limit, MAX_SEARCH_LIMIT))
        all_indices = await self._repo.list_chapter_indices(
            db,
            _uuid(novel_id, "novel_id"),
        )
        scoped = [
            index
            for index in all_indices
            if (chapter_from is None or index >= chapter_from)
            and (chapter_to is None or index <= chapter_to)
        ]
        sources = await self.list_sources(
            db,
            novel_id,
            scoped,
            content_mode=content_mode,
        )
        available = {source.chapter_index for source in sources}
        missing = [index for index in scoped if index not in available]
        needle = pattern if case_sensitive else pattern.lower()
        hits: list[ManuscriptSearchHitContract] = []
        for source in sources:
            content = source.content or ""
            visible_end = (visible_end_offsets or {}).get(source.chapter_index)
            if visible_end is not None:
                content = content[: max(0, min(len(content), visible_end))]
            haystack = content if case_sensitive else content.lower()
            offset = 0
            while True:
                start = haystack.find(needle, offset)
                if start < 0:
                    break
                end = start + len(pattern)
                snippet_start = max(0, start - SNIPPET_CONTEXT_CHARS)
                snippet_end = min(len(content), end + SNIPPET_CONTEXT_CHARS)
                hits.append(
                    ManuscriptSearchHitContract(
                        source_ref=_source_ref(
                            source,
                            content_mode=content_mode,
                            start_offset=start,
                            end_offset=end,
                        ),
                        title=source.title,
                        snippet=content[snippet_start:snippet_end],
                        match_start=start - snippet_start,
                        match_end=end - snippet_start,
                    )
                )
                offset = end if end > start else start + 1
        total = len(hits)
        if group_by_chapter:
            grouped: dict[int, ManuscriptSearchHitContract] = {}
            counts: dict[int, int] = {}
            refs: dict[int, list[SourceRangeRefContract]] = {}
            for hit in hits:
                chapter_index = hit.source_ref.chapter_index
                counts[chapter_index] = counts.get(chapter_index, 0) + 1
                refs.setdefault(chapter_index, []).append(hit.source_ref)
                grouped.setdefault(chapter_index, hit)
            hits = [
                replace(
                    hit,
                    match_count=counts[chapter_index],
                    source_refs=refs[chapter_index],
                )
                for chapter_index, hit in grouped.items()
            ]
            total = len(hits)
        return hits[skip : skip + limit], total, missing

    async def read(
        self,
        db: AsyncSession,
        novel_id: str,
        source_ref: SourceRangeRefContract,
        *,
        before: int = 3,
        after: int = 3,
        max_end_offset: int | None = None,
    ) -> ManuscriptReadContract:
        if not 0 <= before <= MAX_PARAGRAPH_CONTEXT:
            raise ValidationError(f"before must be between 0 and {MAX_PARAGRAPH_CONTEXT}")
        if not 0 <= after <= MAX_PARAGRAPH_CONTEXT:
            raise ValidationError(f"after must be between 0 and {MAX_PARAGRAPH_CONTEXT}")
        draft = await self._repo.get(db, _uuid(source_ref.draft_id, "draft_id"))
        if draft is None or draft.novel_id != _uuid(novel_id, "novel_id"):
            raise NotFoundError("Source draft not found in this novel")
        content = draft.content or ""
        source_hash = hash_text(content)
        if source_hash != source_ref.source_hash:
            raise ValidationError("Source range is stale: source hash mismatch")
        if draft.chapter_index != source_ref.chapter_index:
            raise ValidationError("Source range chapter does not match draft")
        start = source_ref.start_offset
        end = source_ref.end_offset
        if start < 0 or end <= start or end > len(content):
            raise ValidationError("Source range offsets are invalid")
        if hash_text(content[start:end]) != source_ref.range_hash:
            raise ValidationError("Source range is stale: range hash mismatch")
        if draft.version_number != source_ref.version_number:
            raise ValidationError("Source range version does not match draft")
        _validate_content_mode(draft, source_ref.content_mode)
        if max_end_offset is not None and end > max_end_offset:
            raise ValidationError("Source range exceeds the visible cursor")
        expanded_start, expanded_end = _expand_paragraphs(
            content,
            start,
            end,
            before=before,
            after=after,
        )
        if max_end_offset is not None:
            expanded_end = min(expanded_end, max_end_offset)
        return ManuscriptReadContract(
            source_ref=source_ref,
            title=draft.title,
            text=content[expanded_start:expanded_end],
            highlight_start=start - expanded_start,
            highlight_end=end - expanded_start,
            paragraph_before=before,
            paragraph_after=after,
        )

    async def build_range_ref(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        draft_id: str,
        start_offset: int,
        end_offset: int,
        content_mode: str,
    ) -> SourceRangeRefContract:
        draft = await self._repo.get(db, _uuid(draft_id, "draft_id"))
        if draft is None or draft.novel_id != _uuid(novel_id, "novel_id"):
            raise NotFoundError("Source draft not found in this novel")
        _validate_content_mode(draft, content_mode)
        return _source_ref(
            _draft_contract(draft),
            content_mode=content_mode,
            start_offset=start_offset,
            end_offset=end_offset,
        )


def _source_ref(
    draft: WritingDraftContract,
    *,
    content_mode: str,
    start_offset: int,
    end_offset: int,
) -> SourceRangeRefContract:
    content = draft.content or ""
    if draft.id is None or start_offset < 0 or end_offset <= start_offset:
        raise ValidationError("Cannot build an empty or invalid source range")
    if end_offset > len(content):
        raise ValidationError("Source range exceeds draft content")
    return SourceRangeRefContract(
        draft_id=draft.id,
        chapter_index=draft.chapter_index,
        version_number=draft.version_number,
        content_mode=content_mode,
        start_offset=start_offset,
        end_offset=end_offset,
        source_hash=draft.content_hash or hash_text(content),
        range_hash=hash_text(content[start_offset:end_offset]),
    )


def _draft_contract(draft: WritingDraft) -> WritingDraftContract:
    content = draft.content or ""
    projection = project_writing_draft_state(draft.status, draft.provenance_json)
    return WritingDraftContract(
        id=str(draft.id),
        novel_id=str(draft.novel_id),
        chapter_index=draft.chapter_index,
        title=draft.title,
        content=content,
        content_hash=draft.content_hash or hash_text(content),
        version_number=draft.version_number,
        status=draft.status,
        conflict_check_snapshot_json=draft.conflict_check_snapshot_json,
        provenance_json=draft.provenance_json,
        display_state=projection["display_state"],
        source=projection["source"],
        attention_reasons=projection["attention_reasons"],
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def _validate_content_mode(draft: WritingDraft, content_mode: str) -> None:
    if content_mode == "canonical":
        was_published = (draft.provenance_json or {}).get(
            "deprecated_from_status"
        ) == "published"
        if draft.status != "published" and not was_published:
            raise ValidationError("canonical source must reference a published draft")
        return
    if content_mode == "working":
        if draft.status not in WORKING_DRAFT_STATUSES:
            raise ValidationError("working source must reference an adopted draft")
        return
    raise ValidationError("content_mode must be canonical or working")


def _expand_paragraphs(
    content: str,
    start: int,
    end: int,
    *,
    before: int,
    after: int,
) -> tuple[int, int]:
    paragraphs = [
        (match.start(), match.end())
        for match in re.finditer(r"[^\n]+(?:\n|$)", content)
        if match.group(0).strip()
    ]
    if not paragraphs:
        return start, end
    first = next(
        (
            index
            for index, (_, paragraph_end) in enumerate(paragraphs)
            if start < paragraph_end
        ),
        len(paragraphs) - 1,
    )
    last = (
        next(
            (
                index
                for index, (paragraph_start, _) in enumerate(
                    paragraphs[first:], start=first
                )
                if end <= paragraph_start
            ),
            len(paragraphs),
        )
        - 1
    )
    first = max(0, first - before)
    last = min(len(paragraphs) - 1, max(first, last) + after)
    return paragraphs[first][0], paragraphs[last][1]


def _uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Invalid {field}") from exc
