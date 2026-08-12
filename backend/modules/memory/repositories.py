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
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from modules.memory.models import (
    DeltaLog,
    MemoryEvent,
    MemorySceneCheckpoint,
    MemorySceneSnapshot,
    MemorySnapshot,
)
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

    async def replace_scene_events(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        scene_id: uuid.UUID,
        scene_index: int,
        chapter_index: int,
        rows: list[dict],
    ) -> list[MemoryEvent]:
        """Replace one Scene stream without colliding with sibling Scenes."""
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
        by_sequence = {item.scene_sequence: item for item in existing}
        chapter_base = scene_index * 1000
        for row in rows:
            local_sequence = int(row["scene_sequence"])
            values = {
                **row,
                "novel_id": novel_id,
                "scene_id": scene_id,
                "scene_index": scene_index,
                "chapter_index": chapter_index,
                "sequence": chapter_base + local_sequence,
            }
            current = by_sequence.pop(local_sequence, None)
            if current is None:
                db.add(MemoryEvent(**values))
                continue
            for key, value in values.items():
                setattr(current, key, value)
        for stale in by_sequence.values():
            await db.delete(stale)
        await db.flush()
        return await self.get_through_scene(db, novel_id, scene_index, scene_id=scene_id)

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

    async def align_scene_indices(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_positions: dict[uuid.UUID, int],
    ) -> int | None:
        """Align denormalized event order with the authoritative Scene identity."""
        if not scene_positions:
            return None
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
        mismatches = [
            (scene_id, int(old_index), scene_positions[scene_id])
            for scene_id, old_index in rows
            if scene_id is not None
            and old_index is not None
            and int(old_index) != scene_positions[scene_id]
        ]
        if not mismatches:
            return None
        earliest = min(
            min(old_index, new_index) for _, old_index, new_index in mismatches
        )
        for scene_id, _, new_index in mismatches:
            await db.execute(
                update(MemoryEvent)
                .where(
                    MemoryEvent.novel_id == novel_id,
                    MemoryEvent.scene_id == scene_id,
                )
                .values(scene_index=new_index)
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

    async def get_latest_ready_before(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        scene_index: int,
        dimension: str,
    ) -> MemorySceneCheckpoint | None:
        result = await db.execute(
            select(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == novel_id,
                MemorySceneCheckpoint.scene_index < scene_index,
                MemorySceneCheckpoint.dimension == dimension,
                MemorySceneCheckpoint.is_current.is_(True),
                MemorySceneCheckpoint.status == "ready",
            )
            .order_by(MemorySceneCheckpoint.scene_index.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

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
