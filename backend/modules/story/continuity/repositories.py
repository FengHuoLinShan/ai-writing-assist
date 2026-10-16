"""
Memory 数据访问层

- EventRepository: memory_events 表操作
- SnapshotRepository: memory_snapshots 表操作
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from core.errors import ConflictError
from modules.story.continuity.chapter_order_projection import (
    MAX_CHAPTER_EVENT_CANDIDATES,
    ChapterOrderTransition,
    affected_chapter_indices,
    build_chapter_order_transitions,
    candidate_chapter_indices,
    project_current_chapter_index,
)
from modules.story.continuity.models import (
    DeltaLog,
    MemoryEvent,
    MemorySceneCheckpoint,
    MemorySceneSnapshot,
    MemorySnapshot,
    StoryChapterOrderReceipt,
)
from shared.constants import DEFAULT_PAGE_SIZE


class EventRepository:
    """记忆事件数据访问"""

    async def get_chapter_order_transitions(
        self, db: AsyncSession, novel_id: uuid.UUID
    ) -> tuple[ChapterOrderTransition, ...]:
        receipts = list(
            (
                await db.scalars(
                    select(StoryChapterOrderReceipt)
                    .where(StoryChapterOrderReceipt.novel_id == novel_id)
                    .order_by(
                        StoryChapterOrderReceipt.created_at,
                        StoryChapterOrderReceipt.id,
                    )
                )
            ).all()
        )
        return build_chapter_order_transitions(receipts)

    async def _affected_events(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        affected: set[int],
    ) -> list[MemoryEvent]:
        events = []
        chapter_ids = sorted(affected)
        for start in range(0, len(chapter_ids), 100):
            chunk = chapter_ids[start : start + 100]
            ranked = (
                select(
                    MemoryEvent.id.label("event_id"),
                    func.row_number()
                    .over(
                        partition_by=MemoryEvent.chapter_index,
                        order_by=(MemoryEvent.sequence, MemoryEvent.id),
                    )
                    .label("row_number"),
                )
                .where(
                    MemoryEvent.novel_id == novel_id,
                    MemoryEvent.chapter_index.in_(chunk),
                    MemoryEvent.source_stale.is_(False),
                )
                .subquery()
            )
            rows = (
                await db.execute(
                    select(MemoryEvent, ranked.c.row_number)
                    .join(ranked, ranked.c.event_id == MemoryEvent.id)
                    .where(ranked.c.row_number <= MAX_CHAPTER_EVENT_CANDIDATES + 1)
                    .order_by(
                        MemoryEvent.chapter_index,
                        MemoryEvent.sequence,
                        MemoryEvent.id,
                    )
                )
            ).all()
            if any(
                row_number > MAX_CHAPTER_EVENT_CANDIDATES for _event, row_number in rows
            ):
                raise ConflictError(
                    "章节重排候选事件超过每章 500 条读取边界，请先缩小重排范围"
                )
            events.extend(event for event, _row_number in rows)
        return events

    @staticmethod
    def _after_cursor(
        event: MemoryEvent,
        chapter_index: int,
        after: tuple[int, int, uuid.UUID] | None,
    ) -> bool:
        return (
            after is None
            or (
                chapter_index,
                event.sequence,
                event.id,
            )
            > after
        )

    @staticmethod
    def _projected_order(
        event: MemoryEvent,
        transitions: tuple[ChapterOrderTransition, ...],
    ) -> tuple[int, int, uuid.UUID]:
        chapter_index = project_current_chapter_index(
            event.chapter_index, event.created_at, transitions
        )
        return (
            chapter_index if chapter_index is not None else -1,
            event.sequence,
            event.id,
        )

    async def get_by_ids(
        self, db: AsyncSession, novel_id: uuid.UUID, event_ids: list[uuid.UUID]
    ) -> list[MemoryEvent]:
        result = await db.scalars(
            select(MemoryEvent)
            .where(MemoryEvent.novel_id == novel_id, MemoryEvent.id.in_(event_ids))
            .order_by(MemoryEvent.chapter_index, MemoryEvent.sequence)
        )
        return list(result.all())

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        sequence: int,
        event_type: str,
        snapshot_after: dict,
        entity_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        snapshot_before: dict | None = None,
        source: str = "ai_extraction",
        scene_id: uuid.UUID | None = None,
        scene_index: int | None = None,
        scene_sequence: int | None = None,
        dimension: str | None = None,
    ) -> MemoryEvent:
        event = MemoryEvent(
            novel_id=novel_id,
            chapter_index=chapter_index,
            sequence=sequence,
            event_type=event_type,
            entity_id=entity_id,
            entity_type=entity_type,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            source=source,
            scene_id=scene_id,
            scene_index=scene_index,
            scene_sequence=scene_sequence,
            dimension=dimension,
        )
        db.add(event)
        await db.flush()
        return event

    async def create_many(
        self,
        db: AsyncSession,
        rows: list[dict],
    ) -> list[MemoryEvent]:
        events = [MemoryEvent(**row) for row in rows]
        if not events:
            return []
        db.add_all(events)
        await db.flush()
        return events

    async def replace_chapter_events(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        rows: list[dict],
    ) -> list[MemoryEvent]:
        """Replace one chapter's current event stream with keyed upserts.

        The business key is (novel_id, chapter_index, sequence).  This keeps the
        old "chapter replacement" semantics without the delete-then-insert race.
        """
        await self._lock_chapter_events(db, novel_id, chapter_index)

        if rows:
            await self._upsert_chapter_event_rows(db, rows)

        max_sequence = len(rows)
        stale_stmt = delete(MemoryEvent).where(
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index == chapter_index,
            MemoryEvent.sequence > max_sequence,
        )
        await db.execute(stale_stmt)
        await db.flush()
        return await self.get_by_chapter(db, novel_id, chapter_index)

    async def _lock_chapter_events(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_events:{novel_id}:{chapter_index}"},
            )

    async def _upsert_chapter_event_rows(
        self,
        db: AsyncSession,
        rows: list[dict],
    ) -> None:
        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "postgresql":
            insert_stmt = pg_insert(MemoryEvent).values(rows)
        elif dialect_name == "sqlite":
            insert_stmt = sqlite_insert(MemoryEvent).values(rows)
        else:
            await self._manual_upsert_chapter_event_rows(db, rows)
            return

        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[
                MemoryEvent.novel_id,
                MemoryEvent.chapter_index,
                MemoryEvent.sequence,
            ],
            set_={
                "event_type": insert_stmt.excluded.event_type,
                "entity_id": insert_stmt.excluded.entity_id,
                "entity_type": insert_stmt.excluded.entity_type,
                "snapshot_before": insert_stmt.excluded.snapshot_before,
                "snapshot_after": insert_stmt.excluded.snapshot_after,
                "source": insert_stmt.excluded.source,
                "scene_id": insert_stmt.excluded.scene_id,
                "scene_index": insert_stmt.excluded.scene_index,
                "scene_sequence": insert_stmt.excluded.scene_sequence,
                "dimension": insert_stmt.excluded.dimension,
                # The upserted chapter_index is in the current order already.
                "created_at": func.now(),
            },
        )
        await db.execute(stmt)

    async def _manual_upsert_chapter_event_rows(
        self,
        db: AsyncSession,
        rows: list[dict],
    ) -> None:
        for row in rows:
            stmt = select(MemoryEvent).where(
                MemoryEvent.novel_id == row["novel_id"],
                MemoryEvent.chapter_index == row["chapter_index"],
                MemoryEvent.sequence == row["sequence"],
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if existing is None:
                db.add(MemoryEvent(**row))
                continue
            for field in (
                "event_type",
                "entity_id",
                "entity_type",
                "snapshot_before",
                "snapshot_after",
                "source",
                "scene_id",
                "scene_index",
                "scene_sequence",
                "dimension",
            ):
                setattr(existing, field, row.get(field))
            existing.created_at = datetime.now(UTC)

    async def get_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> list[MemoryEvent]:
        stmt = (
            select(MemoryEvent)
            .where(
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.chapter_index == chapter_index,
                MemoryEvent.source_stale.is_(False),
            )
            .order_by(MemoryEvent.sequence, MemoryEvent.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_chapter_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
        *,
        order_transitions: tuple[ChapterOrderTransition, ...] | None = None,
    ) -> list[MemoryEvent]:
        if order_transitions is None:
            order_transitions = await self.get_chapter_order_transitions(db, novel_id)
        touched = affected_chapter_indices(order_transitions)
        candidates = candidate_chapter_indices(
            from_chapter, to_chapter, order_transitions
        )
        if order_transitions and touched:
            conditions = [
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.chapter_index >= from_chapter,
                MemoryEvent.chapter_index <= to_chapter,
                MemoryEvent.source_stale.is_(False),
                MemoryEvent.chapter_index.not_in(touched),
            ]
            unaffected = list(
                (
                    await db.scalars(
                        select(MemoryEvent)
                        .where(*conditions)
                        .order_by(
                            MemoryEvent.chapter_index,
                            MemoryEvent.sequence,
                            MemoryEvent.id,
                        )
                    )
                ).all()
            )
            projected = [
                event
                for event in await self._affected_events(db, novel_id, candidates)
                if from_chapter
                <= project_current_chapter_index(
                    event.chapter_index, event.created_at, order_transitions
                )
                <= to_chapter
            ]
            return sorted(
                [*unaffected, *projected],
                key=lambda event: self._projected_order(event, order_transitions),
            )
        stmt = (
            select(MemoryEvent)
            .where(
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.chapter_index >= from_chapter,
                MemoryEvent.chapter_index <= to_chapter,
                MemoryEvent.source_stale.is_(False),
            )
            .order_by(MemoryEvent.chapter_index, MemoryEvent.sequence, MemoryEvent.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_by_chapter_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
        *,
        order_transitions: tuple[ChapterOrderTransition, ...] | None = None,
    ) -> int:
        if order_transitions is None:
            order_transitions = await self.get_chapter_order_transitions(db, novel_id)
        touched = affected_chapter_indices(order_transitions)
        candidates = candidate_chapter_indices(
            from_chapter, to_chapter, order_transitions
        )
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
            MemoryEvent.chapter_index <= to_chapter,
            MemoryEvent.source_stale.is_(False),
        ]
        if order_transitions and touched:
            conditions.append(MemoryEvent.chapter_index.not_in(touched))
        result = await db.execute(select(func.count(MemoryEvent.id)).where(*conditions))
        count = int(result.scalar_one())
        if order_transitions and candidates:
            count += sum(
                1
                for event in await self._affected_events(db, novel_id, candidates)
                if from_chapter
                <= project_current_chapter_index(
                    event.chapter_index, event.created_at, order_transitions
                )
                <= to_chapter
            )
        return count

    async def get_max_chapter_in_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
        *,
        order_transitions: tuple[ChapterOrderTransition, ...] | None = None,
    ) -> int | None:
        if order_transitions is None:
            order_transitions = await self.get_chapter_order_transitions(db, novel_id)
        touched = affected_chapter_indices(order_transitions)
        candidates = candidate_chapter_indices(
            from_chapter, to_chapter, order_transitions
        )
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
            MemoryEvent.chapter_index <= to_chapter,
            MemoryEvent.source_stale.is_(False),
        ]
        if order_transitions and touched:
            conditions.append(MemoryEvent.chapter_index.not_in(touched))
        result = await db.execute(
            select(func.max(MemoryEvent.chapter_index)).where(*conditions)
        )
        maximum = result.scalar_one()
        if order_transitions and candidates:
            projected = [
                project_current_chapter_index(
                    event.chapter_index, event.created_at, order_transitions
                )
                for event in await self._affected_events(db, novel_id, candidates)
            ]
            changed_max = max(
                (
                    index
                    for index in projected
                    if index is not None and from_chapter <= index <= to_chapter
                ),
                default=None,
            )
            values = [value for value in (maximum, changed_max) if value is not None]
            maximum = max(values) if values else None
        return maximum

    async def get_by_chapter_range_page_after(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
        *,
        after: tuple[int, int, uuid.UUID] | None,
        limit: int,
        order_transitions: tuple[ChapterOrderTransition, ...] | None = None,
    ) -> list[MemoryEvent]:
        if order_transitions is None:
            order_transitions = await self.get_chapter_order_transitions(db, novel_id)
        touched = affected_chapter_indices(order_transitions)
        candidates = candidate_chapter_indices(
            from_chapter, to_chapter, order_transitions
        )
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
            MemoryEvent.chapter_index <= to_chapter,
            MemoryEvent.source_stale.is_(False),
        ]
        if order_transitions and touched:
            conditions.append(MemoryEvent.chapter_index.not_in(touched))
        if after is not None:
            after_chapter, after_sequence, after_id = after
            conditions.append(
                or_(
                    MemoryEvent.chapter_index > after_chapter,
                    and_(
                        MemoryEvent.chapter_index == after_chapter,
                        MemoryEvent.sequence > after_sequence,
                    ),
                    and_(
                        MemoryEvent.chapter_index == after_chapter,
                        MemoryEvent.sequence == after_sequence,
                        MemoryEvent.id > after_id,
                    ),
                )
            )
        stmt = (
            select(MemoryEvent)
            .where(*conditions)
            .order_by(MemoryEvent.chapter_index, MemoryEvent.sequence, MemoryEvent.id)
        )
        if not order_transitions or not touched:
            result = await db.execute(stmt.limit(limit))
            return list(result.scalars().all())
        unaffected = list((await db.scalars(stmt.limit(limit))).all())
        projected = []
        for event in await self._affected_events(db, novel_id, candidates):
            chapter_index = project_current_chapter_index(
                event.chapter_index, event.created_at, order_transitions
            )
            if (
                chapter_index is not None
                and from_chapter <= chapter_index <= to_chapter
                and self._after_cursor(event, chapter_index, after)
            ):
                projected.append(event)
        return sorted(
            [*unaffected, *projected],
            key=lambda event: self._projected_order(event, order_transitions),
        )[:limit]

    async def get_by_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        order_transitions: tuple[ChapterOrderTransition, ...] | None = None,
    ) -> tuple[list[MemoryEvent], int]:
        if order_transitions is None:
            order_transitions = await self.get_chapter_order_transitions(db, novel_id)
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.entity_id == entity_id,
            MemoryEvent.source_stale.is_(False),
        ]
        affected = affected_chapter_indices(order_transitions)
        if not order_transitions or not affected:
            total = int(
                await db.scalar(select(func.count(MemoryEvent.id)).where(*conditions))
                or 0
            )
            stmt = (
                select(MemoryEvent)
                .where(*conditions)
                .offset(skip)
                .limit(limit)
                .order_by(
                    MemoryEvent.chapter_index,
                    MemoryEvent.sequence,
                    MemoryEvent.id,
                )
            )
            result = await db.execute(stmt)
            return list(result.scalars().all()), total

        unaffected_conditions = [*conditions, MemoryEvent.chapter_index.not_in(affected)]
        unaffected_total = int(
            await db.scalar(
                select(func.count(MemoryEvent.id)).where(*unaffected_conditions)
            )
            or 0
        )
        unaffected = list(
            (
                await db.scalars(
                    select(MemoryEvent)
                    .where(*unaffected_conditions)
                    .order_by(
                        MemoryEvent.chapter_index,
                        MemoryEvent.sequence,
                        MemoryEvent.id,
                    )
                    .limit(skip + limit)
                )
            ).all()
        )
        changed = [
            event
            for event in await self._affected_events(db, novel_id, affected)
            if event.entity_id == entity_id
        ]
        combined = sorted(
            [*unaffected, *changed],
            key=lambda event: self._projected_order(event, order_transitions),
        )
        return combined[skip : skip + limit], unaffected_total + len(changed)

    async def delete_by_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        from sqlalchemy import delete

        stmt = delete(MemoryEvent).where(
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def delete_from_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
    ) -> int:
        from sqlalchemy import delete

        stmt = delete(MemoryEvent).where(
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def get_max_sequence(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        stmt = select(func.coalesce(func.max(MemoryEvent.sequence), 0)).where(
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index == chapter_index,
        )
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def replace_scene_events(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        scene_index: int,
        chapter_index: int,
        rows: list[dict],
        producer_family: str | None = None,
    ) -> list[MemoryEvent]:
        """Replace one Scene's derived stream without colliding with sibling Scenes.

        分区替换（V4 E03b，plans/01-EVOLUTION §2.2）：

        - 作者确认事件（author authority）永不参与机器替换；
        - 指定 ``producer_family`` 时，其他家族的派生行同样保留——每个
          producer 只替换自己的产物，空重跑只清空自己家族的派生带；
        - 行携带 ``snapshot_after.meta.event_key`` 时按键匹配原地更新
          （行 ID 与槽位保持不变——输出重排不重建事实，T06）；无键的
          旧数据在同家族内按槽位顺序匹配；
        - 未匹配的本家族行先以 Core 语句立即删除，再插入新行，避免
          ORM 插入先于删除造成唯一键瞬态冲突。
        """
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_scene_events:{novel_id}:{scene_id}"},
            )
        existing = list(
            (
                await db.execute(
                    select(MemoryEvent).where(
                        MemoryEvent.novel_id == novel_id,
                        MemoryEvent.scene_id == scene_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        retained_sequences: set[int] = set()
        family_by_key: dict[str, MemoryEvent] = {}
        family_unkeyed: list[MemoryEvent] = []
        for item in existing:
            sequence = item.scene_sequence
            if (
                sequence is None
                or self.is_authority_event(item)
                or (producer_family is not None and item.source != producer_family)
            ):
                # 作者权威、其他 producer 家族与无序号行不在本调用替换范围。
                if sequence is not None:
                    retained_sequences.add(int(sequence))
                continue
            key = self._event_key(item)
            if key:
                family_by_key[key] = item
            else:
                family_unkeyed.append(item)
        family_unkeyed.sort(key=lambda item: int(item.scene_sequence or 0))

        matched: list[tuple[MemoryEvent, dict]] = []
        fresh_rows: list[dict] = []
        for row in sorted(rows, key=lambda item: int(item["scene_sequence"])):
            key = self._row_event_key(row)
            current = family_by_key.pop(key, None) if key else None
            if current is None and not key and family_unkeyed:
                current = family_unkeyed.pop(0)
            if current is not None:
                matched.append((current, row))
            else:
                fresh_rows.append(row)

        # 先删除本家族未匹配行（Core 立即执行），释放槽位且不与后续插入竞态；
        # 同时从会话摘除对应 ORM 对象，避免身份映射残留幽灵行。
        await db.flush()
        unmatched = [*family_by_key.values(), *family_unkeyed]
        if unmatched:
            await db.execute(
                delete(MemoryEvent).where(
                    MemoryEvent.id.in_([item.id for item in unmatched])
                )
            )
            for item in unmatched:
                db.expunge(item)

        # 匹配行保留原槽位，只更新内容；scene_index 变化时同步重算章内序号。
        occupied_sequences = set(retained_sequences)
        for current, row in matched:
            slot = int(current.scene_sequence or 0)
            occupied_sequences.add(slot)
            values = {
                **row,
                "source_stale": False,
                "novel_id": novel_id,
                "scene_id": scene_id,
                "scene_index": scene_index,
                "chapter_index": chapter_index,
                # The matched row is now bound to the current chapter order.
                "created_at": datetime.now(UTC),
                "scene_sequence": slot,
                "sequence": (scene_index + 1) * 1000 + slot,
            }
            for field, value in values.items():
                setattr(current, field, value)

        # 场景事件序号必须避开章级事件带（1..500）：scene_index 从 0 开始，
        # 若基数为 scene_index*1000，首个场景会与同章章级事件在
        # (novel_id, chapter_index, sequence) 唯一键上互相覆盖
        next_slot = 1
        for row in fresh_rows:
            while next_slot in occupied_sequences:
                next_slot += 1
            slot = next_slot
            next_slot += 1
            db.add(
                MemoryEvent(
                    **{
                        **row,
                        "novel_id": novel_id,
                        "scene_id": scene_id,
                        "scene_index": scene_index,
                        "chapter_index": chapter_index,
                        "scene_sequence": slot,
                        "sequence": (scene_index + 1) * 1000 + slot,
                    }
                )
            )
        await db.flush()
        return await self.get_through_scene(db, novel_id, scene_index, scene_id=scene_id)

    @staticmethod
    def _event_key(item: MemoryEvent) -> str | None:
        payload = item.snapshot_after or {}
        if not isinstance(payload, dict):
            return None
        meta = payload.get("meta") or {}
        key = meta.get("event_key") if isinstance(meta, dict) else None
        return str(key) if key else None

    @staticmethod
    def _row_event_key(row: dict) -> str | None:
        payload = row.get("snapshot_after") or {}
        if not isinstance(payload, dict):
            return None
        meta = payload.get("meta") or {}
        key = meta.get("event_key") if isinstance(meta, dict) else None
        return str(key) if key else None

    @staticmethod
    def is_authority_event(item: MemoryEvent) -> bool:
        """Author-confirmed/authoritative rows are never machine-replaceable."""
        if item.source == "author_confirmation":
            return True
        meta = (item.snapshot_after or {}).get("meta") or {}
        return bool(meta.get("author_confirmed"))

    async def get_through_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_index: int,
        *,
        dimension: str | None = None,
        after_scene_index: int | None = None,
        scene_id: uuid.UUID | None = None,
        allowed_scene_ids: list[uuid.UUID] | None = None,
    ) -> list[MemoryEvent]:
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.scene_id.is_not(None),
            MemoryEvent.scene_index.is_not(None),
            MemoryEvent.scene_index <= scene_index,
            MemoryEvent.source_stale.is_(False),
        ]
        if after_scene_index is not None:
            conditions.append(MemoryEvent.scene_index > after_scene_index)
        if dimension is not None:
            conditions.append(MemoryEvent.dimension == dimension)
        if scene_id is not None:
            conditions.append(MemoryEvent.scene_id == scene_id)
        if allowed_scene_ids is not None:
            if not allowed_scene_ids:
                return []
            conditions.append(MemoryEvent.scene_id.in_(allowed_scene_ids))
        result = await db.execute(
            select(MemoryEvent)
            .where(*conditions)
            .order_by(
                MemoryEvent.scene_index,
                MemoryEvent.scene_sequence,
                MemoryEvent.id,
            )
        )
        return list(result.scalars().all())

    async def append_confirmed_scene_event(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        scene_index: int,
        chapter_index: int,
        row: dict,
        idempotency_key: str,
    ) -> tuple[MemoryEvent, bool]:
        """Append once under the Scene event lock without replacing sibling facts."""
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_scene_events:{novel_id}:{scene_id}"},
            )
        existing = list(
            (
                await db.execute(
                    select(MemoryEvent)
                    .where(
                        MemoryEvent.novel_id == novel_id,
                        MemoryEvent.scene_id == scene_id,
                    )
                    .order_by(MemoryEvent.scene_sequence, MemoryEvent.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for item in existing:
            meta = (item.snapshot_after or {}).get("meta") or {}
            if meta.get("idempotency_key") == idempotency_key:
                return item, False
        scene_sequence = (
            max(
                (int(item.scene_sequence or 0) for item in existing),
                default=0,
            )
            + 1
        )
        if scene_sequence > 500:
            raise ValueError("Too many memory events for Scene")
        event = MemoryEvent(
            **row,
            novel_id=novel_id,
            scene_id=scene_id,
            scene_index=scene_index,
            scene_sequence=scene_sequence,
            chapter_index=chapter_index,
            sequence=(scene_index + 1) * 1000 + scene_sequence,
        )
        db.add(event)
        await db.flush()
        return event, True

    async def earliest_chapter_from_scene(
        self, db: AsyncSession, novel_id: uuid.UUID, scene_index: int
    ) -> int | None:
        return await db.scalar(
            select(func.min(MemoryEvent.chapter_index)).where(
                MemoryEvent.novel_id == novel_id, MemoryEvent.scene_index >= scene_index
            )
        )

    async def invalidate_derived_sources(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        from_scene_index: int | None,
        from_chapter: int | None,
        scene_dimensions: list[tuple[uuid.UUID, str]] | None = None,
    ) -> int:
        """Exclude stale machine events from every replay without erasing history."""
        if scene_dimensions is None:
            windows = []
            if from_scene_index is not None:
                windows.append(MemoryEvent.scene_index >= from_scene_index)
            if from_chapter is not None:
                windows.append(MemoryEvent.chapter_index >= from_chapter)
        else:
            if not scene_dimensions:
                return 0
            windows = [
                or_(
                    *(
                        and_(
                            MemoryEvent.scene_id == scene_id,
                            MemoryEvent.dimension == dimension,
                        )
                        for scene_id, dimension in scene_dimensions
                    )
                )
            ]
        if not windows:
            return 0
        result = await db.execute(
            update(MemoryEvent)
            .where(
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.source_stale.is_(False),
                MemoryEvent.source != "author_confirmation",
                func.coalesce(
                    MemoryEvent.snapshot_after["meta"]["author_confirmed"].as_boolean(),
                    False,
                ).is_(False),
                or_(*windows),
            )
            .values(source_stale=True)
        )
        return result.rowcount

    async def scene_index_changes(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_positions: dict[uuid.UUID, int],
    ) -> list[tuple[uuid.UUID, int, int]]:
        """Read the affected window before acquiring any event write locks."""
        if not scene_positions:
            return []
        rows = (
            await db.execute(
                select(MemoryEvent.scene_id, MemoryEvent.scene_index)
                .where(
                    MemoryEvent.novel_id == novel_id,
                    MemoryEvent.scene_id.in_(list(scene_positions)),
                    MemoryEvent.scene_index.is_not(None),
                )
                .distinct()
            )
        ).all()
        return [
            (scene_id, int(old_index), scene_positions[scene_id])
            for scene_id, old_index in rows
            if scene_id is not None
            and old_index is not None
            and int(old_index) != scene_positions[scene_id]
        ]

    async def align_scene_indices(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_positions: dict[uuid.UUID, int],
    ) -> int | None:
        """Align denormalized event order with the authoritative Scene identity."""
        mismatches = await self.scene_index_changes(db, novel_id, scene_positions)
        if not mismatches:
            return None
        earliest = min(
            min(old_index, new_index) for _, old_index, new_index in mismatches
        )
        # Release the old chapter slots before swapping two Scenes in that chapter.
        await db.execute(
            update(MemoryEvent)
            .where(
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.scene_id.in_([scene_id for scene_id, _, _ in mismatches]),
            )
            .values(sequence=-MemoryEvent.sequence)
        )
        for scene_id, _, new_index in mismatches:
            await db.execute(
                update(MemoryEvent)
                .where(
                    MemoryEvent.novel_id == novel_id,
                    MemoryEvent.scene_id == scene_id,
                )
                .values(
                    scene_index=new_index,
                    # sequence 由 scene_index 派生：重排索引时必须同步重算，
                    # 否则该场景后续写入会按新基数插入而与旧行失联
                    sequence=(new_index + 1) * 1000
                    + func.coalesce(MemoryEvent.scene_sequence, 0),
                )
            )
        await db.flush()
        return earliest

    async def count_unanchored_through_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        result = await db.execute(
            select(func.count(MemoryEvent.id)).where(
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.chapter_index <= chapter_index,
                MemoryEvent.scene_id.is_(None),
                MemoryEvent.source_stale.is_(False),
            )
        )
        return int(result.scalar() or 0)


class DeltaLogRepository:
    """Bounded, novel-scoped reads for workflow-owned delta logs."""

    @staticmethod
    def _active_workflow_conditions(
        novel_id: uuid.UUID,
        workflow_id: str,
        *,
        dialect_name: str,
    ) -> list[ColumnElement[bool]]:
        workflow_value = DeltaLog.meta["workflow_id"]
        auto_ingested_value = DeltaLog.meta["auto_ingested"]
        rolled_back_value = DeltaLog.meta["rolled_back"]
        conditions: list[ColumnElement[bool]] = [
            DeltaLog.novel_id == novel_id,
            DeltaLog.source == "deep_import",
        ]
        if dialect_name == "sqlite":
            workflow_type = func.json_type(DeltaLog.meta, '$."workflow_id"')
            auto_ingested_type = func.json_type(DeltaLog.meta, '$."auto_ingested"')
            rolled_back_type = func.json_type(DeltaLog.meta, '$."rolled_back"')
            return [
                *conditions,
                workflow_type == "text",
                workflow_value.as_string() == workflow_id,
                auto_ingested_type == "true",
                or_(rolled_back_type.is_(None), rolled_back_type != "true"),
            ]
        if dialect_name == "postgresql":
            workflow_type = func.json_typeof(workflow_value)
            auto_ingested_type = func.json_typeof(auto_ingested_value)
            rolled_back_type = func.json_typeof(rolled_back_value)
            auto_ingested_is_true = case(
                (
                    auto_ingested_type == "boolean",
                    auto_ingested_value.as_boolean(),
                ),
                else_=False,
            ).is_(True)
            rolled_back_is_not_true = case(
                (
                    rolled_back_type == "boolean",
                    rolled_back_value.as_boolean(),
                ),
                else_=False,
            ).is_(False)
            return [
                *conditions,
                workflow_type == "string",
                workflow_value.as_string() == workflow_id,
                auto_ingested_is_true,
                rolled_back_is_not_true,
            ]
        rolled_back = rolled_back_value.as_boolean()
        return [
            *conditions,
            workflow_value.as_string() == workflow_id,
            auto_ingested_value.as_boolean().is_(True),
            or_(rolled_back.is_(None), rolled_back.is_(False)),
        ]

    @staticmethod
    def _dialect_name(db: AsyncSession) -> str:
        bind = db.get_bind()
        return bind.dialect.name if bind is not None else ""

    async def get_active_by_workflow_page_after(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        workflow_id: str,
        *,
        after_id: uuid.UUID | None,
        limit: int,
        for_update: bool = False,
    ) -> list[DeltaLog]:
        conditions = self._active_workflow_conditions(
            novel_id,
            workflow_id,
            dialect_name=self._dialect_name(db),
        )
        if after_id is not None:
            conditions.append(DeltaLog.id > after_id)
        stmt = select(DeltaLog).where(*conditions).order_by(DeltaLog.id).limit(limit)
        if for_update:
            stmt = stmt.with_for_update()
        result = await db.execute(stmt)
        return list(result.scalars().all())


class SnapshotRepository:
    """记忆快照数据访问"""

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        chapter_index: int,
        full_state: dict,
        events_until: int | None = None,
    ) -> MemorySnapshot:
        await self._lock_snapshot_chapter(db, novel_id, chapter_index)
        await db.execute(
            update(MemorySnapshot)
            .where(
                MemorySnapshot.novel_id == novel_id,
                MemorySnapshot.chapter_index == chapter_index,
                MemorySnapshot.status == "current",
            )
            .values(status="stale")
        )
        snapshot = MemorySnapshot(
            novel_id=novel_id,
            chapter_index=chapter_index,
            status="current",
            full_state=full_state,
            events_until=events_until,
        )
        db.add(snapshot)
        await db.flush()
        return snapshot

    async def _lock_snapshot_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_snapshots:{novel_id}:{chapter_index}"},
            )

    async def get_latest(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> MemorySnapshot | None:
        stmt = (
            select(MemorySnapshot)
            .where(
                MemorySnapshot.novel_id == novel_id,
                MemorySnapshot.chapter_index == chapter_index,
                MemorySnapshot.status == "current",
            )
            .order_by(MemorySnapshot.created_at.desc(), MemorySnapshot.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_nearest(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> MemorySnapshot | None:
        """获取 ≤ chapter_index 的最近一个 current 快照"""
        stmt = (
            select(MemorySnapshot)
            .where(
                MemorySnapshot.novel_id == novel_id,
                MemorySnapshot.chapter_index <= chapter_index,
                MemorySnapshot.status == "current",
            )
            .order_by(MemorySnapshot.chapter_index.desc(), MemorySnapshot.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[MemorySnapshot]:
        stmt = (
            select(MemorySnapshot)
            .where(MemorySnapshot.novel_id == novel_id)
            .order_by(MemorySnapshot.chapter_index, MemorySnapshot.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_status_summary(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> tuple[int, int | None, int | None, int | None]:
        stale_snapshot = aliased(MemorySnapshot)
        current_snapshot = aliased(MemorySnapshot)
        actionable_stale_from = (
            select(func.min(stale_snapshot.chapter_index))
            .where(
                stale_snapshot.novel_id == novel_id,
                stale_snapshot.status == "stale",
                ~select(current_snapshot.id)
                .where(
                    current_snapshot.novel_id == stale_snapshot.novel_id,
                    current_snapshot.chapter_index == stale_snapshot.chapter_index,
                    current_snapshot.status == "current",
                )
                .exists(),
            )
            .scalar_subquery()
        )
        stmt = select(
            func.count(MemorySnapshot.id),
            func.max(MemorySnapshot.chapter_index),
            func.max(
                case(
                    (MemorySnapshot.status == "current", MemorySnapshot.chapter_index),
                    else_=None,
                )
            ),
            actionable_stale_from,
        ).where(MemorySnapshot.novel_id == novel_id)
        row = (await db.execute(stmt)).one()
        return int(row[0] or 0), row[1], row[2], row[3]

    async def mark_stale_from(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
    ) -> int:
        stmt = (
            update(MemorySnapshot)
            .where(
                MemorySnapshot.novel_id == novel_id,
                MemorySnapshot.chapter_index >= from_chapter,
                MemorySnapshot.status == "current",
            )
            .values(status="stale")
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def delete_stale(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        from sqlalchemy import delete

        stmt = delete(MemorySnapshot).where(
            MemorySnapshot.novel_id == novel_id,
            MemorySnapshot.status == "stale",
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount


class SceneCheckpointRepository:
    """Versioned current checkpoint reads and fail-closed supersede writes."""

    async def get_by_id(
        self, db: AsyncSession, novel_id: uuid.UUID, checkpoint_id: uuid.UUID
    ) -> MemorySceneCheckpoint | None:
        return await db.scalar(
            select(MemorySceneCheckpoint).where(
                MemorySceneCheckpoint.novel_id == novel_id,
                MemorySceneCheckpoint.id == checkpoint_id,
            )
        )

    async def list_current_for_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
    ) -> list[MemorySceneCheckpoint]:
        result = await db.execute(
            select(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == novel_id,
                MemorySceneCheckpoint.scene_id == scene_id,
                MemorySceneCheckpoint.is_current.is_(True),
            )
            .order_by(MemorySceneCheckpoint.dimension)
        )
        return list(result.scalars().all())

    async def list_history_for_scene(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        *,
        dimension: str | None = None,
    ) -> list[MemorySceneCheckpoint]:
        """按创建时间倒序列出该 Scene 全部 checkpoint 行（含已 supersede）。

        P2-A 历史回开的数据来源：只读本 novel，不做任何写入或 supersede。
        """
        conditions = [
            MemorySceneCheckpoint.novel_id == novel_id,
            MemorySceneCheckpoint.scene_id == scene_id,
        ]
        if dimension is not None:
            conditions.append(MemorySceneCheckpoint.dimension == dimension)
        result = await db.execute(
            select(MemorySceneCheckpoint)
            .where(*conditions)
            .order_by(
                MemorySceneCheckpoint.created_at.desc(),
                MemorySceneCheckpoint.id.desc(),
            )
        )
        return list(result.scalars().all())

    async def get_current(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        dimension: str,
        *,
        for_update: bool = False,
    ) -> MemorySceneCheckpoint | None:
        stmt = select(MemorySceneCheckpoint).where(
            MemorySceneCheckpoint.novel_id == novel_id,
            MemorySceneCheckpoint.scene_id == scene_id,
            MemorySceneCheckpoint.dimension == dimension,
            MemorySceneCheckpoint.is_current.is_(True),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def lock_current(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        dimension: str,
    ) -> MemorySceneCheckpoint | None:
        """Serialize repair/replace writers in one consistent lock order."""
        await self._lock_dimension(db, novel_id, scene_id, dimension)
        return await self.get_current(
            db,
            novel_id,
            scene_id,
            dimension,
            for_update=True,
        )

    async def supersede_system_from(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_index: int,
        dimensions: list[str],
        *,
        include_start: bool,
    ) -> int:
        comparison = (
            MemorySceneCheckpoint.scene_index >= scene_index
            if include_start
            else MemorySceneCheckpoint.scene_index > scene_index
        )
        result = await db.execute(
            update(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == novel_id,
                comparison,
                MemorySceneCheckpoint.dimension.in_(dimensions),
                MemorySceneCheckpoint.is_current.is_(True),
                MemorySceneCheckpoint.source == "system_generated",
                MemorySceneCheckpoint.confirmed.is_(False),
            )
            .values(is_current=False, status="superseded")
        )
        await db.flush()
        return int(result.rowcount or 0)

    async def supersede_system_consumers(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        consumers: list[tuple[uuid.UUID, str]],
    ) -> int:
        if not consumers:
            return 0
        result = await db.execute(
            update(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == novel_id,
                or_(
                    *(
                        and_(
                            MemorySceneCheckpoint.scene_id == scene_id,
                            MemorySceneCheckpoint.dimension == dimension,
                        )
                        for scene_id, dimension in consumers
                    )
                ),
                MemorySceneCheckpoint.is_current.is_(True),
                MemorySceneCheckpoint.source == "system_generated",
                MemorySceneCheckpoint.confirmed.is_(False),
            )
            .values(is_current=False, status="superseded")
        )
        await db.flush()
        return int(result.rowcount or 0)

    async def mark_pending_revalidation(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        from_scene_index: int | None = None,
        consumers: list[tuple[uuid.UUID, str]] | None = None,
    ) -> int:
        if consumers is None:
            if from_scene_index is None:
                return 0
            scope = MemorySceneCheckpoint.scene_index >= from_scene_index
        else:
            if not consumers:
                return 0
            scope = or_(
                *(
                    and_(
                        MemorySceneCheckpoint.scene_id == scene_id,
                        MemorySceneCheckpoint.dimension == dimension,
                    )
                    for scene_id, dimension in consumers
                )
            )
        rows = await db.scalars(
            select(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == novel_id,
                scope,
                MemorySceneCheckpoint.is_current.is_(True),
                or_(
                    MemorySceneCheckpoint.source != "system_generated",
                    MemorySceneCheckpoint.confirmed.is_(True),
                ),
            )
            .with_for_update()
        )
        reason = "来源已变化，作者确认状态待重验"
        affected = list(rows)
        for row in affected:
            row.status = "needs_revalidation"
            if reason not in (row.gap_reason or ""):
                row.gap_reason = (
                    f"{row.gap_reason}；{reason}" if row.gap_reason else reason
                )
        await db.flush()
        return len(affected)

    async def replace_system(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        scene_index: int,
        dimension: str,
        values: dict,
    ) -> MemorySceneCheckpoint:
        await self._lock_dimension(db, novel_id, scene_id, dimension)
        current = await self.get_current(
            db, novel_id, scene_id, dimension, for_update=True
        )
        if current is not None and (
            current.source != "system_generated" or current.confirmed
        ):
            return current
        if current is not None and current.scene_index == scene_index:
            comparable_fields = (
                "status",
                "state_json",
                "evidence_refs",
                "display_summary",
                "source_hash",
                "gap_reason",
                "retry_count",
            )
            if all(
                getattr(current, field) == values.get(field)
                for field in comparable_fields
            ):
                return current
        if current is not None:
            current.is_current = False
            current.status = "superseded"
        item = MemorySceneCheckpoint(
            novel_id=novel_id,
            scene_id=scene_id,
            scene_index=scene_index,
            stage_index=scene_index + 1,
            dimension=dimension,
            source="system_generated",
            supersedes_id=current.id if current else None,
            **values,
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def _lock_dimension(
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        dimension: str,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_scene_checkpoint:{novel_id}:{scene_id}:{dimension}"},
            )

    async def create_manual_repair(
        self,
        db: AsyncSession,
        *,
        current: MemorySceneCheckpoint,
        state_json: dict,
        evidence_refs: list,
        display_summary: str,
        source_hash: str,
        decision_summary: str,
    ) -> MemorySceneCheckpoint:
        if current.source != "system_generated" or current.confirmed:
            raise ValueError("manual or confirmed checkpoints cannot be superseded")
        current.is_current = False
        current.status = "superseded"
        repaired = MemorySceneCheckpoint(
            novel_id=current.novel_id,
            scene_id=current.scene_id,
            scene_index=current.scene_index,
            stage_index=current.stage_index,
            dimension=current.dimension,
            status="ready",
            source="manual",
            confirmed=True,
            is_current=True,
            state_json=state_json,
            evidence_refs=evidence_refs,
            display_summary=display_summary,
            source_hash=source_hash,
            decision_summary=decision_summary,
            supersedes_id=current.id,
        )
        db.add(repaired)
        await db.flush()
        return repaired


class SceneSnapshotRepository:
    async def supersede_from(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_index: int,
        *,
        include_start: bool,
    ) -> int:
        """Invalidate sparse projections after their event/checkpoint source changed."""
        comparison = (
            MemorySceneSnapshot.scene_index >= scene_index
            if include_start
            else MemorySceneSnapshot.scene_index > scene_index
        )
        result = await db.execute(
            update(MemorySceneSnapshot)
            .where(
                MemorySceneSnapshot.novel_id == novel_id,
                MemorySceneSnapshot.scene_index.is_not(None),
                comparison,
                MemorySceneSnapshot.is_current.is_(True),
            )
            .values(is_current=False, is_latest=False)
        )
        await db.flush()
        return int(result.rowcount or 0)

    async def ensure_stage0(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        empty_state: dict,
        source_hash: str,
    ) -> MemorySceneSnapshot:
        await self._lock_stage(db, novel_id, 0)
        current = (
            await db.execute(
                select(MemorySceneSnapshot).where(
                    MemorySceneSnapshot.novel_id == novel_id,
                    MemorySceneSnapshot.stage_index == 0,
                    MemorySceneSnapshot.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        if current is not None:
            return current
        item = MemorySceneSnapshot(
            novel_id=novel_id,
            stage_index=0,
            snapshot_reasons=["initial"],
            full_state=empty_state,
            source_hash=source_hash,
            is_current=True,
            is_latest=False,
        )
        db.add(item)
        await db.flush()
        return item

    async def replace_for_scene(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        scene_index: int,
        reasons: list[str],
        full_state: dict,
        source_hash: str,
        is_latest: bool,
    ) -> MemorySceneSnapshot:
        stage_index = scene_index + 1
        await self._lock_stage(db, novel_id, stage_index)
        await db.execute(
            update(MemorySceneSnapshot)
            .where(
                MemorySceneSnapshot.novel_id == novel_id,
                MemorySceneSnapshot.stage_index == stage_index,
                MemorySceneSnapshot.is_current.is_(True),
            )
            .values(is_current=False, is_latest=False)
        )
        if is_latest:
            await db.execute(
                update(MemorySceneSnapshot)
                .where(
                    MemorySceneSnapshot.novel_id == novel_id,
                    MemorySceneSnapshot.is_latest.is_(True),
                )
                .values(is_latest=False)
            )
        item = MemorySceneSnapshot(
            novel_id=novel_id,
            scene_id=scene_id,
            scene_index=scene_index,
            stage_index=stage_index,
            snapshot_reasons=reasons,
            full_state=full_state,
            source_hash=source_hash,
            is_current=True,
            is_latest=is_latest,
        )
        db.add(item)
        await db.flush()
        return item

    @staticmethod
    async def _lock_stage(
        db: AsyncSession,
        novel_id: uuid.UUID,
        stage_index: int,
    ) -> None:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"memory_scene_snapshot:{novel_id}:{stage_index}"},
            )
