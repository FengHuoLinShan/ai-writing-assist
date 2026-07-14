"""Coalesced chapter index requests and freshness state."""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.enqueuer import enqueue_task
from modules.rag.contracts import RagIndexReport
from modules.rag.models import RagIndexState

PreparedIndexClaim = Literal["claimed", "source_changed", "fresh"]
PreparedIndexPreflight = Literal["ready", "source_changed", "fresh"]


class RagIndexStateService:
    async def preflight_prepared(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
        source_draft_id: str | None,
        source_content_hash: str | None,
        force: bool = False,
    ) -> PreparedIndexPreflight:
        """Skip expensive embedding when this exact prepared source is fresh."""
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        current_source_id = str(source.id) if source and source.id else None
        current_hash = source.content_hash if source else None
        expected_source_id = str(source_draft_id) if source_draft_id else None
        if current_source_id != expected_source_id or current_hash != source_content_hash:
            return "source_changed"
        if force or source is None or current_source_id is None:
            return "ready"

        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        if (
            state is not None
            and state.status == "succeeded"
            and state.indexed_hash == current_hash
            and state.indexed_source_id == uuid.UUID(current_source_id)
        ):
            return "fresh"
        return "ready"

    async def begin_prepared(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
        source_draft_id: str | None,
        source_content_hash: str | None,
        force: bool = False,
    ) -> PreparedIndexClaim:
        """Claim a precomputed index only while its source is still current.

        The caller may spend significant time generating embeddings before this
        method.  Source validation and the state claim therefore happen together
        under the existing per-index-key transaction lock, immediately before
        the prepared rows are persisted.
        """
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        current_source_id = str(source.id) if source and source.id else None
        current_hash = source.content_hash if source else None
        expected_source_id = str(source_draft_id) if source_draft_id else None
        if current_source_id != expected_source_id or current_hash != source_content_hash:
            return "source_changed"

        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        if state is None:
            state = RagIndexState(
                novel_id=uuid.UUID(str(novel_id)),
                chapter_index=chapter_index,
                content_mode=content_mode,
            )
            db.add(state)
        elif (
            not force
            and source is not None
            and current_source_id is not None
            and state.status == "succeeded"
            and state.indexed_hash == current_hash
            and state.indexed_source_id == uuid.UUID(current_source_id)
        ):
            return "fresh"

        state.requested_source_id = (
            uuid.UUID(expected_source_id) if expected_source_id else None
        )
        state.requested_hash = source_content_hash
        state.status = "running"
        state.error_message = None
        await db.flush()
        return "claimed"

    async def mark_dirty(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
    ) -> dict:
        """Record a new source before an already-scheduled workflow indexes it."""
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        if state is None:
            state = RagIndexState(
                novel_id=uuid.UUID(str(novel_id)),
                chapter_index=chapter_index,
                content_mode=content_mode,
                status="pending",
            )
            db.add(state)
        state.requested_source_id = (
            uuid.UUID(str(source.id)) if source and source.id else None
        )
        state.requested_hash = source.content_hash if source else None
        state.error_message = None
        if state.status != "running":
            state.status = "pending"
        await db.flush()
        return self._state_dict(state, task_id=None)

    async def begin_direct(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
        force: bool = False,
    ) -> bool:
        """Claim synchronous indexing unless another/latest execution owns it."""
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        if state is None:
            state = RagIndexState(
                novel_id=uuid.UUID(str(novel_id)),
                chapter_index=chapter_index,
                content_mode=content_mode,
            )
            db.add(state)
        elif state.status == "running":
            return False
        elif (
            not force
            and source is not None
            and state.status == "succeeded"
            and state.indexed_hash == source.content_hash
            and state.indexed_source_id == uuid.UUID(str(source.id))
        ):
            return False
        state.requested_source_id = (
            uuid.UUID(str(source.id)) if source and source.id else None
        )
        state.requested_hash = source.content_hash if source else None
        state.status = "running"
        state.error_message = None
        await db.flush()
        return True

    async def request(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
    ) -> dict:
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        if state is None:
            state = RagIndexState(
                novel_id=uuid.UUID(str(novel_id)),
                chapter_index=chapter_index,
                content_mode=content_mode,
                status="idle",
            )
            db.add(state)
            await db.flush()
        state.requested_source_id = uuid.UUID(source.id) if source and source.id else None
        state.requested_hash = source.content_hash if source else None
        state.error_message = None
        if (
            source is not None
            and state.indexed_hash == source.content_hash
            and state.indexed_source_id == uuid.UUID(str(source.id))
        ):
            state.status = "succeeded"
            await db.flush()
            return self._state_dict(state, task_id=None)
        task_id = None
        if state.status not in {"pending", "running"}:
            state.status = "pending"
            task_id = enqueue_task(
                db,
                "rag_index_chapter",
                meta={
                    "novel_id": novel_id,
                    "chapter_index": chapter_index,
                    "content_mode": content_mode,
                },
            )
        await db.flush()
        return self._state_dict(state, task_id=task_id)

    async def mark_running(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
    ) -> bool:
        """Claim a queued execution, skipping duplicate or already-fresh work."""
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        if state is None:
            state = RagIndexState(
                novel_id=uuid.UUID(str(novel_id)),
                chapter_index=chapter_index,
                content_mode=content_mode,
                requested_source_id=(
                    uuid.UUID(str(source.id)) if source and source.id else None
                ),
                requested_hash=source.content_hash if source else None,
                status="running",
            )
            db.add(state)
            await db.flush()
            return True
        if state.status == "running":
            return False

        # A queued task may outlive the source version captured when it was
        # requested.  Refresh the target when the task actually claims the
        # state row so finish() compares its report with the source it was
        # asked to index, instead of requeueing forever against a stale hash.
        state.requested_source_id = (
            uuid.UUID(str(source.id)) if source and source.id else None
        )
        state.requested_hash = source.content_hash if source else None
        if (
            source is not None
            and state.status == "succeeded"
            and state.indexed_hash == source.content_hash
            and state.indexed_source_id == uuid.UUID(str(source.id))
        ):
            await db.flush()
            return False
        state.status = "running"
        await db.flush()
        return True

    async def finish(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        report: RagIndexReport,
    ) -> str | None:
        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=report.chapter_index,
            content_mode=report.content_mode,
            lock=True,
        )
        if state is None:
            return None
        state.indexed_source_id = (
            uuid.UUID(report.source_draft_id) if report.source_draft_id else None
        )
        state.indexed_hash = report.source_content_hash
        state.warnings = list(report.warnings)
        state.error_message = None
        if report.source_content_hash is None:
            state.status = "missing_source"
            await db.flush()
            return None
        if state.requested_hash != report.source_content_hash:
            state.status = "pending"
            task_id = enqueue_task(
                db,
                "rag_index_chapter",
                meta={
                    "novel_id": novel_id,
                    "chapter_index": report.chapter_index,
                    "content_mode": report.content_mode,
                },
            )
            await db.flush()
            return task_id
        state.status = "succeeded"
        await db.flush()
        return None

    async def fail(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
        error: str,
        expected_source_id: str | None = None,
        expected_source_hash: str | None = None,
        match_expected_source: bool = False,
    ) -> bool:
        """Mark only the still-current failed attempt.

        A provider failure is observed after the task released its source-read
        transaction.  Another task may have indexed that source, or a publish
        may have installed a newer source, before this method acquires the
        state lock.  Expected-source fencing prevents the old failure from
        overwriting either outcome.
        """
        await self._lock_state_key(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        source = await self._get_source(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
        )
        state = await self._get(
            db,
            novel_id=novel_id,
            chapter_index=chapter_index,
            content_mode=content_mode,
            lock=True,
        )
        current_source_id = str(source.id) if source and source.id else None
        current_hash = source.content_hash if source else None
        normalized_expected_id = str(expected_source_id) if expected_source_id else None
        if match_expected_source and (
            current_source_id != normalized_expected_id
            or current_hash != expected_source_hash
        ):
            return False

        created_state = state is None
        if created_state:
            state = RagIndexState(
                novel_id=uuid.UUID(str(novel_id)),
                chapter_index=chapter_index,
                content_mode=content_mode,
            )
            db.add(state)
        elif match_expected_source:
            expected_uuid = (
                uuid.UUID(normalized_expected_id) if normalized_expected_id else None
            )
            if (
                state.status in {"succeeded", "missing_source"}
                and state.indexed_source_id == expected_uuid
                and state.indexed_hash == expected_source_hash
            ):
                return False
            if (
                state.requested_source_id != expected_uuid
                or state.requested_hash != expected_source_hash
            ):
                return False
            if state.status not in {"pending", "running", "failed"}:
                return False
        elif state.status not in {"pending", "running", "failed"}:
            # Legacy begin_direct()/fail() callers do not carry an explicit
            # source fence. They may fail the row they already own, but must
            # never turn a completed terminal state back into failed.
            return False

        if match_expected_source or created_state:
            state.requested_source_id = (
                uuid.UUID(str(source.id)) if source and source.id else None
            )
            state.requested_hash = source.content_hash if source else None
        state.status = "failed"
        state.error_message = error[:1000]
        await db.flush()
        return True

    async def summary(self, db: AsyncSession, novel_id: str) -> dict:
        stmt = select(RagIndexState).where(
            RagIndexState.novel_id == uuid.UUID(str(novel_id))
        )
        states = list((await db.execute(stmt)).scalars().all())
        return {
            "by_content_mode": {
                mode: {
                    "total": sum(1 for item in states if item.content_mode == mode),
                    "fresh": sum(
                        1
                        for item in states
                        if item.content_mode == mode
                        and item.status == "succeeded"
                        and item.indexed_hash == item.requested_hash
                        and item.indexed_source_id == item.requested_source_id
                    ),
                    "stale": sum(
                        1
                        for item in states
                        if item.content_mode == mode
                        and (
                            item.status != "succeeded"
                            or item.indexed_hash != item.requested_hash
                            or item.indexed_source_id != item.requested_source_id
                        )
                    ),
                }
                for mode in ("canonical", "working")
            }
        }

    async def freshness(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        content_mode: str,
        chapter_from: int | None = None,
        chapter_to: int | None = None,
    ) -> dict:
        conditions = [
            RagIndexState.novel_id == uuid.UUID(str(novel_id)),
            RagIndexState.content_mode == content_mode,
        ]
        if chapter_from is not None:
            conditions.append(RagIndexState.chapter_index >= chapter_from)
        if chapter_to is not None:
            conditions.append(RagIndexState.chapter_index <= chapter_to)
        states = list(
            (await db.execute(select(RagIndexState).where(*conditions))).scalars().all()
        )
        fresh = [
            item
            for item in states
            if item.status == "succeeded"
            and item.indexed_hash == item.requested_hash
            and item.indexed_source_id == item.requested_source_id
        ]
        return {
            "content_mode": content_mode,
            "total": len(states),
            "fresh": len(fresh),
            "stale": len(states) - len(fresh),
            "statuses": sorted({item.status for item in states}),
        }

    async def _get(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
        lock: bool,
    ) -> RagIndexState | None:
        stmt = select(RagIndexState).where(
            RagIndexState.novel_id == uuid.UUID(str(novel_id)),
            RagIndexState.chapter_index == chapter_index,
            RagIndexState.content_mode == content_mode,
        )
        if lock and db.get_bind().dialect.name == "postgresql":
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def _lock_state_key(
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
    ) -> None:
        bind = db.get_bind()
        if bind is None or bind.dialect.name != "postgresql":
            return
        from sqlalchemy import text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": (f"rag_index_state:{novel_id}:{chapter_index}:{content_mode}")},
        )

    @staticmethod
    async def _get_source(
        db: AsyncSession,
        *,
        novel_id: str,
        chapter_index: int,
        content_mode: str,
    ):
        from modules.writing.facade import list_manuscript_sources

        sources = await list_manuscript_sources(
            db,
            novel_id,
            [chapter_index],
            content_mode=content_mode,
        )
        return sources[0] if sources else None

    @staticmethod
    def _state_dict(state: RagIndexState, *, task_id: str | None) -> dict:
        return {
            "id": str(state.id),
            "novel_id": str(state.novel_id),
            "chapter_index": state.chapter_index,
            "content_mode": state.content_mode,
            "requested_source_id": (
                str(state.requested_source_id) if state.requested_source_id else None
            ),
            "requested_hash": state.requested_hash,
            "indexed_source_id": (
                str(state.indexed_source_id) if state.indexed_source_id else None
            ),
            "indexed_hash": state.indexed_hash,
            "status": state.status,
            "warnings": list(state.warnings or []),
            "error_message": state.error_message,
            "task_id": task_id,
        }
