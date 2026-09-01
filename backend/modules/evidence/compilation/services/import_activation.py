"""Deterministic, spoiler-safe context preparation for deep-import Phase 2a."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.token_estimation import estimate_token_count
from modules.evidence.compilation.contracts import ImportContextActivationContract

_ACTIVATION_VERSION = "import-context-v3"
_PREVIOUS_EVIDENCE_LIMIT = 700
_RELATED_CHARACTER_LIMIT = 6
_RELATED_WORLD_OBJECT_LIMIT = 16


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
        from modules.story.facade import (
            get_outline_analysis_context,
            get_scene_context_window,
        )
        from modules.world.facade import (
            get_entity_relations,
            get_world_context,
            list_entity_terms,
        )

        # Kept only for compatibility with the stable facade seam. P13 deliberately
        # does not shrink model input to an application-level token budget.
        _ = budget_tokens

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
            require_complete_mapping=True,
        )
        chapter_indices = self._visible_chapter_indices(
            window.scene.scene_chunks,
            visible_until_chapter=visible_until_chapter,
        )
        outline = None
        if chapter_indices:
            outline = await get_outline_analysis_context(
                db,
                novel_id,
                start_chapter=min(chapter_indices),
                end_chapter=max(chapter_indices),
            )
        outline_context = self._outline_context(outline)
        scene_card = self._scene_card(window.scene)

        world_bundle = await get_world_context(
            db,
            novel_id,
            reveal_mode="author_safe",
            limit=10_000,
            current_chapter=max(chapter_indices) if chapter_indices else None,
            include_review=True,
        )
        entity_terms = await list_entity_terms(db, novel_id, limit=10_000)
        aliases_by_id = {
            str(item.get("id") or ""): [
                str(term).strip()
                for term in item.get("terms", [])[1:]
                if str(term).strip()
            ]
            for item in entity_terms
            if isinstance(item, dict) and item.get("id")
        }
        raw_candidates = [
            self._identity_candidate_source(
                item,
                aliases=aliases_by_id.get(str(item.entity_id), []),
            )
            for item in world_bundle.entities
        ]
        scene_related_ids = self._scene_related_ids(window.scene)
        outline_related_ids = {
            *(
                str(value)
                for value in getattr(outline, "related_character_ids", [])
                if value
            ),
            *(
                str(value)
                for value in getattr(outline, "related_entity_ids", [])
                if value
            ),
        }
        identity_candidates, selected_candidate_sources = (
            self._select_identity_candidates(
                current_text,
                raw_candidates,
                scene_related_ids=scene_related_ids,
                outline_related_ids=outline_related_ids,
            )
        )
        selected_entity_ids = {
            str(item["id"])
            for item in selected_candidate_sources
            if item.get("type") == "world_entity" and item.get("id")
        }
        omitted_sources = [
            {
                "type": "world_entity",
                "id": candidate["entity_id"],
                "reason": "phase2_identity_top_k",
            }
            for candidate in raw_candidates
            if candidate["entity_id"] not in selected_entity_ids
        ]
        relations, _relation_total = await get_entity_relations(
            db,
            novel_id,
            entity_ids=sorted(selected_entity_ids),
        )
        relation_candidates, relation_sources = self._relation_candidates(
            relations,
            selected_candidate_sources,
            novel_id=novel_id,
            before_scene_index=window.scene.scene_index,
            before_chapter_index=max(chapter_indices, default=0),
        )
        world_entries: list[dict] = []
        current_terms = {
            term
            for candidate in identity_candidates
            for term in [candidate["name"], *candidate["aliases"]]
            if term and term in current_text
        }
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
        world_context_text = self._identity_context(identity_candidates)
        world_budget_events: list[dict] = []
        neighbor_context_text = self._neighbor_context(previous_briefs, previous_evidence)
        if not current_sources:
            current_sources = [{"type": "scene", "id": window.scene.id}]
        sources = [
            *current_sources,
            *selected_candidate_sources,
            *relation_sources,
            *self._outline_sources(outline),
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
        warnings: list[str] = []
        if not current_text:
            warnings.append("current_scene_text_unavailable")
        if visible_until_chapter is not None:
            warnings.append("visibility_cutoff_applied")
        context_fingerprint = self._context_fingerprint(
            current_text=current_text,
            current_sources=current_sources,
            scene_card=scene_card,
            outline_context=outline_context,
            identity_candidates=identity_candidates,
            previous_briefs=previous_briefs,
            previous_evidence=previous_evidence,
            relation_candidates=relation_candidates,
        )
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
            scene_card=scene_card,
            outline_context=outline_context,
            identity_candidates=identity_candidates,
            relation_candidates=relation_candidates,
            omitted_sources=omitted_sources,
            context_fingerprint=context_fingerprint,
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
        from modules.story.facade import get_scene_context_window

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
            require_complete_mapping=True,
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
                require_complete_mapping=True,
            )
            if not text:
                continue
            evidence.append(
                {
                    "scene_id": brief.scene_id,
                    "scene_index": brief.scene_index,
                    "text": self._evidence_excerpt(text, current_terms),
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
        require_complete_mapping: bool = False,
    ) -> tuple[str, list[dict]]:
        from dataclasses import asdict

        from modules.writing.facade import (
            build_manuscript_range_ref,
            list_manuscript_sources,
            read_manuscript_range,
        )

        chunks = list(scene_chunks or [])
        if require_complete_mapping and not self._has_complete_visible_span_coverage(
            chunks,
            spans,
            visible_until_chapter=visible_until_chapter,
            visible_until_offset=visible_until_offset,
        ):
            return "", []
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
                parts.append(read.text)
                source_refs.append(
                    {
                        "type": "source_range",
                        **asdict(read.source_ref),
                        "scene_span_id": chunk.get("scene_span_id"),
                    }
                )
        if require_complete_mapping and len(source_refs) != len(chunks):
            return "", []
        return "\n\n".join(parts), source_refs

    @staticmethod
    def _has_complete_visible_span_coverage(
        scene_chunks: list[dict],
        spans: list,
        *,
        visible_until_chapter: int | None,
        visible_until_offset: int | None,
    ) -> bool:
        """Reject mixed precise/imprecise mappings instead of sending partial text."""
        if not spans:
            return True
        visible_chunks = ImportContextActivationService._clip_chunks_to_visibility(
            list(scene_chunks or []),
            visible_until_chapter=visible_until_chapter,
            visible_until_offset=visible_until_offset,
        )
        visible_spans = []
        for span in spans:
            chapter_index = int(span.chapter_index)
            if visible_until_chapter is not None:
                if chapter_index > visible_until_chapter:
                    continue
                if (
                    chapter_index == visible_until_chapter
                    and visible_until_offset is not None
                    and span.start_offset is not None
                    and span.start_offset >= visible_until_offset
                ):
                    continue
            visible_spans.append(span)
        if any(
            span.mapping_status not in {"exact", "reanchored"}
            or span.start_offset is None
            or span.end_offset is None
            or int(span.start_offset) >= int(span.end_offset)
            for span in visible_spans
        ):
            return False
        if visible_chunks and len(visible_spans) < len(visible_chunks):
            return False
        return bool(visible_spans or not visible_chunks)

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
        from modules.story.facade import (
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
    def _scene_card(scene: Any) -> dict:
        meta = dict(getattr(scene, "structure_meta", None) or {})
        return {
            "scene_index": getattr(scene, "scene_index", None),
            "title": getattr(scene, "title", None),
            "goal": getattr(scene, "goal", None),
            "core_conflict": getattr(scene, "core_conflict", None),
            "emotional_beat": getattr(scene, "emotional_beat", None),
            "must_happen": getattr(scene, "must_happen", None),
            "must_not_happen": getattr(scene, "must_not_happen", None),
            "narrative_tag": getattr(scene, "narrative_tag", None),
            "narrative_function": meta.get("narrative_function"),
            "chapter_indices": ImportContextActivationService._scene_chapter_indices(
                getattr(scene, "scene_chunks", None) or []
            ),
        }

    @staticmethod
    def _outline_context(outline: Any | None) -> dict:
        if outline is None:
            return {"scenes": [], "arcs": [], "plot_threads": []}
        return {
            "scenes": [
                ImportContextActivationService._pick(
                    item,
                    "scene_index",
                    "chapter_indices",
                    "title",
                    "goal",
                    "core_conflict",
                    "emotional_beat",
                    "must_happen",
                    "must_not_happen",
                    "narrative_tag",
                    "status",
                )
                for item in outline.scenes
            ],
            "arcs": [
                ImportContextActivationService._pick(
                    item,
                    "title",
                    "arc_index",
                    "start_chapter",
                    "end_chapter",
                    "arc_goal",
                    "core_conflict",
                    "main_opposition",
                    "entry_hook",
                    "midpoint_turn",
                    "climax",
                    "result",
                    "next_hook",
                    "status",
                )
                for item in outline.arcs
            ],
            "plot_threads": [
                ImportContextActivationService._pick(
                    item,
                    "name",
                    "thread_type",
                    "summary",
                    "visible_goal",
                    "hidden_truth",
                    "start_chapter",
                    "planned_payoff_chapter",
                    "current_stage",
                    "reader_known_state",
                    "author_known_state",
                    "status",
                )
                for item in outline.plot_threads
            ],
        }

    @staticmethod
    def _outline_sources(outline: Any | None) -> list[dict]:
        if outline is None:
            return []
        sources: list[dict] = []
        for key, source_type in (
            ("scenes", "scene"),
            ("arcs", "outline_arc"),
            ("plot_threads", "plot_thread"),
        ):
            for item in getattr(outline, key, []) or []:
                if isinstance(item, dict) and item.get("id"):
                    sources.append({"type": source_type, "id": str(item["id"])})
        return sources

    @staticmethod
    def _pick(item: dict, *keys: str) -> dict:
        return {key: item.get(key) for key in keys if item.get(key) is not None}

    @staticmethod
    def _identity_candidate_source(
        entity: Any,
        *,
        aliases: list[str] | None = None,
    ) -> dict:
        candidate_aliases = list(
            dict.fromkeys(
                str(alias).strip()
                for alias in [
                    *(aliases or []),
                    *(getattr(entity, "aliases", None) or []),
                ]
                if str(alias).strip()
            )
        )
        return {
            "entity_id": str(entity.entity_id),
            "entity_type": str(entity.entity_type or "other"),
            "name": str(entity.name or "").strip(),
            "aliases": candidate_aliases,
            "summary": entity.summary,
            "public_info": entity.public_info,
            "importance": float(entity.importance or 0.0),
            "status": entity.status,
        }

    @staticmethod
    def _scene_related_ids(scene: Any) -> set[str]:
        meta = dict(getattr(scene, "structure_meta", None) or {})
        return {
            str(value)
            for key in (
                "related_character_ids",
                "present_character_ids",
                "character_ids",
                "related_entity_ids",
            )
            for value in meta.get(key, [])
            if value
        }

    @staticmethod
    def _select_identity_candidates(
        current_text: str,
        candidates: list[dict],
        *,
        scene_related_ids: set[str],
        outline_related_ids: set[str],
    ) -> tuple[list[dict], list[dict]]:
        ranked: list[tuple[tuple, dict, str]] = []
        for candidate in candidates:
            terms = [candidate["name"], *candidate["aliases"]]
            positions = [current_text.find(term) for term in terms if term]
            mentioned_positions = [position for position in positions if position >= 0]
            entity_id = candidate["entity_id"]
            if mentioned_positions:
                reason = "direct_mention"
                bucket = 0
                first_position = min(mentioned_positions)
            elif entity_id in scene_related_ids:
                reason = "scene_related"
                bucket = 1
                first_position = len(current_text)
            elif entity_id in outline_related_ids:
                reason = "outline_related"
                bucket = 2
                first_position = len(current_text)
            else:
                reason = "importance"
                bucket = 3
                first_position = len(current_text)
            ranked.append(
                (
                    (
                        bucket,
                        first_position,
                        -float(candidate["importance"]),
                        candidate["name"],
                        entity_id,
                    ),
                    candidate,
                    reason,
                )
            )
        ranked.sort(key=lambda value: value[0])

        selected: list[tuple[dict, str]] = []
        remaining_characters = _RELATED_CHARACTER_LIMIT
        remaining_world_objects = _RELATED_WORLD_OBJECT_LIMIT
        for _rank, candidate, reason in ranked:
            if reason != "direct_mention":
                if candidate["entity_type"] == "character":
                    if remaining_characters <= 0:
                        continue
                    remaining_characters -= 1
                else:
                    if remaining_world_objects <= 0:
                        continue
                    remaining_world_objects -= 1
            selected.append((candidate, reason))

        prompt_candidates: list[dict] = []
        audit_sources: list[dict] = []
        for index, (candidate, reason) in enumerate(selected, start=1):
            prompt_ref = f"entity-{index:03d}"
            prompt_candidates.append(
                {
                    "prompt_ref": prompt_ref,
                    "entity_type": candidate["entity_type"],
                    "name": candidate["name"],
                    "aliases": candidate["aliases"],
                    "status": candidate["status"],
                }
            )
            audit_sources.append(
                {
                    "type": "world_entity",
                    "id": candidate["entity_id"],
                    "prompt_ref": prompt_ref,
                    "selection_reason": reason,
                }
            )
        return prompt_candidates, audit_sources

    @staticmethod
    def _identity_context(candidates: list[dict]) -> str:
        return "## 既有身份候选\n" + (
            "\n".join(
                f"- {item['prompt_ref']} {item['entity_type']} {item['name']} "
                f"aliases={item.get('aliases') or []} "
                f"status={item.get('status') or 'unknown'}"
                for item in candidates
            )
            or "- 无"
        )

    @staticmethod
    def _relation_candidates(
        relations: list[Any],
        entity_sources: list[dict],
        *,
        novel_id: str,
        before_scene_index: int,
        before_chapter_index: int,
    ) -> tuple[list[dict], list[dict]]:
        ref_by_entity_id = {
            str(item["id"]): str(item["prompt_ref"])
            for item in entity_sources
            if item.get("id") and item.get("prompt_ref")
        }
        selected: list[tuple[str, str, str, str, Any]] = []
        for relation in relations:
            relation_novel_id = str(
                relation.get("novel_id")
                if isinstance(relation, dict)
                else getattr(relation, "novel_id", "")
            )
            if relation_novel_id and relation_novel_id != str(novel_id):
                raise ValueError("relation novel_id mismatch")
            source_id = str(
                relation.get("source_id")
                if isinstance(relation, dict)
                else getattr(relation, "source_id", "")
            )
            target_id = str(
                relation.get("target_id")
                if isinstance(relation, dict)
                else getattr(relation, "target_id", "")
            )
            status = str(
                relation.get("status")
                if isinstance(relation, dict)
                else getattr(relation, "status", "")
            )
            if (
                source_id not in ref_by_entity_id
                or target_id not in ref_by_entity_id
                or status not in {"canonical", "draft", "candidate"}
            ):
                continue
            value = (
                relation
                if isinstance(relation, dict)
                else relation.model_dump(mode="python")
                if callable(getattr(relation, "model_dump", None))
                else {
                    "review_meta": getattr(relation, "review_meta", None),
                    "description": getattr(relation, "description", None),
                    "strength": getattr(relation, "strength", None),
                    "status": getattr(relation, "status", None),
                }
            )
            review_meta = value.get("review_meta") or {}
            source_scene_index = review_meta.get("scene_index")
            source_chapter_index = review_meta.get("source_chapter_index")
            if (
                not isinstance(source_scene_index, int)
                or isinstance(source_scene_index, bool)
                or source_scene_index >= int(before_scene_index)
                or not isinstance(source_chapter_index, int)
                or isinstance(source_chapter_index, bool)
                or source_chapter_index < 1
                or source_chapter_index > int(before_chapter_index)
            ):
                continue
            relation_id = str(
                relation.get("id")
                if isinstance(relation, dict)
                else getattr(relation, "id", "")
            )
            relation_type = str(
                relation.get("relation_type")
                if isinstance(relation, dict)
                else getattr(relation, "relation_type", "")
            )
            if not relation_id or not relation_type:
                continue
            selected.append(
                (
                    ref_by_entity_id[source_id],
                    ref_by_entity_id[target_id],
                    relation_type,
                    relation_id,
                    value,
                )
            )
        selected.sort(key=lambda item: item[:4])
        prompt_items: list[dict] = []
        audit_sources: list[dict] = []
        for index, (source_ref, target_ref, relation_type, relation_id, value) in (
            enumerate(selected, start=1)
        ):
            prompt_ref = f"relation-{index:03d}"
            prompt_items.append(
                {
                    "prompt_ref": prompt_ref,
                    "source_ref": source_ref,
                    "target_ref": target_ref,
                    "relation_type": relation_type,
                    "description": value.get("description"),
                    "strength": value.get("strength"),
                    "status": value.get("status"),
                }
            )
            audit_sources.append(
                {
                    "type": "world_relation",
                    "id": relation_id,
                    "prompt_ref": prompt_ref,
                }
            )
        return prompt_items, audit_sources

    @staticmethod
    def _evidence_excerpt(text: str, terms: set[str]) -> str:
        positions = [text.find(term) for term in terms if term and term in text]
        if not positions:
            return text[:_PREVIOUS_EVIDENCE_LIMIT]
        center = min(positions)
        start = max(0, center - _PREVIOUS_EVIDENCE_LIMIT // 3)
        end = min(len(text), start + _PREVIOUS_EVIDENCE_LIMIT)
        start = max(0, end - _PREVIOUS_EVIDENCE_LIMIT)
        return text[start:end]

    @staticmethod
    def _visible_chapter_indices(
        chunks: list[dict],
        *,
        visible_until_chapter: int | None,
    ) -> list[int]:
        indices = ImportContextActivationService._scene_chapter_indices(chunks)
        if visible_until_chapter is None:
            return indices
        return [index for index in indices if index <= visible_until_chapter]

    @staticmethod
    def _scene_chapter_indices(chunks: list[dict]) -> list[int]:
        return sorted(
            {
                int(chunk["chapter_index"])
                for chunk in chunks or []
                if str(chunk.get("chapter_index", "")).isdigit()
            }
        )

    @staticmethod
    def _context_fingerprint(
        *,
        current_text: str,
        current_sources: list[dict],
        scene_card: dict,
        outline_context: dict,
        identity_candidates: list[dict],
        previous_briefs: list[dict],
        previous_evidence: list[dict],
        relation_candidates: list[dict] | None = None,
    ) -> str:
        payload = {
            "activation_version": _ACTIVATION_VERSION,
            "current_scene_hash": hashlib.sha256(current_text.encode()).hexdigest(),
            "current_sources": current_sources,
            "scene_card": scene_card,
            "outline_context": outline_context,
            "identity_candidates": identity_candidates,
            "previous_briefs": previous_briefs,
            "previous_evidence": previous_evidence,
            "relation_candidates": relation_candidates or [],
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()

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
