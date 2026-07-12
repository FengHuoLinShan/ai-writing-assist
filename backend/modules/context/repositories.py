"""Persistence helpers for context records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.models import (
    ContextConfirmation,
    ContextRetrievalTrace,
    ContextSnapshot,
)


class ContextConfirmationRepository:
    """Data access for AI reference confirmations."""

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        action: str,
        task: str,
        scope: str,
        context_mode: str,
        include_pending_objects: bool,
        excluded_asset_ids: dict[str, list[str]],
        selected_asset_ids: dict[str, list[str]],
        user_note: str | None,
        compile_options: dict,
        warnings: list[str],
    ) -> ContextConfirmation:
        record = ContextConfirmation(
            novel_id=novel_id,
            action=action,
            task=task,
            scope=scope,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            excluded_asset_ids=excluded_asset_ids,
            selected_asset_ids=selected_asset_ids,
            user_note=user_note,
            compile_options=compile_options,
            warnings=warnings,
            result_refs=[],
            result_status="confirmed",
            stale_reasons=[],
        )
        db.add(record)
        await db.flush()
        return record

    async def get(
        self,
        db: AsyncSession,
        confirmation_id: uuid.UUID,
    ) -> ContextConfirmation | None:
        return await db.get(ContextConfirmation, confirmation_id)

    async def update_tracking(
        self,
        db: AsyncSession,
        record: ContextConfirmation,
        *,
        result_refs: list[dict[str, str]] | None = None,
        result_status: str | None = None,
        stale_reasons: list[str] | None = None,
    ) -> ContextConfirmation:
        if result_refs is not None:
            record.result_refs = result_refs
        if result_status is not None:
            record.result_status = result_status
        if stale_reasons is not None:
            record.stale_reasons = stale_reasons
        await db.flush()
        return record

    async def update_tracking_many(
        self,
        db: AsyncSession,
        updates: list[tuple[ContextConfirmation, list[str]]],
        *,
        result_status: str,
    ) -> int:
        for record, stale_reasons in updates:
            record.result_status = result_status
            record.stale_reasons = stale_reasons
        if updates:
            await db.flush()
        return len(updates)

    async def list_by_asset_ref(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        asset_type: str,
        asset_id: str,
    ) -> list[ContextConfirmation]:
        stmt = select(ContextConfirmation).where(
            ContextConfirmation.novel_id == novel_id,
        )
        result = await db.execute(stmt)
        records = list(result.scalars().all())
        normalized_asset_id = str(asset_id)
        matched: list[ContextConfirmation] = []
        for record in records:
            selected = record.selected_asset_ids or {}
            selected_ids = {str(value) for value in selected.get(asset_type, [])}
            if normalized_asset_id in selected_ids:
                matched.append(record)
                continue
            result_ref_ids = {
                str(ref.get("id"))
                for ref in record.result_refs or []
                if isinstance(ref, dict) and ref.get("id") is not None
            }
            if normalized_asset_id in result_ref_ids:
                matched.append(record)
        return matched


class ContextSnapshotRepository:
    """Data access for automated context snapshots."""

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        task_id: str | None,
        workflow_id: str | None,
        phase: str,
        operation: str,
        scene_id: str | None,
        scene_index: int | None,
        chapter_index: int | None,
        context_mode: str,
        include_pending_objects: bool,
        attempt: int,
        prompt_hash: str,
        prompt_name: str,
        model: str,
        compile_options: dict,
        included_asset_ids: dict,
        excluded_asset_ids: dict,
        context_summary: dict,
        section_metadata: dict,
        token_metadata: dict,
        rendered_context: str | None,
        rendered_context_expires_at: datetime | None,
    ) -> ContextSnapshot:
        snapshot = ContextSnapshot(
            novel_id=novel_id,
            task_id=task_id,
            workflow_id=workflow_id,
            phase=phase,
            operation=operation,
            scene_id=scene_id,
            scene_index=scene_index,
            chapter_index=chapter_index,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            status="running",
            attempt=attempt,
            prompt_hash=prompt_hash,
            prompt_name=prompt_name,
            model=model,
            compile_options=compile_options,
            included_asset_ids=included_asset_ids,
            excluded_asset_ids=excluded_asset_ids,
            context_summary=context_summary,
            section_metadata=section_metadata,
            token_metadata=token_metadata,
            rendered_context=rendered_context,
            result_refs=[],
            rendered_context_expires_at=rendered_context_expires_at,
        )
        db.add(snapshot)
        await db.flush()
        return snapshot

    async def get(
        self,
        db: AsyncSession,
        snapshot_id: uuid.UUID,
    ) -> ContextSnapshot | None:
        return await db.get(ContextSnapshot, snapshot_id)

    async def list_for_novel(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        workflow_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContextSnapshot]:
        stmt = select(ContextSnapshot).where(ContextSnapshot.novel_id == novel_id)
        if workflow_id is not None:
            stmt = stmt.where(ContextSnapshot.workflow_id == workflow_id)
        if task_id is not None:
            stmt = stmt.where(ContextSnapshot.task_id == task_id)
        stmt = (
            stmt.order_by(ContextSnapshot.created_at, ContextSnapshot.id)
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_maintenance(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        workflow_id: str | None = None,
    ) -> list[ContextSnapshot]:
        stmt = select(ContextSnapshot).where(ContextSnapshot.novel_id == novel_id)
        if workflow_id is not None:
            stmt = stmt.where(ContextSnapshot.workflow_id == workflow_id)
        stmt = stmt.order_by(ContextSnapshot.created_at, ContextSnapshot.id)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def mark_succeeded(
        self,
        db: AsyncSession,
        snapshot: ContextSnapshot,
        *,
        result_refs: list[dict],
    ) -> ContextSnapshot:
        snapshot.status = "succeeded"
        snapshot.result_refs = result_refs
        snapshot.error_kind = None
        snapshot.error_message = None
        await db.flush()
        return snapshot

    async def mark_failed(
        self,
        db: AsyncSession,
        snapshot: ContextSnapshot,
        *,
        error_kind: str,
        error_message: str,
    ) -> ContextSnapshot:
        snapshot.status = "failed"
        snapshot.error_kind = error_kind
        snapshot.error_message = error_message
        await db.flush()
        return snapshot

    async def prune_rendered_context(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID | None,
        workflow_id: str | None = None,
        retain_latest_full_context_per_project: int = 200,
        dry_run: bool = False,
    ) -> int:
        stmt = select(ContextSnapshot).where(
            ContextSnapshot.rendered_context.is_not(None)
        )
        if novel_id is not None:
            stmt = stmt.where(ContextSnapshot.novel_id == novel_id)
        stmt = stmt.order_by(
            ContextSnapshot.novel_id,
            ContextSnapshot.created_at.desc(),
            ContextSnapshot.id.desc(),
        )
        result = await db.execute(stmt)
        snapshots = list(result.scalars().all())

        now = datetime.now(UTC)
        seen_by_novel: dict[uuid.UUID, int] = {}
        changed = 0
        for snapshot in snapshots:
            seen = seen_by_novel.get(snapshot.novel_id, 0)
            seen_by_novel[snapshot.novel_id] = seen + 1
            expires_at = snapshot.rendered_context_expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            expired = expires_at is not None and expires_at <= now
            outside_latest = seen >= retain_latest_full_context_per_project
            if expired or outside_latest:
                changed += 1
                if not dry_run:
                    snapshot.rendered_context = None
                    snapshot.rendered_context_expires_at = None

        if changed and not dry_run:
            await db.flush()
        return changed


class ContextRetrievalTraceRepository:
    """Persistence for privacy-safe context retrieval diagnostics."""

    async def create(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        content_mode: str,
        consumer_action: str,
        retrieval_purpose: str,
        reveal_mode: str,
        scene_id: str | None,
        chapter_index: int | None,
        plan_version: str,
        plan_hash: str,
        clause_summaries: list[dict],
        candidate_count: int,
        unique_count: int,
        hydrated_count: int,
        drop_counts: dict[str, int],
        safe_empty_reason: str | None,
        degraded: bool,
        warning_codes: list[str],
        latency_metadata: dict[str, float],
    ) -> ContextRetrievalTrace:
        record = ContextRetrievalTrace(
            novel_id=novel_id,
            content_mode=content_mode,
            consumer_action=consumer_action,
            retrieval_purpose=retrieval_purpose,
            reveal_mode=reveal_mode,
            scene_id=scene_id,
            chapter_index=chapter_index,
            plan_version=plan_version,
            plan_hash=plan_hash,
            clause_summaries=clause_summaries,
            candidate_count=candidate_count,
            unique_count=unique_count,
            hydrated_count=hydrated_count,
            drop_counts=drop_counts,
            safe_empty_reason=safe_empty_reason,
            degraded=degraded,
            warning_codes=warning_codes,
            latency_metadata=latency_metadata,
        )
        db.add(record)
        await db.flush()
        return record

    async def list_for_novel(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        content_mode: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContextRetrievalTrace]:
        stmt = select(ContextRetrievalTrace).where(
            ContextRetrievalTrace.novel_id == novel_id
        )
        if content_mode is not None:
            stmt = stmt.where(ContextRetrievalTrace.content_mode == content_mode)
        if since is not None:
            stmt = stmt.where(ContextRetrievalTrace.created_at >= since)
        stmt = (
            stmt.order_by(
                ContextRetrievalTrace.created_at.desc(),
                ContextRetrievalTrace.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def prune(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        retention_days: int,
        retain_latest: int,
        dry_run: bool,
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        records = await self.list_for_novel(
            db,
            novel_id=novel_id,
            since=None,
            limit=100_000,
        )
        stale_ids = {
            record.id
            for index, record in enumerate(records)
            if self._is_before(record.created_at, cutoff) or index >= retain_latest
        }
        if stale_ids and not dry_run:
            await db.execute(
                delete(ContextRetrievalTrace).where(
                    ContextRetrievalTrace.novel_id == novel_id,
                    ContextRetrievalTrace.id.in_(stale_ids),
                )
            )
            await db.flush()
        return len(stale_ids)

    @staticmethod
    def _is_before(value: datetime, cutoff: datetime) -> bool:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < cutoff
