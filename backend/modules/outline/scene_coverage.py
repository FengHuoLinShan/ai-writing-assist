"""SceneSpan coverage queries owned by the outline module."""

from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.contracts import SceneSpanContract, SceneSpanCoverageContract
from modules.outline.repositories import SceneRepository

_ACTIVE_STATUSES = ("draft", "canonical")
_PRECISE_MAPPING_STATUSES = frozenset({"exact", "reanchored"})


class SceneSpanCoverageService:
    """Build a deterministic coverage summary without judging semantic quality."""

    def __init__(self, repository: SceneRepository | None = None) -> None:
        self._repo = repository or SceneRepository()

    async def get_coverage(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        content_mode: str,
    ) -> SceneSpanCoverageContract:
        nid = uuid.UUID(str(novel_id))
        scene_ids = await self._repo.get_active_scene_ids_for_coverage(
            db,
            nid,
            statuses=_ACTIVE_STATUSES,
        )
        spans = await self._repo.get_scene_spans_for_coverage(
            db,
            nid,
            content_mode=content_mode,
            statuses=_ACTIVE_STATUSES,
        )
        counts = Counter(str(span.mapping_status or "unresolved") for span in spans)
        spanned_scene_ids = {span.scene_id for span in spans}
        precise_spans = [
            _span_to_contract(span)
            for span in spans
            if span.mapping_status in _PRECISE_MAPPING_STATUSES
        ]
        total = len(spans)
        precise = len(precise_spans)
        return SceneSpanCoverageContract(
            novel_id=str(nid),
            content_mode=content_mode,
            scene_count=len(scene_ids),
            scene_with_span_count=len(scene_ids & spanned_scene_ids),
            scene_without_span_count=len(scene_ids - spanned_scene_ids),
            total_span_count=total,
            exact_count=counts["exact"],
            reanchored_count=counts["reanchored"],
            chapter_only_count=counts["chapter_only"],
            unresolved_count=counts["unresolved"],
            precise_span_count=precise,
            imprecise_span_count=total - precise,
            precise_span_rate=round(precise / total, 4) if total else None,
            precise_spans=precise_spans,
        )


def _span_to_contract(span) -> SceneSpanContract:
    return SceneSpanContract(
        id=str(span.id),
        novel_id=str(span.novel_id),
        scene_id=str(span.scene_id),
        chapter_index=int(span.chapter_index),
        content_mode=str(span.content_mode),
        source_draft_id=str(span.source_draft_id) if span.source_draft_id else None,
        source_content_hash=span.source_content_hash,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        start_paragraph=span.start_paragraph,
        end_paragraph=span.end_paragraph,
        part_no=int(span.part_no),
        mapping_status=str(span.mapping_status),
        anchor_hash=span.anchor_hash,
        source=str(span.source),
        status=str(span.status),
    )
