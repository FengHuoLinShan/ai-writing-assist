"""
Memory 数据访问层

- EventRepository: memory_events 表操作
- SnapshotRepository: memory_snapshots 表操作
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from modules.memory.models import DeltaLog, MemoryEvent, MemorySnapshot
from shared.constants import DEFAULT_PAGE_SIZE


class EventRepository:
    """记忆事件数据访问"""

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
            ):
                setattr(existing, field, row.get(field))

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
    ) -> list[MemoryEvent]:
        stmt = (
            select(MemoryEvent)
            .where(
                MemoryEvent.novel_id == novel_id,
                MemoryEvent.chapter_index >= from_chapter,
                MemoryEvent.chapter_index <= to_chapter,
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
    ) -> int:
        stmt = select(func.count(MemoryEvent.id)).where(
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
            MemoryEvent.chapter_index <= to_chapter,
        )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def get_max_chapter_in_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
    ) -> int | None:
        stmt = select(func.max(MemoryEvent.chapter_index)).where(
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
            MemoryEvent.chapter_index <= to_chapter,
        )
        result = await db.execute(stmt)
        return result.scalar_one()

    async def get_by_chapter_range_page_after(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        from_chapter: int,
        to_chapter: int,
        *,
        after: tuple[int, int, uuid.UUID] | None,
        limit: int,
    ) -> list[MemoryEvent]:
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.chapter_index >= from_chapter,
            MemoryEvent.chapter_index <= to_chapter,
        ]
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
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[MemoryEvent], int]:
        conditions = [
            MemoryEvent.novel_id == novel_id,
            MemoryEvent.entity_id == entity_id,
        ]
        count_stmt = select(func.count(MemoryEvent.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(MemoryEvent)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(MemoryEvent.chapter_index, MemoryEvent.sequence, MemoryEvent.id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), total

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
            auto_ingested_type = func.json_type(
                DeltaLog.meta, '$."auto_ingested"'
            )
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

    async def count_active_by_workflow(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        workflow_id: str,
    ) -> int:
        stmt = select(func.count(DeltaLog.id)).where(
            *self._active_workflow_conditions(
                novel_id,
                workflow_id,
                dialect_name=self._dialect_name(db),
            )
        )
        result = await db.execute(stmt)
        return int(result.scalar_one())

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
        stmt = select(
            func.count(MemorySnapshot.id),
            func.max(MemorySnapshot.chapter_index),
            func.max(
                case(
                    (MemorySnapshot.status == "current", MemorySnapshot.chapter_index),
                    else_=None,
                )
            ),
            func.min(
                case(
                    (MemorySnapshot.status == "stale", MemorySnapshot.chapter_index),
                    else_=None,
                )
            ),
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
