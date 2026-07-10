"""Deterministic, spoiler-safe context preparation for deep-import Phase 2a."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.token_estimation import estimate_token_count
from modules.context.contracts import ImportContextActivationContract

_ACTIVATION_VERSION = "import-context-v1"
_PREVIOUS_EVIDENCE_LIMIT = 700


class ImportContextActivationService:
    """Hide cross-module reads behind the context module's deep interface."""

    async def prepare(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        context_mode: str,
        budget_tokens: int,
        prior_neighbor_limit: int,
        visible_until_chapter: int | None = None,
        visible_until_offset: int | None = None,
    ) -> ImportContextActivationContract:
        from modules.outline.facade import get_scene_context_window
        from modules.world.facade import get_world_background

        window = await get_scene_context_window(
            db,
            novel_id,
            scene_id,
            previous_limit=max(0, min(prior_neighbor_limit, 4)),
            status_filter=["canonical", "draft"],
            content_mode=context_mode,
        )
        if window is None:
            raise ValueError("scene_not_found")
        current_spans = await self._bind_current_scene_spans(
            db,
            novel_id=novel_id,
            scene_id=scene_id,
            content_mode=context_mode,
            scene_chunks=window.scene.scene_chunks,
        )
        current_text, current_sources = await self._load_scene_text(
            db,
            novel_id,
            window.scene.scene_chunks,
            current_spans,
            content_mode=context_mode,
            visible_until_chapter=visible_until_chapter,
            visible_until_offset=visible_until_offset,
        )
        background = await get_world_background(
            db,
            novel_id,
            context_mode=context_mode,
        )
        world_entries = [self._entry_dict(entry) for entry in background.entries]
        current_terms = self._matching_terms(current_text, world_entries)
        previous_briefs = [self._brief_dict(brief) for brief in window.previous_briefs]
        previous_evidence = await self._load_previous_evidence(
            db,
            novel_id,
            window.previous_briefs,
            current_terms,
            content_mode=context_mode,
            visible_until_chapter=visible_until_chapter,
            visible_until_offset=visible_until_offset,
        )
        world_context_text, world_budget_events = self._world_context(
            world_entries,
            budget_tokens=max(500, budget_tokens // 3),
        )
        neighbor_context_text = self._neighbor_context(previous_briefs, previous_evidence)
        if not current_sources:
            current_sources = [{"type": "scene", "id": window.scene.id}]
        sources = [
            *current_sources,
            *[
                {"type": entry["asset_type"], "id": entry["asset_id"]}
                for entry in world_entries
            ],
        ]
        visible_source_chapters = [
            int(source["chapter_index"])
            for source in current_sources
            if str(source.get("chapter_index", "")).isdigit()
        ]
        chapter_index = max(
            visible_source_chapters,
            default=min(
                self._scene_chapter_index(window.scene.scene_chunks),
                visible_until_chapter,
            )
            if visible_until_chapter is not None
            else self._scene_chapter_index(window.scene.scene_chunks),
        )
        warnings = list(background.warnings)
        if not current_text:
            warnings.append("current_scene_text_unavailable")
        if visible_until_chapter is not None:
            warnings.append("visibility_cutoff_applied")
        return ImportContextActivationContract(
            novel_id=novel_id,
            scene_id=window.scene.id,
            scene_index=window.scene.scene_index,
            chapter_index=chapter_index,
            activation_version=_ACTIVATION_VERSION,
            current_scene_text=current_text,
            current_scene_sources=current_sources,
            previous_briefs=previous_briefs,
            previous_evidence=previous_evidence,
            world_entries=world_entries,
            world_context_text=world_context_text,
            neighbor_context_text=neighbor_context_text,
            sources=sources,
            budget_events=world_budget_events,
            warnings=warnings,
        )

    async def source_refs(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        content_mode: str,
        visible_until_chapter: int | None = None,
        visible_until_offset: int | None = None,
    ) -> list[dict]:
        """Return only hash-validated current-Scene source ranges for audit metadata."""
        from modules.outline.facade import get_scene_context_window

        window = await get_scene_context_window(
            db,
            novel_id,
            scene_id,
            previous_limit=0,
            status_filter=["canonical", "draft"],
            content_mode=content_mode,
        )
        if window is None:
            return []
        spans = await self._bind_current_scene_spans(
            db,
            novel_id=novel_id,
            scene_id=scene_id,
            content_mode=content_mode,
            scene_chunks=window.scene.scene_chunks,
        )
        _, source_refs = await self._load_scene_text(
            db,
            novel_id,
            window.scene.scene_chunks,
            spans,
            content_mode=content_mode,
            visible_until_chapter=visible_until_chapter,
            visible_until_offset=visible_until_offset,
        )
        return source_refs

    async def _load_previous_evidence(
        self,
        db: AsyncSession,
        novel_id: str,
        briefs: list,
        current_terms: set[str],
        *,
        content_mode: str,
        visible_until_chapter: int | None = None,
        visible_until_offset: int | None = None,
    ) -> list[dict]:
        evidence: list[dict] = []
        for brief in briefs:
            brief_text = " ".join(
                str(value or "")
                for value in (brief.title, brief.goal, brief.core_conflict)
            )
            if not any(term in brief_text for term in current_terms if len(term) > 1):
                continue
            spans = await self._bind_current_scene_spans(
                db,
                novel_id=novel_id,
                scene_id=brief.scene_id,
                content_mode=content_mode,
                scene_chunks=brief.scene_chunks,
            )
            text, _source_refs = await self._load_scene_text(
                db,
                novel_id,
                brief.scene_chunks,
                spans,
                content_mode=content_mode,
                visible_until_chapter=visible_until_chapter,
                visible_until_offset=visible_until_offset,
            )
            if not text:
                continue
            evidence.append(
                {
                    "scene_id": brief.scene_id,
                    "scene_index": brief.scene_index,
                    "text": text[:_PREVIOUS_EVIDENCE_LIMIT],
                    "reason": "shared_world_term",
                }
            )
        return evidence

    async def _load_scene_text(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_chunks: list[dict],
        spans: list,
        *,
        content_mode: str,
        visible_until_chapter: int | None = None,
        visible_until_offset: int | None = None,
    ) -> tuple[str, list[dict]]:
        from dataclasses import asdict

        from modules.writing.facade import (
            build_manuscript_range_ref,
            list_manuscript_sources,
            read_manuscript_range,
        )

        chunks = list(scene_chunks or [])
        if spans:
            chunks = [
                {
                    "chapter_index": span.chapter_index,
                    "start_offset": span.start_offset,
                    "end_offset": span.end_offset,
                    "start_paragraph": span.start_paragraph,
                    "end_paragraph": span.end_paragraph,
                    "scene_span_id": span.id,
                    "source_draft_id": span.source_draft_id,
                    "source_content_hash": span.source_content_hash,
                }
                for span in spans
                if span.mapping_status in {"exact", "reanchored"}
            ]
        chunks = self._clip_chunks_to_visibility(
            chunks,
            visible_until_chapter=visible_until_chapter,
            visible_until_offset=visible_until_offset,
        )
        chapter_indices = sorted(
            {
                int(chunk["chapter_index"])
                for chunk in chunks
                if str(chunk.get("chapter_index", "")).isdigit()
            }
        )
        if not chapter_indices:
            return "", []
        drafts = await list_manuscript_sources(
            db,
            novel_id,
            chapter_indices,
            content_mode=content_mode,
        )
        by_chapter = {draft.chapter_index: draft for draft in drafts}
        parts: list[str] = []
        source_refs: list[dict] = []
        for chapter_index in chapter_indices:
            draft = by_chapter.get(chapter_index)
            if draft is None or not draft.id:
                continue
            selected = [
                chunk
                for chunk in chunks
                if int(chunk.get("chapter_index") or 0) == chapter_index
                and (
                    not chunk.get("source_draft_id")
                    or str(chunk.get("source_draft_id")) == str(draft.id)
                )
                and (
                    not chunk.get("source_content_hash")
                    or chunk.get("source_content_hash") == draft.content_hash
                )
            ]
            for chunk in selected:
                start = chunk.get("start_offset")
                end = chunk.get("end_offset")
                if start is None or end is None:
                    continue
                try:
                    ref = await build_manuscript_range_ref(
                        db,
                        novel_id,
                        draft_id=draft.id,
                        start_offset=int(start),
                        end_offset=int(end),
                        content_mode=content_mode,
                    )
                    read = await read_manuscript_range(
                        db,
                        novel_id,
                        ref,
                        before=0,
                        after=0,
                    )
                except Exception:
                    continue
                parts.append(f"## 第{chapter_index}章\n{read.text}")
                source_refs.append(
                    {
                        "type": "source_range",
                        **asdict(read.source_ref),
                        "scene_span_id": chunk.get("scene_span_id"),
                    }
                )
        return "\n\n".join(parts), source_refs

    @staticmethod
    def _clip_chunks_to_visibility(
        chunks: list[dict],
        *,
        visible_until_chapter: int | None,
        visible_until_offset: int | None,
    ) -> list[dict]:
        """Drop future chunks and clamp the cutoff chapter to its visible offset."""
        if visible_until_offset is not None and visible_until_chapter is None:
            raise ValueError("visible_until_offset_requires_chapter")
        if visible_until_offset is not None and visible_until_offset < 0:
            raise ValueError("visible_until_offset_must_be_non_negative")
        if visible_until_chapter is None:
            return [dict(chunk) for chunk in chunks]

        visible: list[dict] = []
        for original in chunks:
            try:
                chapter_index = int(original.get("chapter_index"))
            except (TypeError, ValueError):
                continue
            if chapter_index > visible_until_chapter:
                continue
            chunk = dict(original)
            if (
                chapter_index == visible_until_chapter
                and visible_until_offset is not None
            ):
                start = chunk.get("start_offset")
                end = chunk.get("end_offset")
                if start is None or end is None:
                    continue
                start_offset = int(start)
                end_offset = min(int(end), visible_until_offset)
                if start_offset >= end_offset:
                    continue
                chunk["end_offset"] = end_offset
            visible.append(chunk)
        return visible

    async def _bind_current_scene_spans(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        content_mode: str,
        scene_chunks: list[dict],
    ) -> list:
        from modules.outline.facade import (
            bind_scene_spans_to_source,
            get_scene_spans_for_scene,
        )
        from modules.writing.facade import list_manuscript_sources

        chapter_indices = sorted(
            {
                int(chunk["chapter_index"])
                for chunk in scene_chunks or []
                if str(chunk.get("chapter_index", "")).isdigit()
            }
        )
        sources = await list_manuscript_sources(
            db,
            novel_id,
            chapter_indices,
            content_mode=content_mode,
        )
        if content_mode == "working":
            canonical_sources = await list_manuscript_sources(
                db,
                novel_id,
                chapter_indices,
                content_mode="canonical",
            )
            for source in canonical_sources:
                await bind_scene_spans_to_source(
                    db,
                    novel_id=novel_id,
                    chapter_index=source.chapter_index,
                    content_mode="canonical",
                    source_draft_id=source.id or "",
                    source_content_hash=source.content_hash,
                    content=source.content or "",
                )
        for source in sources:
            await bind_scene_spans_to_source(
                db,
                novel_id=novel_id,
                chapter_index=source.chapter_index,
                content_mode=content_mode,
                source_draft_id=source.id or "",
                source_content_hash=source.content_hash,
                content=source.content or "",
            )
        return await get_scene_spans_for_scene(
            db,
            novel_id,
            scene_id,
            status_filter=["canonical", "draft"],
            content_mode=content_mode,
        )

    @staticmethod
    def _slice_text(text: str, chunks: list[dict]) -> str:
        if not text or not chunks:
            return ""
        offset_chunks = [
            chunk
            for chunk in chunks
            if chunk.get("start_offset") is not None
            and chunk.get("end_offset") is not None
        ]
        if offset_chunks:
            parts = [
                text[
                    max(0, int(chunk["start_offset"])) : max(
                        0,
                        int(chunk["end_offset"]),
                    )
                ]
                for chunk in offset_chunks
            ]
            return "\n\n".join(part for part in parts if part)
        return ""

    @staticmethod
    def _entry_dict(entry) -> dict:
        return {
            "entry_id": entry.entry_id,
            "asset_type": entry.asset_type,
            "asset_id": entry.asset_id,
            "title": entry.title,
            "summary": entry.summary,
            "group": entry.group,
            "importance": entry.importance,
            "tier": entry.tier,
            "status": entry.status,
            "sensitivity": entry.sensitivity,
            "keywords": entry.keywords,
            "token_count": entry.token_count,
        }

    @staticmethod
    def _brief_dict(brief) -> dict:
        return {
            "scene_id": brief.scene_id,
            "scene_index": brief.scene_index,
            "title": brief.title,
            "goal": brief.goal,
            "core_conflict": brief.core_conflict,
            "emotional_beat": brief.emotional_beat,
            "chapter_indices": brief.chapter_indices,
        }

    @staticmethod
    def _matching_terms(text: str, entries: list[dict]) -> set[str]:
        return {
            term
            for entry in entries
            for term in [entry["title"], *entry["keywords"]]
            if term and str(term) in text
        }

    @staticmethod
    def _world_context(
        entries: list[dict],
        *,
        budget_tokens: int,
    ) -> tuple[str, list[dict]]:
        selected: list[str] = []
        events: list[dict] = []
        seen_groups: set[str] = set()
        used = 0
        for entry in entries:
            if entry["group"] in seen_groups:
                continue
            line = f"- {entry['title']}: {entry['summary']}"
            token_count = estimate_token_count(line)
            if used + token_count > budget_tokens:
                events.append(
                    {
                        "section_key": "world_asset_context",
                        "event_type": "evicted",
                        "reason": "activation_budget",
                        "before_tokens": token_count,
                        "after_tokens": 0,
                        "tier": 2,
                    }
                )
                continue
            selected.append(line)
            seen_groups.add(entry["group"])
            used += token_count
        return "## 世界背景\n" + ("\n".join(selected) or "- 无"), events

    @staticmethod
    def _neighbor_context(briefs: list[dict], evidence: list[dict]) -> str:
        lines = ["## 前序 Scene 摘要"]
        lines.extend(
            "- Scene "
            f"{item['scene_index']} {item.get('title') or ''}: "
            f"{item.get('goal') or item.get('core_conflict') or '无'}"
            for item in briefs
        )
        for item in evidence:
            lines.append(f"## 前序证据 Scene {item['scene_index']}\n{item['text']}")
        return "\n".join(lines)

    @staticmethod
    def _scene_chapter_index(chunks: list[dict]) -> int | None:
        indices = [
            int(chunk["chapter_index"])
            for chunk in chunks or []
            if str(chunk.get("chapter_index", "")).isdigit()
        ]
        return max(indices) if indices else None
