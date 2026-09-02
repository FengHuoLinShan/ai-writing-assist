"""Persistence helpers for context records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    BigInteger,
    String,
    and_,
    case,
    cast,
    delete,
    func,
    literal,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.models import (
    ContextConfirmation,
    ContextConfirmationAssetRef,
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
        *,
        novel_id: uuid.UUID,
        for_update: bool = False,
    ) -> ContextConfirmation | None:
        stmt = select(ContextConfirmation).where(
            ContextConfirmation.id == confirmation_id,
            ContextConfirmation.novel_id == novel_id,
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await db.execute(stmt)).scalar_one_or_none()

    async def replace_asset_refs(
        self,
        db: AsyncSession,
        record: ContextConfirmation,
        *,
        asset_role: str,
        refs: list[tuple[str, str]],
    ) -> None:
        """Replace one exact-ref role inside the caller's transaction."""
        await db.execute(
            delete(ContextConfirmationAssetRef).where(
                ContextConfirmationAssetRef.confirmation_id == record.id,
                ContextConfirmationAssetRef.novel_id == record.novel_id,
                ContextConfirmationAssetRef.asset_role == asset_role,
            )
        )
        for asset_type, asset_id in dict.fromkeys(refs):
            db.add(
                ContextConfirmationAssetRef(
                    confirmation_id=record.id,
                    novel_id=record.novel_id,
                    asset_role=asset_role,
                    asset_type=asset_type,
                    asset_id=asset_id,
                )
            )
        await db.flush()

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
        stmt = (
            select(ContextConfirmation)
            .join(
                ContextConfirmationAssetRef,
                and_(
                    ContextConfirmationAssetRef.confirmation_id == ContextConfirmation.id,
                    ContextConfirmationAssetRef.novel_id == ContextConfirmation.novel_id,
                ),
            )
            .where(
                ContextConfirmation.novel_id == novel_id,
                ContextConfirmationAssetRef.asset_type == asset_type,
                ContextConfirmationAssetRef.asset_id == str(asset_id),
            )
            .with_for_update(of=ContextConfirmation)
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        return list(result.unique().scalars().all())


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
        consumer_novel_id: uuid.UUID | None = None,
    ) -> ContextSnapshot:
        snapshot = ContextSnapshot(
            novel_id=novel_id,
            consumer_novel_id=consumer_novel_id,
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

    async def transition_terminal(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        terminal_status: str,
        result_refs: list[dict] | None = None,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> ContextSnapshot:
        """Close a running snapshot exactly once, scoped to its project.

        The guarded UPDATE is the terminal-state compare-and-set.  A repeated
        request for the winning terminal state is idempotent and returns the
        stored row without replacing its original terminal payload.  The
        opposite terminal state is rejected.
        """
        if terminal_status not in {"succeeded", "failed"}:
            raise ValueError("invalid context snapshot terminal status")
        values = {"status": terminal_status}
        if terminal_status == "succeeded":
            values.update(
                result_refs=result_refs or [],
                error_kind=None,
                error_message=None,
            )
        else:
            values.update(
                error_kind=error_kind,
                error_message=error_message,
            )
        transitioned = await db.execute(
            update(ContextSnapshot)
            .where(
                ContextSnapshot.novel_id == novel_id,
                ContextSnapshot.id == snapshot_id,
                ContextSnapshot.status == "running",
            )
            .values(**values)
            .returning(ContextSnapshot.id)
            .execution_options(synchronize_session=False)
        )
        won = transitioned.scalar_one_or_none() is not None
        result = await db.execute(
            select(ContextSnapshot)
            .where(
                ContextSnapshot.novel_id == novel_id,
                ContextSnapshot.id == snapshot_id,
            )
            .execution_options(populate_existing=True)
        )
        snapshot = result.scalar_one_or_none()
        if snapshot is None:
            raise ValueError("context_snapshot_id not found")
        if won:
            return snapshot
        if snapshot.status == terminal_status:
            same_payload = (
                (snapshot.result_refs or []) == (result_refs or [])
                if terminal_status == "succeeded"
                else snapshot.error_kind == error_kind
                and snapshot.error_message == error_message
            )
            if same_payload:
                return snapshot
            raise ValueError(
                "context snapshot terminal payload conflicts with the stored result"
            )
        raise ValueError(
            "context snapshot already finalized as "
            f"{snapshot.status}; cannot finalize as {terminal_status}"
        )

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

    async def aggregate_for_novel(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        content_mode: str,
        since: datetime,
    ) -> dict:
        conditions = (
            ContextRetrievalTrace.novel_id == novel_id,
            ContextRetrievalTrace.content_mode == content_mode,
            ContextRetrievalTrace.created_at >= since,
        )
        totals_stmt = select(
            func.count(ContextRetrievalTrace.id).label("query_count"),
            func.coalesce(
                func.sum(case((ContextRetrievalTrace.degraded.is_(True), 1), else_=0)),
                0,
            ).label("degraded_count"),
            func.coalesce(
                func.sum(case((ContextRetrievalTrace.hydrated_count == 0, 1), else_=0)),
                0,
            ).label("empty_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (ContextRetrievalTrace.hydrated_count == 0)
                            & or_(
                                ContextRetrievalTrace.safe_empty_reason.is_(None),
                                ContextRetrievalTrace.safe_empty_reason == "",
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("unclassified_empty_count"),
        ).where(*conditions)
        totals = (await db.execute(totals_stmt)).one()

        reasons_stmt = (
            select(
                ContextRetrievalTrace.safe_empty_reason,
                func.count(ContextRetrievalTrace.id),
            )
            .where(
                *conditions,
                ContextRetrievalTrace.safe_empty_reason.is_not(None),
                ContextRetrievalTrace.safe_empty_reason != "",
            )
            .group_by(ContextRetrievalTrace.safe_empty_reason)
        )
        reason_rows = (await db.execute(reasons_stmt)).all()

        bind = db.get_bind()
        dialect_name = bind.dialect.name if bind is not None else ""
        if dialect_name == "postgresql":
            drop_counts_json = cast(ContextRetrievalTrace.drop_counts, JSONB)
            safe_drop_counts = case(
                (func.jsonb_typeof(drop_counts_json) == "object", drop_counts_json),
                else_=cast(literal("{}"), JSONB),
            )
            entries = func.jsonb_each(safe_drop_counts).table_valued("key", "value")
            entry_json = cast(entries.c.value, JSONB)
            entry_text = cast(entry_json, String)
            valid_numeric = and_(
                func.jsonb_typeof(entry_json) == "number",
                entry_text.op("~")(r"^[0-9]{1,18}$"),
            )
            numeric_value = cast(entry_text, BigInteger)
        else:
            safe_drop_counts = case(
                (
                    func.json_type(ContextRetrievalTrace.drop_counts) == "object",
                    ContextRetrievalTrace.drop_counts,
                ),
                else_=literal("{}"),
            )
            entries = func.json_each(safe_drop_counts).table_valued(
                "key", "value", "type"
            )
            numeric_value = cast(entries.c.value, BigInteger)
            valid_numeric = and_(
                entries.c.type == "integer",
                numeric_value >= 0,
                numeric_value <= 999_999_999_999_999_999,
            )
        drops_stmt = (
            select(
                entries.c.key,
                func.sum(numeric_value),
            )
            .select_from(ContextRetrievalTrace)
            .join(entries, true())
            .where(*conditions, valid_numeric)
            .group_by(entries.c.key)
        )
        drop_rows = (await db.execute(drops_stmt)).all()

        return {
            "query_count": int(totals.query_count or 0),
            "degraded_count": int(totals.degraded_count or 0),
            "empty_count": int(totals.empty_count or 0),
            "unclassified_empty_count": int(totals.unclassified_empty_count or 0),
            "drop_counts": {str(key): int(value or 0) for key, value in drop_rows},
            "safe_empty_reasons": {
                str(reason): int(count or 0) for reason, count in reason_rows
            },
        }

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
        beyond_retention_cap = (
            select(ContextRetrievalTrace.id)
            .where(ContextRetrievalTrace.novel_id == novel_id)
            .order_by(
                ContextRetrievalTrace.created_at.desc(),
                ContextRetrievalTrace.id.desc(),
            )
            .offset(retain_latest)
        )
        stale_condition = or_(
            ContextRetrievalTrace.created_at < cutoff,
            ContextRetrievalTrace.id.in_(beyond_retention_cap),
        )
        count_stmt = select(func.count(ContextRetrievalTrace.id)).where(
            ContextRetrievalTrace.novel_id == novel_id,
            stale_condition,
        )
        stale_count = int((await db.execute(count_stmt)).scalar_one() or 0)
        if stale_count and not dry_run:
            await db.execute(
                delete(ContextRetrievalTrace).where(
                    ContextRetrievalTrace.novel_id == novel_id,
                    stale_condition,
                )
            )
            await db.flush()
        return stale_count
