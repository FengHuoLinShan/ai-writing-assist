"""Context snapshot service."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import ContextSnapshotContract
from modules.context.repositories import ContextSnapshotRepository
from shared.utils import parse_uuid


class ContextSnapshotService:
    """Owns automated AI-call context snapshot semantics."""

    def __init__(self, repository: ContextSnapshotRepository | None = None) -> None:
        self._repo = repository or ContextSnapshotRepository()

    async def create_context_snapshot(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task_id: str | None = None,
        workflow_id: str | None = None,
        phase: str,
        operation: str,
        scene_id: str | None = None,
        scene_index: int | None = None,
        chapter_index: int | None = None,
        context_mode: str = "working",
        include_pending_objects: bool = True,
        attempt: int = 1,
        prompt_name: str,
        model: str,
        compile_options: dict,
        included_asset_ids: dict,
        excluded_asset_ids: dict | None = None,
        context_summary: dict,
        section_metadata: dict,
        token_metadata: dict,
        rendered_context: str | None = None,
        retain_rendered_context: bool = False,
    ) -> ContextSnapshotContract:
        stored_rendered = rendered_context if retain_rendered_context else None
        expires_at = (
            datetime.now(UTC) + timedelta(days=30) if retain_rendered_context else None
        )
        snapshot = await self._repo.create(
            db,
            novel_id=parse_uuid(novel_id, "novel_id"),
            task_id=task_id,
            workflow_id=workflow_id,
            phase=phase,
            operation=operation,
            scene_id=scene_id,
            scene_index=scene_index,
            chapter_index=chapter_index,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            attempt=attempt,
            prompt_hash=self._prompt_hash(
                prompt_name=prompt_name,
                rendered_context=rendered_context,
                context_summary=context_summary,
                section_metadata=section_metadata,
            ),
            prompt_name=prompt_name,
            model=model,
            compile_options=compile_options,
            included_asset_ids=included_asset_ids,
            excluded_asset_ids=excluded_asset_ids or {},
            context_summary=context_summary,
            section_metadata=section_metadata,
            token_metadata=token_metadata,
            rendered_context=stored_rendered,
            rendered_context_expires_at=expires_at,
        )
        return self._to_contract(snapshot)

    async def mark_context_snapshot_succeeded(
        self,
        db: AsyncSession,
        *,
        snapshot_id: str | uuid.UUID,
        result_refs: list[dict],
    ) -> ContextSnapshotContract:
        snapshot = await self._require_snapshot(db, snapshot_id)
        updated = await self._repo.mark_succeeded(
            db,
            snapshot,
            result_refs=result_refs,
        )
        return self._to_contract(updated)

    async def mark_context_snapshot_failed(
        self,
        db: AsyncSession,
        *,
        snapshot_id: str | uuid.UUID,
        error_kind: str,
        error_message: str,
    ) -> ContextSnapshotContract:
        snapshot = await self._require_snapshot(db, snapshot_id)
        updated = await self._repo.mark_failed(
            db,
            snapshot,
            error_kind=error_kind,
            error_message=error_message[:500],
        )
        return self._to_contract(updated)

    async def get_context_snapshot(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        snapshot_id: str | uuid.UUID,
    ) -> ContextSnapshotContract:
        snapshot = await self._require_snapshot(db, snapshot_id)
        nid = parse_uuid(novel_id, "novel_id")
        if str(snapshot.novel_id) != str(nid):
            raise ValueError("context_snapshot_id not found")
        return self._to_contract(snapshot)

    async def list_context_snapshots(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        workflow_id: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ContextSnapshotContract]:
        records = await self._repo.list_for_novel(
            db,
            novel_id=parse_uuid(novel_id, "novel_id"),
            workflow_id=workflow_id,
            task_id=task_id,
            limit=limit,
            offset=offset,
        )
        return [self._to_contract(record) for record in records]

    async def build_snapshot_health_summary(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        workflow_id: str | None = None,
        running_timeout_minutes: int = 120,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        records = await self._repo.list_for_maintenance(
            db,
            novel_id=nid,
            workflow_id=workflow_id,
        )
        cutoff = datetime.now(UTC) - timedelta(minutes=running_timeout_minutes)
        by_status = {"running": 0, "succeeded": 0, "failed": 0}
        by_phase: dict[str, dict[str, int]] = {}
        stale_running_count = 0
        retained_rendered_context_count = 0
        latest_failure = None

        for record in records:
            status = record.status or "unknown"
            by_status[status] = by_status.get(status, 0) + 1
            phase_counts = by_phase.setdefault(
                record.phase,
                {"running": 0, "succeeded": 0, "failed": 0},
            )
            phase_counts[status] = phase_counts.get(status, 0) + 1

            if record.status == "running" and self._is_before(record.created_at, cutoff):
                stale_running_count += 1
            if record.rendered_context is not None:
                retained_rendered_context_count += 1
            if record.status == "failed" and self._is_newer_failure(
                record,
                latest_failure,
            ):
                latest_failure = {
                    "snapshot_id": str(record.id),
                    "phase": record.phase,
                    "scene_id": record.scene_id,
                    "scene_index": record.scene_index,
                    "chapter_index": record.chapter_index,
                    "error_kind": record.error_kind,
                    "error_message": record.error_message,
                    "created_at": record.created_at.isoformat(),
                }

        return {
            "novel_id": str(nid),
            "workflow_id": workflow_id,
            "total_snapshots": len(records),
            "by_status": by_status,
            "by_phase": by_phase,
            "stale_running_count": stale_running_count,
            "retained_rendered_context_count": retained_rendered_context_count,
            "latest_failure": latest_failure,
        }

    async def mark_stale_running_snapshots(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        workflow_id: str | None = None,
        running_timeout_minutes: int = 120,
        dry_run: bool = True,
    ) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        records = await self._repo.list_for_maintenance(
            db,
            novel_id=nid,
            workflow_id=workflow_id,
        )
        cutoff = datetime.now(UTC) - timedelta(minutes=running_timeout_minutes)
        stale_records = [
            record
            for record in records
            if record.status == "running" and self._is_before(record.created_at, cutoff)
        ]
        if dry_run:
            return len(stale_records)

        for record in stale_records:
            record.status = "failed"
            record.error_kind = "stale_running"
            record.error_message = "Snapshot remained running past lifecycle timeout"
        if stale_records:
            await db.flush()
        return len(stale_records)

    async def prune_rendered_context(
        self,
        db: AsyncSession,
        *,
        novel_id: str | None = None,
        workflow_id: str | None = None,
        retain_latest_full_context_per_project: int | None = None,
        dry_run: bool = False,
        older_than_days: int | None = None,
        keep_latest_per_project: int | None = None,
    ) -> int:
        retain_latest = (
            retain_latest_full_context_per_project
            if retain_latest_full_context_per_project is not None
            else (keep_latest_per_project if keep_latest_per_project is not None else 200)
        )
        return await self._repo.prune_rendered_context(
            db,
            novel_id=parse_uuid(novel_id, "novel_id") if novel_id else None,
            workflow_id=workflow_id,
            retain_latest_full_context_per_project=retain_latest,
            dry_run=dry_run,
        )

    async def run_snapshot_maintenance(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        workflow_id: str | None = None,
        running_timeout_minutes: int = 120,
        prune_rendered_context: bool = True,
        retain_latest_full_context_per_project: int = 200,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        stale_count = await self.mark_stale_running_snapshots(
            db,
            novel_id=novel_id,
            workflow_id=workflow_id,
            running_timeout_minutes=running_timeout_minutes,
            dry_run=dry_run,
        )
        pruned_count = 0
        if prune_rendered_context:
            pruned_count = await self.prune_rendered_context(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
                retain_latest_full_context_per_project=(
                    retain_latest_full_context_per_project
                ),
                dry_run=dry_run,
            )
        summary = await self.build_snapshot_health_summary(
            db,
            novel_id=novel_id,
            workflow_id=workflow_id,
            running_timeout_minutes=running_timeout_minutes,
        )
        return {
            "snapshot_health_summary": summary,
            "stale_running_count": stale_count,
            "pruned_rendered_context_count": pruned_count,
            "would_change_count": stale_count + pruned_count if dry_run else 0,
            "dry_run": dry_run,
        }

    async def _require_snapshot(
        self,
        db: AsyncSession,
        snapshot_id: str | uuid.UUID,
    ):
        sid = snapshot_id if isinstance(snapshot_id, uuid.UUID) else parse_uuid(
            str(snapshot_id),
            "context_snapshot_id",
        )
        snapshot = await self._repo.get(db, sid)
        if snapshot is None:
            raise ValueError("context_snapshot_id not found")
        return snapshot

    @staticmethod
    def _prompt_hash(
        *,
        prompt_name: str,
        rendered_context: str | None,
        context_summary: dict,
        section_metadata: dict,
    ) -> str:
        payload = {
            "prompt_name": prompt_name,
            "rendered_context": rendered_context or "",
            "context_summary": context_summary,
            "section_metadata": section_metadata,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_before(value: datetime | None, cutoff: datetime) -> bool:
        if value is None:
            return True
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value < cutoff

    @staticmethod
    def _is_newer_failure(record, latest_failure: dict[str, Any] | None) -> bool:
        if latest_failure is None:
            return True
        current = record.created_at
        if current is not None and current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        previous_raw = latest_failure.get("created_at")
        if previous_raw is None:
            return True
        previous = datetime.fromisoformat(previous_raw)
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
        return current is not None and current > previous

    @staticmethod
    def _to_contract(record) -> ContextSnapshotContract:
        return ContextSnapshotContract(
            id=str(record.id),
            novel_id=str(record.novel_id),
            task_id=record.task_id,
            workflow_id=record.workflow_id,
            phase=record.phase,
            operation=record.operation,
            scene_id=record.scene_id,
            scene_index=record.scene_index,
            chapter_index=record.chapter_index,
            context_mode=record.context_mode,
            include_pending_objects=record.include_pending_objects,
            status=record.status,
            attempt=record.attempt,
            prompt_hash=record.prompt_hash,
            prompt_name=record.prompt_name,
            model=record.model,
            compile_options=record.compile_options or {},
            included_asset_ids=record.included_asset_ids or {},
            excluded_asset_ids=record.excluded_asset_ids or {},
            context_summary=record.context_summary or {},
            section_metadata=record.section_metadata or {},
            token_metadata=record.token_metadata or {},
            rendered_context=record.rendered_context,
            result_refs=record.result_refs or [],
            error_kind=record.error_kind,
            error_message=record.error_message,
            rendered_context_expires_at=(
                record.rendered_context_expires_at.isoformat()
                if record.rendered_context_expires_at
                else None
            ),
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
