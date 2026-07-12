from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, ClassVar

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import (
    OutlineArc,
    PlotThread,
    Scene,
    SceneChapterLink,
    SceneCrossChapterSuggestion,
    SceneSpan,
)
from modules.outline.schemas import (
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
    SceneCreate,
    SceneUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE


def apply_structure_asset_filters(
    conditions: list[Any],
    model: Any,
    *,
    status: str | None = None,
    source: str | None = None,
    workflow_id: str | None = None,
    needs_review: bool | None = None,
) -> None:
    if status is not None:
        conditions.append(model.status == status)
    if source is not None:
        conditions.append(model.provenance_meta["source"].as_string() == source)
    if workflow_id is not None:
        conditions.append(model.provenance_meta["workflow_id"].as_string() == workflow_id)
    if needs_review is not None:
        conditions.append(
            model.provenance_meta["needs_review"].as_boolean() == needs_review
        )


class StructurePlanRepository[ModelT]:
    model_class: ClassVar[type[ModelT]]
    order_by: ClassVar[tuple[Any, ...]] = ()

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: dict,
    ) -> ModelT:
        plan = self.model_class(novel_id=novel_id, **data)
        db.add(plan)
        await db.flush()
        return plan

    async def create_batch(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[dict],
    ) -> list[ModelT]:
        plans = [self.model_class(novel_id=novel_id, **data) for data in items]
        db.add_all(plans)
        await db.flush()
        return plans

    async def get(self, db: AsyncSession, plan_id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model_class).where(self.model_class.id == plan_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
    ) -> tuple[list[ModelT], int]:
        conditions = [self.model_class.novel_id == novel_id]
        apply_structure_asset_filters(
            conditions,
            self.model_class,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        total = (
            await db.execute(select(func.count(self.model_class.id)).where(*conditions))
        ).scalar() or 0
        stmt = select(self.model_class).where(*conditions).offset(skip).limit(limit)
        if self.order_by:
            stmt = stmt.order_by(*self.order_by)
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

    async def update(
        self,
        db: AsyncSession,
        plan_id: uuid.UUID,
        data: dict,
    ) -> ModelT | None:
        plan = await self.get(db, plan_id)
        if plan is None:
            return None
        for field, value in data.items():
            setattr(plan, field, value)
        db.add(plan)
        await db.flush()
        return plan

    async def delete(self, db: AsyncSession, plan_id: uuid.UUID) -> bool:
        result = await db.execute(
            delete(self.model_class).where(self.model_class.id == plan_id)
        )
        await db.flush()
        return result.rowcount > 0


class PlotThreadRepository:
    @staticmethod
    def _build(novel_id: uuid.UUID, data: PlotThreadCreate) -> PlotThread:
        return PlotThread(
            novel_id=novel_id,
            name=data.name,
            thread_type=data.thread_type,
            summary=data.summary,
            visible_goal=data.visible_goal,
            hidden_truth=data.hidden_truth,
            start_chapter=data.start_chapter,
            planned_payoff_chapter=data.planned_payoff_chapter,
            current_stage=data.current_stage,
            related_character_ids=data.related_character_ids or [],
            related_entity_ids=data.related_entity_ids or [],
            related_memory_ids=data.related_memory_ids or [],
            reader_known_state=data.reader_known_state,
            author_known_state=data.author_known_state,
            provenance_meta=data.provenance_meta or {},
            status=data.status or "draft",
        )

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: PlotThreadCreate,
    ) -> PlotThread:
        thread = self._build(novel_id, data)
        db.add(thread)
        await db.flush()
        return thread

    async def create_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[PlotThreadCreate],
    ) -> list[PlotThread]:
        threads = [self._build(novel_id, data) for data in items]
        if threads:
            db.add_all(threads)
            await db.flush()
        return threads

    async def get(self, db: AsyncSession, thread_id: uuid.UUID) -> PlotThread | None:
        stmt = select(PlotThread).where(PlotThread.id == thread_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
    ) -> tuple[list[PlotThread], int]:
        conditions = [PlotThread.novel_id == novel_id]
        apply_structure_asset_filters(
            conditions,
            PlotThread,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        count_stmt = select(func.count(PlotThread.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(PlotThread)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(PlotThread.start_chapter, PlotThread.name, PlotThread.id)
        )
        result = await db.execute(stmt)
        items: Sequence[PlotThread] = result.scalars().all()
        return list(items), total

    async def get_active(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[PlotThread]:
        """获取某个章节时活跃的剧情线。

        start_chapter <= chapter_index，且未完结或 planned_payoff >= chapter。
        """
        conditions = [
            PlotThread.novel_id == novel_id,
            PlotThread.status.in_(["draft", "canonical"]),
            PlotThread.start_chapter <= chapter_index,
            or_(
                PlotThread.planned_payoff_chapter.is_(None),
                PlotThread.planned_payoff_chapter >= chapter_index,
            ),
        ]
        stmt = (
            select(PlotThread)
            .where(*conditions)
            .order_by(PlotThread.start_chapter, PlotThread.id)
        )
        result = await db.execute(stmt)
        items: Sequence[PlotThread] = result.scalars().all()
        return list(items)

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        """统计与 [start_chapter, end_chapter] 范围重叠的剧情线数量。

        使用范围重叠检测（与 OutlineArc 版本一致），
        而非仅检查 start_chapter 是否在区间内。
        """
        conditions = [
            PlotThread.novel_id == novel_id,
            PlotThread.start_chapter <= end_chapter,
            # 线程没有 end_chapter 字段，用 planned_payoff_chapter 估算范围上限
            or_(
                PlotThread.planned_payoff_chapter.is_(None),
                PlotThread.planned_payoff_chapter >= start_chapter,
            ),
        ]
        stmt = select(func.count(PlotThread.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def update(
        self,
        db: AsyncSession,
        thread_id: uuid.UUID,
        data: PlotThreadUpdate,
    ) -> PlotThread | None:
        thread = await self.get(db, thread_id)
        if thread is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
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
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for json_field in (
            "related_character_ids",
            "related_entity_ids",
            "related_memory_ids",
            "provenance_meta",
        ):
            value = getattr(data, json_field, None)
            if value is not None:
                update_values[json_field] = value

        if update_values:
            for field, value in update_values.items():
                setattr(thread, field, value)
            db.add(thread)
            await db.flush()

        return thread

    async def delete(self, db: AsyncSession, thread_id: uuid.UUID) -> bool:
        stmt = delete(PlotThread).where(PlotThread.id == thread_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


class OutlineArcRepository:
    @staticmethod
    def _build(novel_id: uuid.UUID, data: OutlineArcCreate) -> OutlineArc:
        return OutlineArc(
            novel_id=novel_id,
            title=data.title,
            arc_index=data.arc_index,
            start_chapter=data.start_chapter,
            end_chapter=data.end_chapter,
            arc_goal=data.arc_goal,
            core_conflict=data.core_conflict,
            main_opposition=data.main_opposition,
            entry_hook=data.entry_hook,
            midpoint_turn=data.midpoint_turn,
            climax=data.climax,
            result=data.result,
            next_hook=data.next_hook,
            related_thread_ids=data.related_thread_ids or [],
            related_character_ids=data.related_character_ids or [],
            related_entity_ids=data.related_entity_ids or [],
            provenance_meta=data.provenance_meta or {},
            status=data.status or "draft",
        )

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: OutlineArcCreate,
    ) -> OutlineArc:
        arc = self._build(novel_id, data)
        db.add(arc)
        await db.flush()
        return arc

    async def create_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[OutlineArcCreate],
    ) -> list[OutlineArc]:
        arcs = [self._build(novel_id, data) for data in items]
        if arcs:
            db.add_all(arcs)
            await db.flush()
        return arcs

    async def get(self, db: AsyncSession, arc_id: uuid.UUID) -> OutlineArc | None:
        stmt = select(OutlineArc).where(OutlineArc.id == arc_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
    ) -> tuple[list[OutlineArc], int]:
        conditions = [OutlineArc.novel_id == novel_id]
        apply_structure_asset_filters(
            conditions,
            OutlineArc,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
        )
        count_stmt = select(func.count(OutlineArc.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(OutlineArc)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(OutlineArc.arc_index, OutlineArc.id)
        )
        result = await db.execute(stmt)
        items: Sequence[OutlineArc] = result.scalars().all()
        return list(items), total

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> OutlineArc | None:
        """获取指定章节所属的篇章"""
        stmt = (
            select(OutlineArc)
            .where(
                OutlineArc.novel_id == novel_id,
                OutlineArc.start_chapter <= chapter_index,
                OutlineArc.end_chapter >= chapter_index,
                OutlineArc.status.in_(["draft", "canonical"]),
            )
            .order_by(OutlineArc.arc_index, OutlineArc.id)
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_by_novel_and_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
    ) -> int:
        """统计章节范围 [start, end] 内重叠的篇章数。"""
        conditions = [
            OutlineArc.novel_id == novel_id,
            OutlineArc.start_chapter <= end_chapter,
            or_(
                OutlineArc.end_chapter.is_(None),
                OutlineArc.end_chapter >= start_chapter,
            ),
        ]
        stmt = select(func.count(OutlineArc.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def update(
        self,
        db: AsyncSession,
        arc_id: uuid.UUID,
        data: OutlineArcUpdate,
    ) -> OutlineArc | None:
        arc = await self.get(db, arc_id)
        if arc is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
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
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        for json_field in (
            "related_thread_ids",
            "related_character_ids",
            "related_entity_ids",
            "provenance_meta",
        ):
            value = getattr(data, json_field, None)
            if value is not None:
                update_values[json_field] = value

        if update_values:
            for field, value in update_values.items():
                setattr(arc, field, value)
            db.add(arc)
            await db.flush()

        return arc

    async def delete(self, db: AsyncSession, arc_id: uuid.UUID) -> bool:
        stmt = delete(OutlineArc).where(OutlineArc.id == arc_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


class SceneRepository:
    def _build_scene(self, novel_id: uuid.UUID, data: SceneCreate) -> Scene:
        return Scene(
            novel_id=novel_id,
            scene_index=data.scene_index,
            title=data.title,
            goal=data.goal,
            core_conflict=data.core_conflict,
            emotional_beat=data.emotional_beat,
            must_happen=data.must_happen,
            must_not_happen=data.must_not_happen,
            narrative_tag=data.narrative_tag or "draft",
            source=data.source or "manual",
            scene_chunks=data.scene_chunks or [],
            chapter_ids=data.chapter_ids or [],
            pov_character_id=data.pov_character_id,
            structure_meta=data.structure_meta or {},
            status=data.status or "draft",
        )

    def chapter_indices_for_scene(self, scene: Scene) -> list[int]:
        indices: set[int] = set()
        for chapter_id in scene.chapter_ids or []:
            try:
                indices.add(int(chapter_id))
            except (TypeError, ValueError):
                continue
        for chunk in scene.scene_chunks or []:
            if not isinstance(chunk, dict):
                continue
            raw_index = chunk.get("chapter_index") or chunk.get("chapter_id")
            try:
                indices.add(int(raw_index))
            except (TypeError, ValueError):
                continue
        return sorted(indices)

    def scene_spans_for_scene(self, scene: Scene) -> list[SceneSpan]:
        parts: list[dict[str, Any]] = []
        for raw_order, chunk in enumerate(scene.scene_chunks or []):
            if not isinstance(chunk, dict):
                continue
            chapter_index = self._first_int(chunk, ("chapter_index", "chapter_id"))
            if chapter_index is None:
                continue
            start_offset = self._first_int(chunk, ("start_offset", "start_pos"))
            end_offset = self._first_int(chunk, ("end_offset", "end_pos"))
            start_paragraph = self._first_int(chunk, ("start_paragraph",))
            end_paragraph = self._first_int(chunk, ("end_paragraph",))
            parts.append(
                {
                    "chapter_index": chapter_index,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "start_paragraph": start_paragraph,
                    "end_paragraph": end_paragraph,
                    "source_draft_id": chunk.get("source_draft_id"),
                    "source_content_hash": chunk.get("source_content_hash"),
                    "mapping_status": (
                        "exact"
                        if start_offset is not None and end_offset is not None
                        else "chapter_only"
                    ),
                    "anchor_hash": chunk.get("anchor_hash"),
                    "anchor_excerpt": chunk.get("anchor_excerpt"),
                    "raw_order": raw_order,
                }
            )

        parts.sort(
            key=lambda part: (
                part["chapter_index"],
                part["start_offset"] if part["start_offset"] is not None else 10**12,
                (
                    part["start_paragraph"]
                    if part["start_paragraph"] is not None
                    else 10**12
                ),
                part["raw_order"],
            )
        )
        return [
            SceneSpan(
                novel_id=scene.novel_id,
                scene_id=scene.id,
                chapter_index=part["chapter_index"],
                content_mode="canonical",
                source_draft_id=(
                    uuid.UUID(str(part["source_draft_id"]))
                    if part["source_draft_id"]
                    else None
                ),
                source_content_hash=part["source_content_hash"],
                start_offset=part["start_offset"],
                end_offset=part["end_offset"],
                start_paragraph=part["start_paragraph"],
                end_paragraph=part["end_paragraph"],
                part_no=part_no,
                mapping_status=part["mapping_status"],
                anchor_hash=part["anchor_hash"],
                anchor_excerpt=part["anchor_excerpt"],
                source=scene.source or "manual",
                status=scene.status or "draft",
            )
            for part_no, part in enumerate(parts)
        ]

    @staticmethod
    def _first_int(chunk: dict[str, Any], keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = chunk.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return None

    async def sync_scene_indexes(
        self,
        db: AsyncSession,
        scene: Scene,
    ) -> None:
        await self.sync_chapter_links(db, scene)
        await self.sync_scene_spans(db, scene)

    async def sync_chapter_links(
        self,
        db: AsyncSession,
        scene: Scene,
    ) -> None:
        await db.execute(
            delete(SceneChapterLink).where(
                SceneChapterLink.novel_id == scene.novel_id,
                SceneChapterLink.scene_id == scene.id,
            )
        )
        links = [
            SceneChapterLink(
                novel_id=scene.novel_id,
                scene_id=scene.id,
                chapter_index=chapter_index,
            )
            for chapter_index in self.chapter_indices_for_scene(scene)
        ]
        if links:
            db.add_all(links)
        await db.flush()

    async def sync_scene_spans(
        self,
        db: AsyncSession,
        scene: Scene,
    ) -> None:
        """Rebuild physical span rows after ``scene_chunks`` changes."""
        await db.execute(
            delete(SceneSpan).where(
                SceneSpan.novel_id == scene.novel_id,
                SceneSpan.scene_id == scene.id,
            )
        )
        spans = self.scene_spans_for_scene(scene)
        if spans:
            db.add_all(spans)
        await db.flush()

    async def mirror_scene_span_lifecycle(
        self,
        db: AsyncSession,
        scene: Scene,
    ) -> None:
        """Mirror Scene lifecycle fields without destroying version-bound spans."""
        await db.execute(
            update(SceneSpan)
            .where(
                SceneSpan.novel_id == scene.novel_id,
                SceneSpan.scene_id == scene.id,
            )
            .values(
                source=scene.source or "manual",
                status=scene.status or "draft",
            )
        )
        await db.flush()

    async def delete_scene_spans(
        self,
        db: AsyncSession,
        scene: Scene,
    ) -> None:
        await db.execute(
            delete(SceneSpan).where(
                SceneSpan.novel_id == scene.novel_id,
                SceneSpan.scene_id == scene.id,
            )
        )
        await db.flush()

    async def stale_cross_chapter_suggestions_for_scene(
        self,
        db: AsyncSession,
        scene: Scene,
    ) -> int:
        result = await db.execute(
            select(SceneCrossChapterSuggestion).where(
                SceneCrossChapterSuggestion.novel_id == scene.novel_id,
                SceneCrossChapterSuggestion.status == "pending",
            )
        )
        matched = [
            item
            for item in result.scalars().all()
            if str(scene.id) in {str(value) for value in item.source_scene_ids or []}
        ]
        for item in matched:
            item.status = "stale"
            db.add(item)
        if matched:
            await db.flush()
        return len(matched)

    async def backfill_chapter_links(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID | None = None,
    ) -> int:
        conditions = []
        if novel_id is not None:
            conditions.append(Scene.novel_id == novel_id)
        stmt = select(Scene)
        if conditions:
            stmt = stmt.where(*conditions)
        result = await db.execute(stmt)
        scenes: Sequence[Scene] = result.scalars().all()
        delete_stmt = delete(SceneChapterLink)
        if novel_id is not None:
            delete_stmt = delete_stmt.where(SceneChapterLink.novel_id == novel_id)
        await db.execute(delete_stmt)
        link_count = 0
        links: list[SceneChapterLink] = []
        for scene in scenes:
            for chapter_index in self.chapter_indices_for_scene(scene):
                links.append(
                    SceneChapterLink(
                        novel_id=scene.novel_id,
                        scene_id=scene.id,
                        chapter_index=chapter_index,
                    )
                )
        if links:
            db.add_all(links)
            link_count = len(links)
        await db.flush()
        return link_count

    async def backfill_scene_spans(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID | None = None,
    ) -> int:
        conditions = []
        if novel_id is not None:
            conditions.append(Scene.novel_id == novel_id)
        stmt = select(Scene)
        if conditions:
            stmt = stmt.where(*conditions)
        result = await db.execute(stmt)
        scenes: Sequence[Scene] = result.scalars().all()
        delete_stmt = delete(SceneSpan)
        if novel_id is not None:
            delete_stmt = delete_stmt.where(SceneSpan.novel_id == novel_id)
        await db.execute(delete_stmt)
        spans: list[SceneSpan] = []
        for scene in scenes:
            spans.extend(self.scene_spans_for_scene(scene))
        if spans:
            db.add_all(spans)
        await db.flush()
        return len(spans)

    async def get_scene_spans_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        *,
        statuses: tuple[str, ...] = ("draft", "canonical"),
        content_mode: str = "canonical",
    ) -> list[SceneSpan]:
        conditions = [
            SceneSpan.novel_id == novel_id,
            SceneSpan.chapter_index == chapter_index,
            SceneSpan.content_mode == content_mode,
        ]
        if statuses:
            conditions.append(SceneSpan.status.in_(statuses))
        stmt = (
            select(SceneSpan).where(*conditions).order_by(SceneSpan.part_no, SceneSpan.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_active_scene_ids_for_coverage(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
    ) -> set[uuid.UUID]:
        stmt = select(Scene.id).where(
            Scene.novel_id == novel_id,
            Scene.status.in_(statuses),
        )
        result = await db.execute(stmt)
        return set(result.scalars().all())

    async def get_scene_spans_for_coverage(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        content_mode: str,
        statuses: tuple[str, ...],
    ) -> list[SceneSpan]:
        stmt = (
            select(SceneSpan)
            .where(
                SceneSpan.novel_id == novel_id,
                SceneSpan.content_mode == content_mode,
                SceneSpan.status.in_(statuses),
            )
            .order_by(SceneSpan.chapter_index, SceneSpan.part_no, SceneSpan.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_scene_spans_for_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        *,
        statuses: tuple[str, ...] | None = None,
        content_mode: str = "canonical",
    ) -> list[SceneSpan]:
        conditions = [
            SceneSpan.novel_id == novel_id,
            SceneSpan.scene_id == scene_id,
            SceneSpan.content_mode == content_mode,
        ]
        if statuses:
            conditions.append(SceneSpan.status.in_(statuses))
        stmt = (
            select(SceneSpan).where(*conditions).order_by(SceneSpan.part_no, SceneSpan.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_scene_ids_needing_span_review(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """Return active Scenes with source mappings needing manual review."""
        stmt = select(SceneSpan.scene_id).where(
            SceneSpan.novel_id == novel_id,
            SceneSpan.status.in_(("draft", "canonical")),
            SceneSpan.mapping_status.in_(("chapter_only", "unresolved")),
        )
        result = await db.execute(stmt)
        return set(result.scalars().all())

    async def get_scene_spans_needing_review(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[SceneSpan]:
        stmt = (
            select(SceneSpan)
            .where(
                SceneSpan.novel_id == novel_id,
                SceneSpan.status.in_(("draft", "canonical")),
                SceneSpan.mapping_status.in_(("chapter_only", "unresolved")),
            )
            .order_by(SceneSpan.scene_id, SceneSpan.content_mode, SceneSpan.part_no)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def _get_by_chapter_json_fallback(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[Scene]:
        conditions = [
            Scene.novel_id == novel_id,
            Scene.status.in_(["draft", "canonical"]),
        ]
        stmt = select(Scene).where(*conditions).order_by(Scene.scene_index, Scene.id)
        result = await db.execute(stmt)
        all_scenes: Sequence[Scene] = result.scalars().all()
        matching = [
            scene
            for scene in all_scenes
            if chapter_index in self.chapter_indices_for_scene(scene)
        ]
        return matching

    async def _get_by_chapter_range_json_fallback(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
        *,
        statuses: tuple[str, ...],
    ) -> list[Scene]:
        conditions = [
            Scene.novel_id == novel_id,
            Scene.status.in_(statuses),
        ]
        stmt = select(Scene).where(*conditions).order_by(Scene.scene_index, Scene.id)
        result = await db.execute(stmt)
        all_scenes: Sequence[Scene] = result.scalars().all()
        matching = []
        for scene in all_scenes:
            chapters = self.chapter_indices_for_scene(scene)
            if any(start_chapter <= chapter <= end_chapter for chapter in chapters):
                matching.append(scene)
        return matching

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: SceneCreate,
    ) -> Scene:
        scene = self._build_scene(novel_id, data)
        db.add(scene)
        await db.flush()
        await self.sync_scene_indexes(db, scene)
        return scene

    async def create_many(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        items: list[SceneCreate],
    ) -> list[Scene]:
        scenes = [self._build_scene(novel_id, data) for data in items]
        if not scenes:
            return []
        db.add_all(scenes)
        await db.flush()
        for scene in scenes:
            await self.sync_scene_indexes(db, scene)
        return scenes

    async def get(self, db: AsyncSession, scene_id: uuid.UUID) -> Scene | None:
        stmt = select(Scene).where(Scene.id == scene_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_for_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_ids: list[uuid.UUID],
    ) -> list[Scene]:
        if not scene_ids:
            return []
        stmt = select(Scene).where(
            Scene.novel_id == novel_id,
            Scene.id.in_(scene_ids),
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Scene], int]:
        conditions = [Scene.novel_id == novel_id]
        count_stmt = select(func.count(Scene.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        stmt = (
            select(Scene)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Scene.scene_index, Scene.id)
        )
        result = await db.execute(stmt)
        items: Sequence[Scene] = result.scalars().all()
        return list(items), total

    async def get_by_novel_ordered(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        boundary_status: str | None = None,
        phase: str | None = None,
        phase1a_fallback: bool | None = None,
        q: str | None = None,
        chapter_from: int | None = None,
        chapter_to: int | None = None,
        confidence_band: str | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> list[Scene]:
        conditions = [Scene.novel_id == novel_id]
        if status:
            conditions.append(Scene.status == status)
        else:
            conditions.append(Scene.status.in_(["candidate", "draft", "canonical"]))
        if source:
            conditions.append(Scene.source == source)
        if workflow_id:
            conditions.append(
                Scene.structure_meta["workflow_id"].as_string() == workflow_id
            )
        if needs_review is not None:
            conditions.append(
                Scene.structure_meta["needs_review"].as_boolean() == needs_review
            )
        if boundary_status:
            conditions.append(
                Scene.structure_meta["boundary_status"].as_string() == boundary_status
            )
        if phase:
            conditions.append(Scene.structure_meta["phase"].as_string() == phase)
        if phase1a_fallback is not None:
            conditions.append(
                Scene.structure_meta["phase1a_fallback"].as_boolean() == phase1a_fallback
            )
        if q:
            pattern = f"%{q.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Scene.title).like(pattern),
                    func.lower(Scene.goal).like(pattern),
                    func.lower(Scene.core_conflict).like(pattern),
                    func.lower(Scene.emotional_beat).like(pattern),
                    func.lower(Scene.must_happen).like(pattern),
                    func.lower(Scene.must_not_happen).like(pattern),
                )
            )
        if confidence_band:
            confidence = Scene.structure_meta["confidence"].as_float()
            if confidence_band == "low":
                conditions.append(confidence < 0.5)
            elif confidence_band == "medium":
                conditions.append(and_(confidence >= 0.5, confidence < 0.8))
            elif confidence_band == "high":
                conditions.append(confidence >= 0.8)
        if chapter_from is not None or chapter_to is not None:
            chapter_conditions = [
                SceneChapterLink.novel_id == novel_id,
                SceneChapterLink.scene_id == Scene.id,
            ]
            if chapter_from is not None:
                chapter_conditions.append(SceneChapterLink.chapter_index >= chapter_from)
            if chapter_to is not None:
                chapter_conditions.append(SceneChapterLink.chapter_index <= chapter_to)
            conditions.append(
                select(SceneChapterLink.id).where(*chapter_conditions).exists()
            )
        stmt = (
            select(Scene)
            .where(*conditions)
            .order_by(Scene.scene_index, Scene.id)
            .offset(skip)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        items: Sequence[Scene] = result.scalars().all()
        return list(items)

    async def get_by_provenance_key(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        provenance_key: str,
    ) -> list[Scene]:
        stmt = (
            select(Scene)
            .where(Scene.novel_id == novel_id)
            .order_by(Scene.scene_index, Scene.id)
        )
        result = await db.execute(stmt)
        items: Sequence[Scene] = result.scalars().all()
        return [
            scene
            for scene in items
            if (scene.structure_meta or {}).get("provenance_key") == provenance_key
        ]

    async def get_by_provenance_keys(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        provenance_keys: list[str],
    ) -> list[Scene]:
        unique_keys = list(dict.fromkeys(key for key in provenance_keys if key))
        if not unique_keys:
            return []
        stmt = (
            select(Scene)
            .where(
                Scene.novel_id == novel_id,
                Scene.structure_meta["provenance_key"].as_string().in_(unique_keys),
            )
            .order_by(Scene.scene_index, Scene.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[Scene]:
        stmt = (
            select(Scene)
            .join(SceneChapterLink, SceneChapterLink.scene_id == Scene.id)
            .where(
                Scene.novel_id == novel_id,
                Scene.status.in_(["draft", "canonical"]),
                SceneChapterLink.novel_id == novel_id,
                SceneChapterLink.chapter_index == chapter_index,
            )
            .order_by(Scene.scene_index, Scene.id)
        )
        result = await db.execute(stmt)
        matching: Sequence[Scene] = result.scalars().all()
        if matching:
            return list(matching)
        return await self._get_by_chapter_json_fallback(db, novel_id, chapter_index)

    async def get_by_chapter_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        start_chapter: int,
        end_chapter: int,
        *,
        statuses: tuple[str, ...] = ("candidate", "draft", "canonical"),
    ) -> list[Scene]:
        linked_scene_ids = (
            select(SceneChapterLink.scene_id)
            .where(
                SceneChapterLink.novel_id == novel_id,
                SceneChapterLink.chapter_index >= start_chapter,
                SceneChapterLink.chapter_index <= end_chapter,
            )
            .distinct()
        )
        stmt = (
            select(Scene)
            .where(
                Scene.novel_id == novel_id,
                Scene.status.in_(statuses),
                Scene.id.in_(linked_scene_ids),
            )
            .order_by(Scene.scene_index, Scene.id)
        )
        result = await db.execute(stmt)
        matching: Sequence[Scene] = result.scalars().all()
        if matching:
            return list(matching)
        return await self._get_by_chapter_range_json_fallback(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            statuses=statuses,
        )

    async def get_by_chapter_index(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> Scene | None:
        """获取包含指定章节的 Scene（一个章节只属于一个 Scene）"""
        stmt = (
            select(Scene)
            .join(SceneChapterLink, SceneChapterLink.scene_id == Scene.id)
            .where(
                Scene.novel_id == novel_id,
                Scene.status.in_(["draft", "canonical"]),
                SceneChapterLink.novel_id == novel_id,
                SceneChapterLink.chapter_index == chapter_index,
            )
            .order_by(Scene.scene_index, Scene.id)
            .limit(1)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()
        if scene is not None:
            return scene
        fallback = await self._get_by_chapter_json_fallback(db, novel_id, chapter_index)
        return fallback[0] if fallback else None

    async def update(
        self,
        db: AsyncSession,
        scene_id: uuid.UUID,
        data: SceneUpdate,
    ) -> Scene | None:
        scene = await self.get(db, scene_id)
        if scene is None:
            return None

        update_values: dict[str, Any] = {}
        fields_set = data.model_fields_set
        for field in (
            "scene_index",
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "source",
            "pov_character_id",
            "status",
        ):
            if field in fields_set:
                value = getattr(data, field)
                if (
                    field in {"scene_index", "narrative_tag", "source", "status"}
                    and value is None
                ):
                    continue
                update_values[field] = value

        for json_field in ("scene_chunks", "chapter_ids", "structure_meta"):
            if json_field in fields_set:
                value = getattr(data, json_field)
                update_values[json_field] = value

        if update_values:
            for field, value in update_values.items():
                setattr(scene, field, value)
            db.add(scene)
            await db.flush()

        if "chapter_ids" in fields_set:
            await self.sync_chapter_links(db, scene)
        if "scene_chunks" in fields_set:
            await self.sync_scene_spans(db, scene)
        elif {"source", "status"} & fields_set:
            await self.mirror_scene_span_lifecycle(db, scene)
        if ("status" in fields_set and scene.status == "deprecated") or {
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "chapter_ids",
            "scene_chunks",
        } & fields_set:
            await self.stale_cross_chapter_suggestions_for_scene(db, scene)
        return scene

    async def deprecate_with_reference(
        self,
        db: AsyncSession,
        scenes: Sequence[Scene],
        *,
        reference_field: str,
        reference_scene_id: uuid.UUID,
        clear_mapping: bool = False,
    ) -> int:
        """Mark scenes deprecated while preserving per-source trace metadata."""
        scene_list = list(scenes)
        if not scene_list:
            return 0

        for scene in scene_list:
            source_meta = dict(scene.structure_meta or {})
            source_meta[reference_field] = str(reference_scene_id)
            scene.status = "deprecated"
            scene.structure_meta = source_meta
            if clear_mapping:
                scene.chapter_ids = []
                scene.scene_chunks = []

        db.add_all(scene_list)
        await db.flush()
        if clear_mapping:
            await db.execute(
                delete(SceneChapterLink).where(
                    SceneChapterLink.scene_id.in_([scene.id for scene in scene_list])
                )
            )
        for scene in scene_list:
            await self.stale_cross_chapter_suggestions_for_scene(db, scene)
            if clear_mapping:
                await self.delete_scene_spans(db, scene)
            else:
                await self.mirror_scene_span_lifecycle(db, scene)
        return len(scene_list)

    async def delete(self, db: AsyncSession, scene_id: uuid.UUID) -> bool:
        stmt = delete(Scene).where(Scene.id == scene_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def reorder(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_ids: list[uuid.UUID],
    ) -> int:
        """批量重排 scene_index，按 scene_ids 顺序从 0 开始重新编号"""
        if not scene_ids:
            return 0
        scene_order = {scene_id: index for index, scene_id in enumerate(scene_ids)}
        stmt = (
            update(Scene)
            .where(Scene.id.in_(scene_ids), Scene.novel_id == novel_id)
            .values(scene_index=case(scene_order, value=Scene.id))
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0

    async def shift_scene_indices_after(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_index: int,
        *,
        exclude_ids: set[uuid.UUID] | None = None,
    ) -> int:
        """将指定 novel 中 scene_index 更大的 Scene 整体后移一位。"""
        stmt = update(Scene).where(
            Scene.novel_id == novel_id,
            Scene.scene_index > scene_index,
        )
        if exclude_ids:
            stmt = stmt.where(Scene.id.not_in(exclude_ids))
        result = await db.execute(
            stmt.values(scene_index=Scene.scene_index + 1),
        )
        await db.flush()
        return result.rowcount or 0


class SceneCrossChapterSuggestionRepository:
    async def upsert_pending(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        source_task_id: uuid.UUID,
        suggestion_key: str,
        source_fingerprint: str,
        payload: dict[str, Any],
    ) -> SceneCrossChapterSuggestion:
        result = await db.execute(
            select(SceneCrossChapterSuggestion).where(
                SceneCrossChapterSuggestion.novel_id == novel_id,
                SceneCrossChapterSuggestion.suggestion_key == suggestion_key,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = SceneCrossChapterSuggestion(
                novel_id=novel_id,
                source_task_id=source_task_id,
                suggestion_key=suggestion_key,
                source_fingerprint=source_fingerprint,
                source_scene_ids=list(payload.get("source_scene_ids") or []),
                chapter_span=list(payload.get("chapter_span") or []),
                proposed_scene=dict(payload.get("proposed_scene") or {}),
                scan_trace=list(payload.get("scan_trace") or []),
                confidence=payload.get("confidence"),
                reason=payload.get("reason"),
                status="pending",
            )
            db.add(item)
        elif item.status == "pending":
            item.source_task_id = source_task_id
            item.source_scene_ids = list(payload.get("source_scene_ids") or [])
            item.chapter_span = list(payload.get("chapter_span") or [])
            item.proposed_scene = dict(payload.get("proposed_scene") or {})
            item.scan_trace = list(payload.get("scan_trace") or [])
            item.confidence = payload.get("confidence")
            item.reason = payload.get("reason")
            db.add(item)
        await db.flush()
        return item

    async def list_by_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str = "pending",
        skip: int = 0,
        limit: int | None = None,
    ) -> list[SceneCrossChapterSuggestion]:
        stmt = (
            select(SceneCrossChapterSuggestion)
            .where(
                SceneCrossChapterSuggestion.novel_id == novel_id,
                SceneCrossChapterSuggestion.status == status,
            )
            .order_by(
                SceneCrossChapterSuggestion.created_at.desc(),
                SceneCrossChapterSuggestion.id,
            )
            .offset(skip)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str = "pending",
    ) -> int:
        result = await db.execute(
            select(func.count(SceneCrossChapterSuggestion.id)).where(
                SceneCrossChapterSuggestion.novel_id == novel_id,
                SceneCrossChapterSuggestion.status == status,
            )
        )
        return int(result.scalar_one() or 0)

    async def get_for_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        suggestion_id: uuid.UUID,
    ) -> SceneCrossChapterSuggestion | None:
        result = await db.execute(
            select(SceneCrossChapterSuggestion).where(
                SceneCrossChapterSuggestion.novel_id == novel_id,
                SceneCrossChapterSuggestion.id == suggestion_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_status(
        self,
        db: AsyncSession,
        item: SceneCrossChapterSuggestion,
        *,
        status: str,
        result_scene_id: uuid.UUID | None = None,
    ) -> None:
        item.status = status
        item.result_scene_id = result_scene_id
        db.add(item)
        await db.flush()
