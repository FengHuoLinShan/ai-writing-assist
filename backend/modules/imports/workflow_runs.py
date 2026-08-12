"""Imports-owned workflow run lifecycle and owner fencing."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.models import ImportWorkflowRun

ACTIVE_RUN_STATUSES = {"pending", "running"}
IMPORT_WORKFLOW_TYPES = {
    "deep_import",
    "scene_auto_extraction",
    "world_object_auto_extraction",
    "plot_structure_auto_extraction",
}
MANUAL_RECOVERY_WORKFLOW_TYPES = IMPORT_WORKFLOW_TYPES


def _parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("workflow identifier must be a UUID") from exc


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return deepcopy(value)


@dataclass(frozen=True)
class ImportWorkflowOwnerToken:
    """Complete CAS identity for one write-capable workflow attempt."""

    workflow_id: str
    task_id: str
    generation: int
    attempt: int
    lease_id: str


@dataclass(frozen=True)
class ImportWorkflowAttempt:
    """Immutable input handed from a task handler to an imports orchestrator."""

    owner: ImportWorkflowOwnerToken
    workflow_type: str
    stage: str | None
    novel_id: str
    start_chapter: int
    end_chapter: int
    context_mode: str
    include_pending_objects: bool
    high_quality: bool
    replace_existing: bool
    authorization_snapshot: Mapping[str, Any]
    llm_execution_snapshot: Mapping[str, Any]
    prepare_checkpoint: Mapping[str, Any]
    checkpoints: Mapping[str, Any]
    progress: Mapping[str, Any]

    @property
    def workflow_id(self) -> str:
        return self.owner.workflow_id

    @property
    def task_id(self) -> str:
        return self.owner.task_id

    def meta_projection(self) -> dict[str, Any]:
        # Once a workflow checkpoints, prepare_checkpoint contains the complete
        # frozen task meta (including Scene v2 source/context fingerprints).
        # Rehydrate it first, then overwrite identity/snapshots from the run's
        # dedicated authoritative columns.
        projection = _thaw_json(self.prepare_checkpoint)
        projection.update(
            {
                "novel_id": self.novel_id,
                "start_chapter": self.start_chapter,
                "end_chapter": self.end_chapter,
                "stage": self.stage,
                "context_mode": self.context_mode,
                "include_pending_objects": self.include_pending_objects,
                "high_quality": self.high_quality,
                "replace_existing": self.replace_existing,
                "adoption_policy": self.authorization_snapshot.get(
                    "adoption_policy"
                ),
                "authorization_confirmed": self.authorization_snapshot.get(
                    "authorization_confirmed"
                ),
                "authorization_snapshot": _thaw_json(
                    self.authorization_snapshot
                ),
                "llm_execution_snapshot": _thaw_json(
                    self.llm_execution_snapshot
                ),
            }
        )
        return projection

    def progress_projection(self) -> dict[str, Any]:
        return _thaw_json(self.progress)


class ImportWorkflowOwnershipLost(asyncio.CancelledError):
    """Raised to roll back a transaction after the run owner changed."""


class ImportWorkflowRunService:
    """Transactional lifecycle for imports-owned workflow state."""

    async def get_active_for_novel(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        for_update: bool = False,
    ) -> ImportWorkflowRun | None:
        stmt = (
            select(ImportWorkflowRun)
            .where(
                ImportWorkflowRun.novel_id == _parse_uuid(novel_id),
                (
                    ImportWorkflowRun.status.in_(sorted(ACTIVE_RUN_STATUSES))
                    | ImportWorkflowRun.recovery_required.is_(True)
                ),
            )
            .order_by(
                ImportWorkflowRun.created_at.desc(),
                ImportWorkflowRun.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def reconcile_task_owners(self, db: AsyncSession) -> int:
        """Converge active/recovery runs from the queue's stable lifecycle view."""
        return await self.reconcile_scoped_task_owners(
            db,
            include_restartable_history=True,
        )

    async def reconcile_scoped_task_owners(
        self,
        db: AsyncSession,
        *,
        novel_id: str | None = None,
        task_id: str | None = None,
        include_restartable_history: bool = False,
    ) -> int:
        """Lock and converge only the requested owner scope when provided."""
        from infrastructure.tasks.facade import list_task_lifecycle_contracts

        active_predicate = (
            ImportWorkflowRun.status.in_(sorted(ACTIVE_RUN_STATUSES))
            | ImportWorkflowRun.recovery_required.is_(True)
        )
        if task_id is not None:
            selection_predicate = ImportWorkflowRun.task_id == _parse_uuid(task_id)
        elif include_restartable_history or novel_id is not None:
            selection_predicate = active_predicate
        else:
            selection_predicate = active_predicate
        stmt = select(ImportWorkflowRun).where(selection_predicate)
        if novel_id is not None:
            stmt = stmt.where(
                ImportWorkflowRun.novel_id == _parse_uuid(novel_id),
            )
        runs = list(
            (
                await db.execute(
                    stmt.order_by(
                        ImportWorkflowRun.created_at.desc(),
                        ImportWorkflowRun.id.desc(),
                    ).with_for_update()
                )
            ).scalars()
        )
        owned_novels = {
            str(run.novel_id)
            for run in runs
            if run.status in ACTIVE_RUN_STATUSES or run.recovery_required
        }
        if task_id is not None:
            for run in runs:
                active = await self.get_active_for_novel(
                    db,
                    novel_id=str(run.novel_id),
                    # The exact run is already locked. A second run lock here
                    # would invert the all-runs reconciliation order and can
                    # deadlock concurrent workers. A stale positive is safe:
                    # it only defers this retry until the next reconciliation.
                    for_update=False,
                )
                if active is not None and active.task_id != run.task_id:
                    owned_novels.add(str(run.novel_id))
        runs_by_novel: dict[str, list[ImportWorkflowRun]] = {}
        for run in runs:
            runs_by_novel.setdefault(str(run.novel_id), []).append(run)
        contracts_by_task = {}
        for run_novel_id, novel_runs in runs_by_novel.items():
            contracts_by_task.update(
                await list_task_lifecycle_contracts(
                    db,
                    task_ids=[str(run.task_id) for run in novel_runs],
                    novel_id=run_novel_id,
                    max_heartbeat_gap=0.0,
                )
            )
        changed = 0
        for run in runs:
            task = contracts_by_task.get(str(run.task_id))
            before = (
                run.status,
                run.recovery_required,
                run.owner_task_id,
                run.owner_attempt,
                run.owner_lease_id,
            )
            if task is None or task.status == "cancelled":
                run.status = "cancelled"
                run.recovery_required = False
                self._clear_owner(run)
            elif task.status == "done":
                run.status = "done"
                run.recovery_required = False
                self._clear_owner(run)
            elif task.status == "failed":
                run.status = "failed"
                run.recovery_required = bool(
                    run.workflow_type in MANUAL_RECOVERY_WORKFLOW_TYPES
                    and task.recovery_policy == "manual_resume"
                    and task.recovery_required
                )
                self._clear_owner(run)
            elif task.status == "pending":
                if (
                    run.status not in ACTIVE_RUN_STATUSES
                    and str(run.novel_id) in owned_novels
                ):
                    continue
                run.status = "pending"
                run.recovery_required = False
                self._clear_owner(run)
                owned_novels.add(str(run.novel_id))
            elif task.status == "running":
                if not task.lease_id or int(task.attempt or 0) < 1:
                    run.status = "cancelled"
                    run.recovery_required = False
                    self._clear_owner(run)
                else:
                    if (
                        run.status not in ACTIVE_RUN_STATUSES
                        and str(run.novel_id) in owned_novels
                    ):
                        continue
                    run.status = "running"
                    run.recovery_required = False
                    run.owner_task_id = run.task_id
                    run.owner_attempt = int(task.attempt)
                    run.owner_lease_id = str(task.lease_id)
                    owned_novels.add(str(run.novel_id))
            after = (
                run.status,
                run.recovery_required,
                run.owner_task_id,
                run.owner_attempt,
                run.owner_lease_id,
            )
            if before != after:
                changed += 1
        await db.flush()
        return changed

    async def get_by_task(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        for_update: bool = False,
    ) -> ImportWorkflowRun | None:
        stmt = select(ImportWorkflowRun).where(
            ImportWorkflowRun.task_id == _parse_uuid(task_id)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def create_pending(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        novel_id: str,
        workflow_type: str,
        stage: str | None,
        start_chapter: int,
        end_chapter: int,
        authorization_snapshot: dict[str, Any],
        llm_execution_snapshot: dict[str, Any],
        context_mode: str = "working",
        include_pending_objects: bool = True,
        high_quality: bool = False,
        replace_existing: bool = False,
        initial_progress: dict[str, Any] | None = None,
    ) -> ImportWorkflowRun:
        if workflow_type not in IMPORT_WORKFLOW_TYPES:
            raise ValueError(f"unsupported imports workflow type: {workflow_type}")
        if start_chapter < 1 or end_chapter < start_chapter:
            raise ValueError("invalid imports workflow chapter range")
        parsed_task_id = _parse_uuid(task_id)
        run = ImportWorkflowRun(
            # First-version API compatibility: workflow_id == task_id.
            id=parsed_task_id,
            task_id=parsed_task_id,
            novel_id=_parse_uuid(novel_id),
            workflow_type=workflow_type,
            stage=stage,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            status="pending",
            generation=1,
            owner_task_id=None,
            owner_attempt=None,
            owner_lease_id=None,
            recovery_required=False,
            authorization_snapshot=deepcopy(authorization_snapshot),
            llm_execution_snapshot=deepcopy(llm_execution_snapshot),
            prepare_checkpoint={
                "context_mode": context_mode,
                "include_pending_objects": bool(include_pending_objects),
                "high_quality": bool(high_quality),
                "replace_existing": bool(replace_existing),
            },
            checkpoints={},
            progress=deepcopy(initial_progress or {}),
        )
        db.add(run)
        await db.flush()
        return run

    async def claim_attempt(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        workflow_type: str,
        attempt: int,
        lease_id: str,
    ) -> ImportWorkflowAttempt:
        """Claim the domain run for the exact queue attempt."""
        if attempt < 1 or not lease_id:
            raise ImportWorkflowOwnershipLost
        run = await self.get_by_task(db, task_id=task_id, for_update=True)
        if (
            run is None
            or run.workflow_type != workflow_type
            or run.status not in ACTIVE_RUN_STATUSES
            or (
                run.status == "running"
                and (
                    run.owner_attempt != attempt
                    or str(run.owner_lease_id or "") != str(lease_id)
                )
            )
        ):
            raise ImportWorkflowOwnershipLost
        run.status = "running"
        run.owner_task_id = _parse_uuid(task_id)
        run.owner_attempt = int(attempt)
        run.owner_lease_id = str(lease_id)
        await db.flush()
        return self._attempt_from_run(run)

    async def require_owner(
        self,
        db: AsyncSession,
        owner: ImportWorkflowOwnerToken,
    ) -> ImportWorkflowRun:
        """Lock and return the run only if the complete owner token still wins."""
        run = await self.get_by_task(db, task_id=owner.task_id, for_update=True)
        if (
            run is None
            or str(run.id) != owner.workflow_id
            or int(run.generation) != int(owner.generation)
            or str(run.owner_task_id or "") != owner.task_id
            or int(run.owner_attempt or 0) != int(owner.attempt)
            or str(run.owner_lease_id or "") != str(owner.lease_id)
            or run.status != "running"
        ):
            raise ImportWorkflowOwnershipLost
        return run

    async def checkpoint(
        self,
        db: AsyncSession,
        *,
        owner: ImportWorkflowOwnerToken,
        progress: dict[str, Any],
        prepare_checkpoint: dict[str, Any] | None = None,
        checkpoints: dict[str, Any] | None = None,
    ) -> None:
        run = await self.require_owner(db, owner)
        run.progress = deepcopy(progress)
        if prepare_checkpoint is not None:
            run.prepare_checkpoint = deepcopy(prepare_checkpoint)
        if checkpoints is not None:
            run.checkpoints = deepcopy(checkpoints)
        await db.flush()

    async def complete(
        self,
        db: AsyncSession,
        *,
        owner: ImportWorkflowOwnerToken,
        progress: dict[str, Any],
    ) -> None:
        run = await self.require_owner(db, owner)
        run.progress = deepcopy(progress)
        run.status = "done"
        run.recovery_required = False
        self._clear_owner(run)
        await db.flush()

    async def fail(
        self,
        db: AsyncSession,
        *,
        owner: ImportWorkflowOwnerToken,
        progress: dict[str, Any],
        recovery_required: bool,
    ) -> None:
        run = await self.require_owner(db, owner)
        run.progress = deepcopy(progress)
        run.status = "failed"
        run.recovery_required = bool(recovery_required)
        self._clear_owner(run)
        await db.flush()

    async def resume(
        self,
        db: AsyncSession,
        *,
        task_id: str,
    ) -> ImportWorkflowRun:
        run = await self.get_by_task(db, task_id=task_id, for_update=True)
        if run is None:
            raise LookupError(task_id)
        if run.status != "failed" or not run.recovery_required:
            raise ValueError("only recovery-required imports workflows can resume")
        run.generation = int(run.generation) + 1
        run.status = "pending"
        run.recovery_required = False
        self._clear_owner(run)
        await db.flush()
        return run

    async def abandon(
        self,
        db: AsyncSession,
        *,
        task_id: str,
    ) -> ImportWorkflowRun:
        run = await self.get_by_task(db, task_id=task_id, for_update=True)
        if run is None:
            raise LookupError(task_id)
        if run.status != "failed" or not run.recovery_required:
            raise ValueError("only recovery-required imports workflows can abandon")
        run.status = "cancelled"
        run.recovery_required = False
        self._clear_owner(run)
        await db.flush()
        return run

    @staticmethod
    def _attempt_from_run(run: ImportWorkflowRun) -> ImportWorkflowAttempt:
        prepare = dict(run.prepare_checkpoint or {})
        return ImportWorkflowAttempt(
            owner=ImportWorkflowOwnerToken(
                workflow_id=str(run.id),
                task_id=str(run.task_id),
                generation=int(run.generation),
                attempt=int(run.owner_attempt or 0),
                lease_id=str(run.owner_lease_id or ""),
            ),
            workflow_type=str(run.workflow_type),
            stage=run.stage,
            novel_id=str(run.novel_id),
            start_chapter=int(run.start_chapter),
            end_chapter=int(run.end_chapter),
            context_mode=str(prepare.get("context_mode") or "working"),
            include_pending_objects=bool(prepare.get("include_pending_objects", True)),
            high_quality=bool(prepare.get("high_quality", False)),
            replace_existing=bool(prepare.get("replace_existing", False)),
            authorization_snapshot=_freeze_json(
                deepcopy(run.authorization_snapshot or {})
            ),
            llm_execution_snapshot=_freeze_json(
                deepcopy(run.llm_execution_snapshot or {})
            ),
            prepare_checkpoint=_freeze_json(deepcopy(run.prepare_checkpoint or {})),
            checkpoints=_freeze_json(deepcopy(run.checkpoints or {})),
            progress=_freeze_json(deepcopy(run.progress or {})),
        )

    @staticmethod
    def _clear_owner(run: ImportWorkflowRun) -> None:
        run.owner_task_id = None
        run.owner_attempt = None
        run.owner_lease_id = None
