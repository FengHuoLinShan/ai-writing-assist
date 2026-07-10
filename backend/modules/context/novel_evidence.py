"""Deterministic grep/search/read/inspect/trace orchestration."""

from __future__ import annotations

import uuid
from dataclasses import asdict, replace

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.context.contracts import EvidenceHitContract, VisibilityContextContract
from modules.context.evidence_repository import EvidenceLinkRepository
from modules.writing.contracts import SourceRangeRefContract
from shared.target_ref import TargetRef, normalize_target_ref


class NovelEvidenceService:
    def __init__(self, evidence_repo: EvidenceLinkRepository | None = None) -> None:
        self._evidence_repo = evidence_repo or EvidenceLinkRepository()

    async def grep(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        pattern: str,
        content_mode: str,
        visibility: VisibilityContextContract,
        chapter_from: int | None = None,
        chapter_to: int | None = None,
        case_sensitive: bool = False,
        skip: int = 0,
        limit: int = 20,
    ) -> dict:
        from modules.writing.facade import grep_manuscript

        self._require_visibility(visibility)
        visibility, visibility_warnings = await self._resolve_visibility_cursor(
            db,
            novel_id=novel_id,
            content_mode=content_mode,
            visibility=visibility,
        )
        effective_to = _effective_chapter_to(chapter_to, visibility)
        visible_end_offsets = None
        if visibility.cutoff_chapter and visibility.cutoff_offset is not None:
            visible_end_offsets = {visibility.cutoff_chapter: visibility.cutoff_offset}
        hits, total, missing = await grep_manuscript(
            db,
            novel_id,
            pattern,
            content_mode=content_mode,
            chapter_from=chapter_from,
            chapter_to=effective_to,
            case_sensitive=case_sensitive,
            visible_end_offsets=visible_end_offsets,
            skip=skip,
            limit=limit,
        )
        result: list[EvidenceHitContract] = []
        for hit in hits:
            if not _source_visible(asdict(hit.source_ref), visibility):
                continue
            scene_refs = await self._scene_refs(db, novel_id, hit.source_ref)
            object_refs = await self._object_refs_for_source(db, novel_id, hit.source_ref)
            result.append(
                EvidenceHitContract(
                    kind="manuscript",
                    title=hit.title or f"第 {hit.source_ref.chapter_index} 章",
                    snippet=hit.snippet,
                    source_ref=asdict(hit.source_ref),
                    chapter_index=hit.source_ref.chapter_index,
                    scene_refs=scene_refs,
                    object_refs=object_refs,
                    visibility_decision=_visibility_decision(visibility),
                )
            )
        warnings = list(visibility_warnings)
        if missing and content_mode == "canonical":
            warnings.append("部分章节没有已发布正文，未回退到工作稿")
        return {
            "hits": [asdict(item) for item in result],
            "total": total,
            "warnings": warnings,
            "degraded": False,
            "missing_chapters": missing,
        }

    async def search(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        query: str,
        content_mode: str,
        visibility: VisibilityContextContract,
        scopes: list[str],
        chapter_from: int | None = None,
        chapter_to: int | None = None,
        top_k: int = 12,
    ) -> dict:
        self._require_visibility(visibility)
        visibility, visibility_warnings = await self._resolve_visibility_cursor(
            db,
            novel_id=novel_id,
            content_mode=content_mode,
            visibility=visibility,
        )
        hits: list[EvidenceHitContract] = []
        warnings: list[str] = list(visibility_warnings)
        degraded = False
        if "manuscript" in scopes:
            (
                manuscript,
                manuscript_warnings,
                manuscript_degraded,
            ) = await self._search_manuscript(
                db,
                novel_id=novel_id,
                query=query,
                content_mode=content_mode,
                visibility=visibility,
                chapter_from=chapter_from,
                chapter_to=chapter_to,
                top_k=top_k,
            )
            hits.extend(manuscript)
            warnings.extend(manuscript_warnings)
            degraded = degraded or manuscript_degraded
        if "world" in scopes:
            hits.extend(
                await self._search_world(
                    db,
                    novel_id=novel_id,
                    query=query,
                    content_mode=content_mode,
                    visibility=visibility,
                    limit=top_k,
                )
            )
        if "outline" in scopes:
            outline, outline_warnings, outline_degraded = await self._search_outline(
                db,
                novel_id=novel_id,
                query=query,
                content_mode=content_mode,
                visibility=visibility,
                limit=top_k,
            )
            hits.extend(outline)
            warnings.extend(outline_warnings)
            degraded = degraded or outline_degraded
        hits.sort(key=lambda item: item.score or 0.0, reverse=True)
        hits = hits[:top_k]
        return {
            "hits": [asdict(item) for item in hits],
            "total": len(hits),
            "warnings": list(dict.fromkeys(warnings)),
            "degraded": degraded,
            "missing_chapters": [],
        }

    async def read(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        source_ref: SourceRangeRefContract,
        visibility: VisibilityContextContract,
        before: int = 3,
        after: int = 3,
    ) -> dict:
        self._require_visibility(visibility)
        visibility, visibility_warnings = await self._resolve_visibility_cursor(
            db,
            novel_id=novel_id,
            content_mode=source_ref.content_mode,
            visibility=visibility,
        )
        if not _source_visible(asdict(source_ref), visibility):
            raise ValueError("来源超出当前可见截止位置")
        from modules.writing.facade import read_manuscript_range

        item = await read_manuscript_range(
            db,
            novel_id,
            source_ref,
            before=before,
            after=after,
            max_end_offset=(
                visibility.cutoff_offset
                if visibility.mode != "author"
                and source_ref.chapter_index == visibility.cutoff_chapter
                else None
            ),
        )
        return {
            "source_ref": asdict(item.source_ref),
            "title": item.title,
            "text": item.text,
            "highlight_start": item.highlight_start,
            "highlight_end": item.highlight_end,
            "scene_refs": await self._scene_refs(db, novel_id, item.source_ref),
            "object_refs": await self._object_refs_for_source(
                db, novel_id, item.source_ref
            ),
            "warnings": visibility_warnings,
            "degraded": bool(visibility_warnings),
            "index_fresh": True,
            "visibility_decision": _visibility_decision(visibility),
        }

    async def inspect(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        target_ref: TargetRef | dict,
        content_mode: str,
        visibility: VisibilityContextContract,
    ) -> dict:
        self._require_visibility(visibility)
        visibility, cursor_warnings = await self._resolve_visibility_cursor(
            db,
            novel_id=novel_id,
            content_mode=content_mode,
            visibility=visibility,
        )
        target = normalize_target_ref(target_ref)
        item, warnings = await self._visible_target(
            db,
            novel_id=novel_id,
            target=target,
            content_mode=content_mode,
            visibility=visibility,
        )
        links = await self._evidence_repo.list_for_target(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            target_hash=target.target_hash(),
            claim_path=target.target_path,
            statuses=("active",),
        )
        visible_links = []
        index_fresh = True
        for link in links:
            source = dict(link.source_ref or {})
            if source.get("content_mode") != content_mode or not _source_visible(
                source, visibility
            ):
                continue
            try:
                await self.read(
                    db,
                    novel_id=novel_id,
                    source_ref=SourceRangeRefContract(**source),
                    visibility=visibility,
                    before=0,
                    after=0,
                )
            except Exception:
                warnings.append(f"证据 {link.id} 的原文引用已失效")
                index_fresh = False
                continue
            visible_links.append(link)
        all_warnings = [*cursor_warnings, *warnings]
        return {
            "target_ref": target.canonical_dict(),
            "visible": item is not None,
            "item": item,
            "evidence_count": len(visible_links),
            "index_fresh": index_fresh,
            "warnings": all_warnings,
            "visibility_decision": _visibility_decision(
                visibility,
                visible=item is not None,
            ),
            "degraded": bool(all_warnings),
        }

    async def trace(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        target_ref: TargetRef | dict,
        claim_path: str,
        content_mode: str,
        visibility: VisibilityContextContract,
    ) -> dict:
        self._require_visibility(visibility)
        visibility, cursor_warnings = await self._resolve_visibility_cursor(
            db,
            novel_id=novel_id,
            content_mode=content_mode,
            visibility=visibility,
        )
        target = normalize_target_ref(target_ref)
        warnings: list[str] = list(cursor_warnings)
        supported_target_types = {
            "world_entity",
            "entity",
            "core_entity",
            "character_knowledge",
            "outline_scene",
        }
        if target.target_type in supported_target_types:
            visible_target, target_warnings = await self._visible_target(
                db,
                novel_id=novel_id,
                target=target,
                content_mode=content_mode,
                visibility=visibility,
            )
            warnings.extend(target_warnings)
            if visible_target is None:
                return {
                    "target_ref": target.canonical_dict(),
                    "claim_path": claim_path,
                    "links": [],
                    "index_fresh": True,
                    "warnings": warnings,
                    "visibility_decision": _visibility_decision(
                        visibility,
                        visible=False,
                    ),
                    "degraded": bool(warnings),
                }
        elif visibility.mode != "author":
            warnings.append("当前视角无法校验该目标，证据链已保守排除")
            return {
                "target_ref": target.canonical_dict(),
                "claim_path": claim_path,
                "links": [],
                "index_fresh": True,
                "warnings": warnings,
                "visibility_decision": _visibility_decision(
                    visibility,
                    visible=False,
                ),
                "degraded": True,
            }
        links = await self._evidence_repo.list_for_target(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            target_hash=target.target_hash(),
            claim_path=claim_path,
            statuses=("active", "needs_review"),
        )
        visible_links: list[dict] = []
        index_fresh = True
        for link in links:
            source = dict(link.source_ref or {})
            if link.status == "needs_review":
                if visibility.mode != "author":
                    warnings.append("未定位原文的证据已按当前视角保守排除")
                    continue
                visible_links.append(
                    {
                        "id": str(link.id),
                        "evidence_type": link.evidence_type,
                        "precision": link.precision,
                        "status": link.status,
                        "source_ref": source,
                        "provenance": dict(link.provenance or {}),
                        "read": None,
                    }
                )
                warnings.append(f"证据 {link.id} 尚未定位到可见原文")
                continue
            if source.get("content_mode") != content_mode:
                continue
            if not _source_visible(source, visibility):
                continue
            try:
                read = await self.read(
                    db,
                    novel_id=novel_id,
                    source_ref=SourceRangeRefContract(**source),
                    visibility=visibility,
                    before=1,
                    after=1,
                )
            except Exception:
                warnings.append(f"证据 {link.id} 的原文引用已失效")
                index_fresh = False
                continue
            visible_links.append(
                {
                    "id": str(link.id),
                    "evidence_type": link.evidence_type,
                    "precision": link.precision,
                    "status": link.status,
                    "source_ref": source,
                    "provenance": dict(link.provenance or {}),
                    "read": read,
                }
            )
        return {
            "target_ref": target.canonical_dict(),
            "claim_path": claim_path,
            "links": visible_links,
            "index_fresh": index_fresh,
            "warnings": warnings,
            "visibility_decision": _visibility_decision(visibility),
            "degraded": bool(warnings),
        }

    async def record_link(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        target_ref: TargetRef | dict,
        source_ref: SourceRangeRefContract | dict,
        claim_path: str = "",
        evidence_type: str = "supports",
        precision: str = "range",
        status: str = "active",
        provenance: dict | None = None,
    ) -> dict:
        target = normalize_target_ref(target_ref)
        source = (
            source_ref
            if isinstance(source_ref, SourceRangeRefContract)
            else SourceRangeRefContract(**source_ref)
        )
        from modules.writing.facade import read_manuscript_range

        await read_manuscript_range(db, novel_id, source, before=0, after=0)
        item = await self._evidence_repo.create(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            target_ref=target.canonical_dict(),
            target_hash=target.target_hash(),
            claim_path=claim_path or target.target_path,
            evidence_type=evidence_type,
            source_ref=asdict(source),
            precision=precision,
            status=status,
            provenance=provenance or {},
        )
        return {"id": str(item.id), "target_ref": item.target_ref}

    async def record_unresolved_link(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        target_ref: TargetRef | dict,
        claim_path: str = "",
        evidence_type: str = "supports",
        provenance: dict | None = None,
    ) -> dict:
        target = normalize_target_ref(target_ref)
        item = await self._evidence_repo.create(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            target_ref=target.canonical_dict(),
            target_hash=target.target_hash(),
            claim_path=claim_path or target.target_path,
            evidence_type=evidence_type,
            source_ref={},
            precision="unresolved",
            status="needs_review",
            provenance=provenance or {},
        )
        return {"id": str(item.id), "target_ref": item.target_ref}

    async def locate_scene_quote(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        quote: str,
        content_mode: str = "working",
        visible_until_chapter: int | None = None,
        visible_until_offset: int | None = None,
    ) -> tuple[SourceRangeRefContract | None, str | None]:
        quote = str(quote or "").strip()
        if not quote:
            return None, "missing_quote"
        from modules.outline.facade import (
            bind_scene_spans_to_source,
            get_scene_contract,
            get_scene_spans_for_scene,
        )
        from modules.writing.facade import grep_manuscript, list_manuscript_sources

        try:
            scene = await get_scene_contract(db, novel_id, scene_id)
        except ValidationError:
            return None, "invalid_scene_id"
        if scene is None:
            return None, "scene_not_found"
        scene_chapters = sorted(
            {
                int(chunk["chapter_index"])
                for chunk in scene.scene_chunks or []
                if str(chunk.get("chapter_index", "")).isdigit()
            }
        )
        if visible_until_offset is not None and visible_until_chapter is None:
            return None, "visible_until_offset_requires_chapter"
        if visible_until_chapter is not None:
            scene_chapters = [
                chapter for chapter in scene_chapters if chapter <= visible_until_chapter
            ]
        if content_mode == "working":
            canonical_sources = await list_manuscript_sources(
                db,
                novel_id,
                scene_chapters,
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
        mode_sources = await list_manuscript_sources(
            db,
            novel_id,
            scene_chapters,
            content_mode=content_mode,
        )
        for source in mode_sources:
            await bind_scene_spans_to_source(
                db,
                novel_id=novel_id,
                chapter_index=source.chapter_index,
                content_mode=content_mode,
                source_draft_id=source.id or "",
                source_content_hash=source.content_hash,
                content=source.content or "",
            )

        spans = await get_scene_spans_for_scene(
            db,
            novel_id,
            scene_id,
            content_mode=content_mode,
        )
        precise = [
            span
            for span in spans
            if span.mapping_status in {"exact", "reanchored"}
            and span.start_offset is not None
            and span.end_offset is not None
            and span.source_draft_id
            and span.source_content_hash
            and (
                visible_until_chapter is None
                or span.chapter_index <= visible_until_chapter
            )
            and (
                visible_until_chapter is None
                or visible_until_offset is None
                or span.chapter_index < visible_until_chapter
                or int(span.start_offset) < visible_until_offset
            )
        ]
        chapters = sorted({span.chapter_index for span in precise})
        if not chapters:
            return None, "scene_span_unresolved"
        sources = await list_manuscript_sources(
            db,
            novel_id,
            chapters,
            content_mode=content_mode,
        )
        current = {source.chapter_index: source for source in sources}
        hits, _, _ = await grep_manuscript(
            db,
            novel_id,
            quote,
            content_mode=content_mode,
            chapter_from=min(chapters),
            chapter_to=max(chapters),
            case_sensitive=True,
            visible_end_offsets=(
                {visible_until_chapter: visible_until_offset}
                if visible_until_chapter is not None and visible_until_offset is not None
                else None
            ),
            limit=100,
        )
        matches: list[SourceRangeRefContract] = []
        for hit in hits:
            source = current.get(hit.source_ref.chapter_index)
            if source is None:
                continue
            if (
                source.id != hit.source_ref.draft_id
                or source.content_hash != hit.source_ref.source_hash
            ):
                continue
            if any(
                span.chapter_index == hit.source_ref.chapter_index
                and span.source_draft_id == hit.source_ref.draft_id
                and span.source_content_hash == hit.source_ref.source_hash
                and int(span.start_offset or 0) <= hit.source_ref.start_offset
                and min(
                    int(span.end_offset or 0),
                    (
                        visible_until_offset
                        if visible_until_chapter is not None
                        and visible_until_offset is not None
                        and span.chapter_index == visible_until_chapter
                        else int(span.end_offset or 0)
                    ),
                )
                >= hit.source_ref.end_offset
                for span in precise
            ):
                matches.append(hit.source_ref)
        unique = {
            (
                ref.draft_id,
                ref.start_offset,
                ref.end_offset,
                ref.range_hash,
            ): ref
            for ref in matches
        }
        if len(unique) == 1:
            return next(iter(unique.values())), None
        if not unique:
            return None, "quote_not_found_in_visible_scene"
        return None, "quote_ambiguous_in_visible_scene"

    async def _search_manuscript(self, db, **kwargs):
        from modules.rag.facade import get_index_freshness, retrieve
        from modules.writing.facade import build_manuscript_range_ref

        visibility = kwargs["visibility"]
        result = await retrieve(
            db,
            kwargs["novel_id"],
            kwargs["query"],
            content_mode=kwargs["content_mode"],
            visible_until_chapter=_effective_chapter_to(
                kwargs.get("chapter_to"), visibility
            ),
            top_k=kwargs["top_k"],
            mode="search",
        )
        hits: list[EvidenceHitContract] = []
        warnings = list(result.warnings or [])
        freshness = await get_index_freshness(
            db,
            kwargs["novel_id"],
            content_mode=kwargs["content_mode"],
            chapter_from=kwargs.get("chapter_from"),
            chapter_to=_effective_chapter_to(
                kwargs.get("chapter_to"),
                visibility,
            ),
        )
        if freshness["stale"]:
            label = "工作稿" if kwargs["content_mode"] == "working" else "已发布正文"
            warnings.append(f"{label}索引更新中/需重建，过期片段不会返回")
        from modules.writing.facade import list_manuscript_sources

        chapter_indices = sorted(
            {
                int(chunk.chapter_index)
                for chunk in result.chunks
                if chunk.chapter_index is not None
            }
        )
        current_sources = await list_manuscript_sources(
            db,
            kwargs["novel_id"],
            chapter_indices,
            content_mode=kwargs["content_mode"],
        )
        current_by_chapter = {source.chapter_index: source for source in current_sources}
        for chunk in result.chunks:
            if (
                chunk.source_type != "chapter_text"
                or not chunk.source_id
                or not chunk.source_content_hash
                or chunk.start_offset is None
                or chunk.end_offset is None
            ):
                continue
            if (
                kwargs.get("chapter_from")
                and (chunk.chapter_index or 0) < kwargs["chapter_from"]
            ):
                continue
            current = current_by_chapter.get(chunk.chapter_index or 0)
            if (
                current is None
                or current.id != chunk.source_id
                or current.content_hash != chunk.source_content_hash
            ):
                warnings.append("索引未跟上当前正文版本，旧片段已剔除")
                continue
            try:
                source_ref = await build_manuscript_range_ref(
                    db,
                    kwargs["novel_id"],
                    draft_id=chunk.source_id,
                    start_offset=chunk.start_offset,
                    end_offset=chunk.end_offset,
                    content_mode=kwargs["content_mode"],
                )
            except Exception:
                continue
            if source_ref.source_hash != chunk.source_content_hash:
                warnings.append("检测到过期索引片段，已从结果中剔除")
                continue
            if not _source_visible(asdict(source_ref), visibility):
                continue
            read = await self.read(
                db,
                novel_id=kwargs["novel_id"],
                source_ref=source_ref,
                visibility=visibility,
                before=0,
                after=0,
            )
            hits.append(
                EvidenceHitContract(
                    kind="manuscript",
                    title=read["title"] or f"第 {source_ref.chapter_index} 章",
                    snippet=read["text"][:500],
                    source_ref=asdict(source_ref),
                    chapter_index=source_ref.chapter_index,
                    score=chunk.score,
                    scene_refs=read["scene_refs"],
                    object_refs=read["object_refs"],
                    visibility_decision=_visibility_decision(visibility),
                )
            )
        return hits, warnings, bool(result.degraded or warnings)

    async def _search_world(
        self, db, *, novel_id, query, content_mode, visibility, limit
    ):
        from modules.world.facade import list_entities

        items = await list_entities(
            db,
            novel_id,
            statuses=["canonical", "draft", "candidate"],
            limit=max(limit * 4, 50),
        )
        needle = query.lower()
        hits = []
        for item in items:
            target = {
                "target_type": "world_entity",
                "target_id": str(item.get("entity_id") or item.get("id") or ""),
                "target_path": "",
            }
            inspected = await self.inspect(
                db,
                novel_id=novel_id,
                target_ref=target,
                content_mode=content_mode,
                visibility=visibility,
            )
            if not inspected["visible"]:
                continue
            visible_item = inspected["item"] or {}
            visible_text = "\n".join(
                str(visible_item.get(key) or "")
                for key in (
                    "name",
                    "summary",
                    "public_info",
                    "reader_reveal_content",
                )
            )
            if needle not in visible_text.lower():
                continue
            hits.append(
                EvidenceHitContract(
                    kind="world_object",
                    title=str(visible_item.get("name") or item.get("name") or "世界对象"),
                    snippet=str(
                        visible_item.get("summary")
                        or visible_item.get("public_info")
                        or ""
                    ),
                    target_ref=target,
                    object_refs=[target],
                    score=1.0,
                    visibility_decision=inspected["visibility_decision"],
                )
            )
            if len(hits) >= limit:
                break
        return hits

    async def _search_outline(
        self, db, *, novel_id, query, content_mode, visibility, limit
    ):
        from modules.outline.facade import (
            get_scene_summary_checkpoint,
            get_scenes_by_novel,
            rebuild_scene_summary_checkpoint,
        )

        scenes = await get_scenes_by_novel(
            db, novel_id, status_filter=["canonical", "draft"]
        )
        needle = query.lower()
        hits = []
        warnings: list[str] = []
        degraded = False
        for scene in scenes:
            chapters = [
                int(value)
                for value in scene.get("chapter_ids") or []
                if str(value).isdigit()
            ]
            if (
                visibility.cutoff_chapter is not None
                and chapters
                and min(chapters) > visibility.cutoff_chapter
            ):
                continue
            target = {
                "target_type": "outline_scene",
                "target_id": str(scene["id"]),
                "target_path": "",
            }
            if visibility.mode == "author":
                text = "\n".join(
                    str(scene.get(key) or "")
                    for key in ("title", "goal", "core_conflict")
                )
                title = str(scene.get("title") or f"Scene {scene.get('scene_index')}")
            else:
                checkpoint = await get_scene_summary_checkpoint(
                    db,
                    novel_id=novel_id,
                    scene_id=str(scene["id"]),
                    content_mode=content_mode,
                    through_chapter=visibility.cutoff_chapter or 1,
                    through_offset=visibility.cutoff_offset,
                )
                if checkpoint is None:
                    checkpoint = await rebuild_scene_summary_checkpoint(
                        db,
                        novel_id=novel_id,
                        scene_id=str(scene["id"]),
                        content_mode=content_mode,
                        through_chapter=visibility.cutoff_chapter or 1,
                        through_offset=visibility.cutoff_offset,
                    )
                if checkpoint is None:
                    continue
                if checkpoint.source == "extractive":
                    warnings.append("Scene 摘要 checkpoint 不可用，已降级为可见原文摘录")
                    degraded = True
                text = checkpoint.summary
                title = f"Scene {scene.get('scene_index')}"
            if needle not in text.lower():
                continue
            hits.append(
                EvidenceHitContract(
                    kind="outline_asset",
                    title=title,
                    snippet=text[:500],
                    target_ref=target,
                    scene_refs=[target],
                    score=1.0,
                    visibility_decision=_visibility_decision(visibility),
                )
            )
            if len(hits) >= limit:
                break
        return hits, list(dict.fromkeys(warnings)), degraded

    async def _visible_target(self, db, *, novel_id, target, content_mode, visibility):
        warnings: list[str] = []
        if target.target_type in {"world_entity", "entity", "core_entity"}:
            from modules.world.facade import get_world_context

            reveal_mode = "author_only" if visibility.mode == "author" else "author_safe"
            bundle = await get_world_context(
                db,
                novel_id,
                entity_ids=[target.target_id],
                reveal_mode=reveal_mode,
                current_chapter=visibility.cutoff_chapter,
            )
            entities = [item.model_dump() for item in bundle.entities]
            item = entities[0] if entities else None
            if (
                visibility.mode != "author"
                and item is not None
                and item.get("status") != "canonical"
            ):
                warnings.append("非正史对象不对读者/角色视角开放")
                return None, warnings
            if visibility.mode != "author" and item is not None:
                from modules.outline.facade import get_reader_reveal_decision

                reveal = await get_reader_reveal_decision(
                    db,
                    novel_id=novel_id,
                    target_type="entity",
                    target_id=target.target_id,
                    cutoff_chapter=visibility.cutoff_chapter or 0,
                )
                if reveal.has_policy:
                    item["hidden_truth"] = None
                    item["reader_reveal_content"] = reveal.reveal_content
                    if not reveal.revealed:
                        item["summary"] = None
                        warnings.append("对象的揭示计划尚未到达可见阶段")
                else:
                    item["hidden_truth"] = None
                    item["summary"] = item.get("public_info")
            if visibility.mode == "character" and item is not None:
                from modules.world.facade import filter_context_by_character_knowledge

                entity_type = str(item.get("entity_type") or "")
                knowledge_target_type = (
                    entity_type
                    if entity_type in {"character", "location", "event"}
                    else "entity"
                )
                filtered = await filter_context_by_character_knowledge(
                    db,
                    novel_id,
                    visibility.character_id or "",
                    [
                        {
                            **item,
                            "target_type": knowledge_target_type,
                            "target_id": target.target_id,
                        }
                    ],
                    visible_until_chapter=visibility.cutoff_chapter,
                )
                item = filtered[0] if filtered else None
                if item is not None and item.get("visibility_source") == "public_info":
                    warnings.append("当前截止位置无可判定的人物知识，仅返回公开基线")
            return item, warnings
        if target.target_type == "character_knowledge":
            from modules.world.facade import get_character_knowledge_entries

            entries = await get_character_knowledge_entries(db, novel_id)
            item = next(
                (entry for entry in entries if str(entry.get("id")) == target.target_id),
                None,
            )
            if item is None:
                return None, warnings
            if visibility.mode == "reader":
                warnings.append("人物私有知识不直接暴露给读者视角")
                return None, warnings
            if visibility.mode == "character" and str(item.get("character_id")) != str(
                visibility.character_id
            ):
                warnings.append("人物知识不属于当前视角人物")
                return None, warnings
            learned = item.get("source_chapter_index")
            public_baseline = bool(item.get("is_public_baseline"))
            if visibility.mode != "author" and (
                (learned is None and not public_baseline)
                or (learned is not None and learned >= (visibility.cutoff_chapter or 0))
            ):
                warnings.append("人物知识缺少可判定的同章先后位置，已按保守可见性排除")
                return None, warnings
            return item, warnings
        if target.target_type == "outline_scene":
            from modules.outline.facade import (
                get_scene_contract,
                get_scene_summary_checkpoint,
                rebuild_scene_summary_checkpoint,
            )

            scene = await get_scene_contract(db, novel_id, target.target_id)
            if scene is None:
                return None, warnings
            if visibility.mode == "author":
                return asdict(scene), warnings
            checkpoint = await get_scene_summary_checkpoint(
                db,
                novel_id=novel_id,
                scene_id=target.target_id,
                content_mode=content_mode,
                through_chapter=visibility.cutoff_chapter or 1,
                through_offset=visibility.cutoff_offset,
            )
            if checkpoint is None:
                checkpoint = await rebuild_scene_summary_checkpoint(
                    db,
                    novel_id=novel_id,
                    scene_id=target.target_id,
                    content_mode=content_mode,
                    through_chapter=visibility.cutoff_chapter or 1,
                    through_offset=visibility.cutoff_offset,
                )
            if checkpoint is None:
                warnings.append("无精确可见原文，未回退到完整 Scene 卡")
                return None, warnings
            if checkpoint.source == "extractive":
                warnings.append("Scene 摘要 checkpoint 不可用，已降级为可见原文摘录")
            return asdict(checkpoint), warnings
        return None, ["不支持的 target_type"]

    async def resolve_visibility_cursor(
        self,
        db,
        *,
        novel_id: str,
        content_mode: str,
        visibility: VisibilityContextContract,
    ) -> tuple[VisibilityContextContract, list[str]]:
        """Resolve a Scene cursor to a conservative, version-bound text offset."""
        self._require_visibility(visibility)
        return await self._resolve_visibility_cursor(
            db,
            novel_id=novel_id,
            content_mode=content_mode,
            visibility=visibility,
        )

    async def _resolve_visibility_cursor(
        self,
        db,
        *,
        novel_id: str,
        content_mode: str,
        visibility: VisibilityContextContract,
    ) -> tuple[VisibilityContextContract, list[str]]:
        if visibility.mode == "author" or not visibility.cutoff_scene_id:
            return visibility, []
        from modules.outline.facade import get_scene_spans_for_scene
        from modules.writing.facade import list_manuscript_sources

        chapter = visibility.cutoff_chapter or 0
        spans = await get_scene_spans_for_scene(
            db,
            novel_id,
            visibility.cutoff_scene_id,
            content_mode=content_mode,
        )
        sources = await list_manuscript_sources(
            db,
            novel_id,
            [chapter],
            content_mode=content_mode,
        )
        source = sources[0] if sources else None
        end_offsets = [
            int(span.end_offset)
            for span in spans
            if span.chapter_index == chapter
            and span.mapping_status in {"exact", "reanchored"}
            and span.end_offset is not None
            and source is not None
            and span.source_draft_id == source.id
            and span.source_content_hash == source.content_hash
        ]
        if not end_offsets:
            return (
                replace(visibility, cutoff_offset=0),
                ["截止 Scene 缺少精确版本绑定，同章正文已保守排除"],
            )
        scene_end = max(end_offsets)
        cutoff = (
            min(scene_end, visibility.cutoff_offset)
            if visibility.cutoff_offset is not None
            else scene_end
        )
        return replace(visibility, cutoff_offset=cutoff), []

    @staticmethod
    def _require_visibility(visibility: VisibilityContextContract) -> None:
        if visibility.mode not in {"author", "reader", "character"}:
            raise ValueError("不支持的可见性视角")
        if visibility.mode in {"reader", "character"} and not visibility.cutoff_chapter:
            raise ValueError("reader/character 视角必须提供截止章")
        if visibility.mode == "character" and not visibility.character_id:
            raise ValueError("character 视角必须提供人物 ID")

    async def _scene_refs(self, db, novel_id, source_ref):
        from modules.outline.facade import get_scene_spans_by_chapter

        spans = await get_scene_spans_by_chapter(
            db,
            novel_id,
            source_ref.chapter_index,
            content_mode=source_ref.content_mode,
        )
        return [
            {
                "target_type": "outline_scene",
                "target_id": span.scene_id,
                "target_path": "",
                "scene_span_id": span.id,
            }
            for span in spans
            if span.mapping_status in {"exact", "reanchored"}
            and span.source_draft_id == source_ref.draft_id
            and span.source_content_hash == source_ref.source_hash
            and span.start_offset is not None
            and span.end_offset is not None
            and source_ref.start_offset < span.end_offset
            and source_ref.end_offset > span.start_offset
        ]

    async def _object_refs_for_source(self, db, novel_id, source_ref):
        links = await self._evidence_repo.list_for_source_chapter(
            db,
            novel_id=uuid.UUID(str(novel_id)),
            chapter_index=source_ref.chapter_index,
        )
        result = []
        for link in links:
            raw = link.source_ref or {}
            if raw.get("draft_id") != source_ref.draft_id:
                continue
            if int(raw.get("start_offset") or 0) >= source_ref.end_offset:
                continue
            if int(raw.get("end_offset") or 0) <= source_ref.start_offset:
                continue
            result.append(dict(link.target_ref or {}))
        return result


def _effective_chapter_to(
    chapter_to: int | None,
    visibility: VisibilityContextContract,
) -> int | None:
    if visibility.mode == "author" or visibility.cutoff_chapter is None:
        return chapter_to
    if chapter_to is None:
        return visibility.cutoff_chapter
    return min(chapter_to, visibility.cutoff_chapter)


def _source_visible(source_ref: dict, visibility: VisibilityContextContract) -> bool:
    if visibility.mode == "author":
        return True
    chapter = int(source_ref.get("chapter_index") or 0)
    cutoff = int(visibility.cutoff_chapter or 0)
    if chapter < cutoff:
        return True
    if chapter > cutoff:
        return False
    if visibility.cutoff_offset is None:
        return True
    return int(source_ref.get("end_offset") or 0) <= visibility.cutoff_offset


def _visibility_decision(
    visibility: VisibilityContextContract,
    *,
    visible: bool = True,
) -> dict:
    return {
        "mode": visibility.mode,
        "visible": visible,
        "cutoff_chapter": visibility.cutoff_chapter,
        "cutoff_scene_id": visibility.cutoff_scene_id,
        "cutoff_offset": visibility.cutoff_offset,
        "character_id": visibility.character_id,
    }
