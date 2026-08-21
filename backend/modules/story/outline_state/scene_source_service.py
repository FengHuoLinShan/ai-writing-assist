"""Version-bound SceneSpan anchoring and spoiler-safe summary checkpoints."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.contracts import (
    SceneSpanContract,
    SceneSummaryCheckpointContract,
)
from modules.story.outline_state.models import SceneSpan, SceneSummaryCheckpoint
from modules.story.outline_state.repositories import SceneRepository

ANCHOR_EXCERPT_LIMIT = 256
CHECKPOINT_SUMMARY_LIMIT = 1200


class SceneSourceService:
    async def bind_chapter_spans(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
        source_draft_id: str,
        source_content_hash: str,
        content: str,
    ) -> list[SceneSpanContract]:
        nid = uuid.UUID(str(novel_id))
        draft_id = uuid.UUID(str(source_draft_id))
        repo = SceneRepository()
        spans = await repo.get_scene_spans_by_chapter(
            db,
            nid,
            chapter_index,
            statuses=("draft", "canonical"),
            content_mode=content_mode,
        )
        if not spans and content_mode == "working":
            canonical = await repo.get_scene_spans_by_chapter(
                db,
                nid,
                chapter_index,
                statuses=("draft", "canonical"),
                content_mode="canonical",
            )
            spans = [self._clone_for_working(span) for span in canonical]
            if spans:
                db.add_all(spans)
                await db.flush()

        for span in spans:
            self._reanchor_span(
                span,
                content=content,
                source_draft_id=draft_id,
                source_content_hash=source_content_hash,
            )
        await db.flush()
        return [_span_contract(span) for span in spans]

    async def get_checkpoint(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        content_mode: str,
        through_chapter: int,
        through_offset: int | None = None,
    ) -> SceneSummaryCheckpointContract | None:
        conditions = [
            SceneSummaryCheckpoint.novel_id == uuid.UUID(str(novel_id)),
            SceneSummaryCheckpoint.scene_id == uuid.UUID(str(scene_id)),
            SceneSummaryCheckpoint.content_mode == content_mode,
            SceneSummaryCheckpoint.status == "ready",
            SceneSummaryCheckpoint.through_chapter <= through_chapter,
        ]
        if through_offset is not None:
            conditions.append(
                or_(
                    SceneSummaryCheckpoint.through_chapter < through_chapter,
                    and_(
                        SceneSummaryCheckpoint.through_chapter == through_chapter,
                        SceneSummaryCheckpoint.through_offset >= 0,
                        SceneSummaryCheckpoint.through_offset <= through_offset,
                    ),
                )
            )
        else:
            conditions.append(
                or_(
                    SceneSummaryCheckpoint.through_chapter < through_chapter,
                    and_(
                        SceneSummaryCheckpoint.through_chapter == through_chapter,
                        SceneSummaryCheckpoint.through_offset == -1,
                    ),
                )
            )
        stmt = (
            select(SceneSummaryCheckpoint)
            .where(*conditions)
            .order_by(
                SceneSummaryCheckpoint.through_chapter.desc(),
                SceneSummaryCheckpoint.through_offset.desc(),
                SceneSummaryCheckpoint.updated_at.desc(),
            )
            .limit(1)
        )
        item = (await db.execute(stmt)).scalar_one_or_none()
        if item is None:
            return None
        if not await self._checkpoint_is_current(db, novel_id, item):
            item.status = "stale"
            await db.flush()
            return None
        return _checkpoint_contract(item)

    async def rebuild_checkpoint(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        scene_id: str,
        content_mode: str,
        through_chapter: int,
        through_offset: int | None = None,
    ) -> SceneSummaryCheckpointContract | None:
        from modules.writing.facade import (
            build_manuscript_range_ref,
            read_manuscript_range,
        )

        spans = await SceneRepository().get_scene_spans_for_scene(
            db,
            uuid.UUID(str(novel_id)),
            uuid.UUID(str(scene_id)),
            statuses=("draft", "canonical"),
            content_mode=content_mode,
        )
        visible = [
            span
            for span in spans
            if span.chapter_index < through_chapter
            or (
                span.chapter_index == through_chapter
                and (
                    through_offset is None
                    or span.start_offset is None
                    or span.start_offset < through_offset
                )
            )
        ]
        source_refs: list[dict] = []
        excerpts: list[str] = []
        for span in visible:
            if (
                span.mapping_status not in {"exact", "reanchored"}
                or span.source_draft_id is None
                or not span.source_content_hash
                or span.start_offset is None
                or span.end_offset is None
            ):
                continue
            end_offset = span.end_offset
            if span.chapter_index == through_chapter and through_offset is not None:
                end_offset = min(end_offset, through_offset)
            if end_offset <= span.start_offset:
                continue
            try:
                ref = await build_manuscript_range_ref(
                    db,
                    novel_id,
                    draft_id=str(span.source_draft_id),
                    start_offset=span.start_offset,
                    end_offset=end_offset,
                    content_mode=content_mode,
                )
                if ref.source_hash != span.source_content_hash:
                    continue
                read = await read_manuscript_range(
                    db,
                    novel_id,
                    ref,
                    before=0,
                    after=0,
                )
            except Exception:
                continue
            source_refs.append(asdict(read.source_ref))
            excerpts.append(read.text)
        if not excerpts:
            return None
        combined = "\n".join(excerpts)
        summary = combined[:CHECKPOINT_SUMMARY_LIMIT]
        based_on_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        stored_offset = through_offset if through_offset is not None else -1
        lookup = await db.execute(
            select(SceneSummaryCheckpoint).where(
                SceneSummaryCheckpoint.novel_id == uuid.UUID(str(novel_id)),
                SceneSummaryCheckpoint.scene_id == uuid.UUID(str(scene_id)),
                SceneSummaryCheckpoint.content_mode == content_mode,
                SceneSummaryCheckpoint.through_chapter == through_chapter,
                SceneSummaryCheckpoint.through_offset == stored_offset,
            )
        )
        item = lookup.scalar_one_or_none()
        if item is None:
            item = SceneSummaryCheckpoint(
                novel_id=uuid.UUID(str(novel_id)),
                scene_id=uuid.UUID(str(scene_id)),
                content_mode=content_mode,
                through_chapter=through_chapter,
                through_offset=stored_offset,
                summary=summary,
                source_refs=source_refs,
                based_on_hash=based_on_hash,
                source="extractive",
                status="ready",
            )
            db.add(item)
        else:
            item.summary = summary
            item.source_refs = source_refs
            item.based_on_hash = based_on_hash
            item.source = "extractive"
            item.status = "ready"
        await db.flush()
        return _checkpoint_contract(item)

    @staticmethod
    async def _checkpoint_is_current(
        db: AsyncSession,
        novel_id: str,
        item: SceneSummaryCheckpoint,
    ) -> bool:
        from modules.writing.contracts import SourceRangeRefContract
        from modules.writing.facade import (
            list_manuscript_sources,
            read_manuscript_range,
        )

        refs: list[SourceRangeRefContract] = []
        try:
            refs = [SourceRangeRefContract(**raw) for raw in item.source_refs or []]
        except (TypeError, ValueError):
            return False
        if not refs:
            return False
        chapters = sorted({ref.chapter_index for ref in refs})
        current_sources = await list_manuscript_sources(
            db,
            novel_id,
            chapters,
            content_mode=item.content_mode,
        )
        current_by_chapter = {source.chapter_index: source for source in current_sources}
        excerpts: list[str] = []
        for ref in refs:
            current = current_by_chapter.get(ref.chapter_index)
            if (
                current is None
                or current.id != ref.draft_id
                or current.version_number != ref.version_number
                or current.content_hash != ref.source_hash
            ):
                return False
            try:
                read = await read_manuscript_range(
                    db,
                    novel_id,
                    ref,
                    before=0,
                    after=0,
                )
            except Exception:
                return False
            excerpts.append(read.text)
        combined = "\n".join(excerpts)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest() == item.based_on_hash

    @staticmethod
    def _clone_for_working(span: SceneSpan) -> SceneSpan:
        return SceneSpan(
            novel_id=span.novel_id,
            scene_id=span.scene_id,
            chapter_index=span.chapter_index,
            content_mode="working",
            source_draft_id=span.source_draft_id,
            source_content_hash=span.source_content_hash,
            start_offset=span.start_offset,
            end_offset=span.end_offset,
            start_paragraph=span.start_paragraph,
            end_paragraph=span.end_paragraph,
            part_no=span.part_no,
            mapping_status=span.mapping_status,
            anchor_hash=span.anchor_hash,
            anchor_excerpt=span.anchor_excerpt,
            source=span.source,
            status=span.status,
        )

    @staticmethod
    def _reanchor_span(
        span: SceneSpan,
        *,
        content: str,
        source_draft_id: uuid.UUID,
        source_content_hash: str,
    ) -> None:
        span.source_draft_id = source_draft_id
        span.source_content_hash = source_content_hash
        if (
            span.mapping_status == "chapter_only"
            and not span.anchor_hash
            and not span.anchor_excerpt
        ):
            # Migration-era spans intentionally have only chapter precision.
            # Valid-looking legacy offsets are not enough to manufacture exact
            # provenance; a user or a newly generated exact span must establish
            # the first anchor.
            return
        if span.start_offset is None or span.end_offset is None:
            span.mapping_status = "chapter_only"
            return
        if 0 <= span.start_offset < span.end_offset <= len(content):
            current = content[span.start_offset : span.end_offset]
            current_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if span.anchor_hash is None or current_hash == span.anchor_hash:
                span.anchor_hash = current_hash
                span.anchor_excerpt = current[:ANCHOR_EXCERPT_LIMIT]
                span.mapping_status = "exact"
                return
        anchor = (span.anchor_excerpt or "").strip()
        if anchor and content.count(anchor) == 1:
            start = content.index(anchor)
            length = max(
                1,
                (span.end_offset or start + len(anchor)) - (span.start_offset or start),
            )
            span.start_offset = start
            span.end_offset = min(len(content), start + length)
            current = content[span.start_offset : span.end_offset]
            span.anchor_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
            span.anchor_excerpt = current[:ANCHOR_EXCERPT_LIMIT]
            span.mapping_status = "reanchored"
            return
        span.mapping_status = "unresolved"


def _span_contract(span: SceneSpan) -> SceneSpanContract:
    return SceneSpanContract(
        id=str(span.id),
        novel_id=str(span.novel_id),
        scene_id=str(span.scene_id),
        chapter_index=span.chapter_index,
        content_mode=span.content_mode,
        source_draft_id=(str(span.source_draft_id) if span.source_draft_id else None),
        source_content_hash=span.source_content_hash,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        start_paragraph=span.start_paragraph,
        end_paragraph=span.end_paragraph,
        part_no=span.part_no,
        mapping_status=span.mapping_status,
        anchor_hash=span.anchor_hash,
        source=span.source,
        status=span.status,
    )


def _checkpoint_contract(item: SceneSummaryCheckpoint) -> SceneSummaryCheckpointContract:
    return SceneSummaryCheckpointContract(
        id=str(item.id),
        novel_id=str(item.novel_id),
        scene_id=str(item.scene_id),
        content_mode=item.content_mode,
        through_chapter=item.through_chapter,
        through_offset=(item.through_offset if item.through_offset >= 0 else None),
        summary=item.summary,
        source_refs=list(item.source_refs or []),
        based_on_hash=item.based_on_hash,
        source=item.source,
        status=item.status,
    )
