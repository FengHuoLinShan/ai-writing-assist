"""Owner/generation regression tests for imports-owned workflow runs."""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from infrastructure.tasks.models import AsyncTask
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.workflow_runs import (
    ImportWorkflowOwnershipLost,
    ImportWorkflowRunService,
)

IMPORTS_ROOT = Path(__file__).resolve().parents[1]


async def _create_pending_run(db_session, novel_id: str, *, task_type="deep_import"):
    task_id = uuid.uuid4()
    task = AsyncTask(
        id=task_id,
        task_type=task_type,
        status="pending",
        attempt=0,
        recovery_policy="manual_resume",
        meta={"novel_id": novel_id},
        result={},
    )
    db_session.add(task)
    await db_session.flush()
    run = await ImportWorkflowRunService().create_pending(
        db_session,
        task_id=str(task_id),
        novel_id=novel_id,
        workflow_type=task_type,
        stage=None,
        start_chapter=1,
        end_chapter=3,
        authorization_snapshot={
            "authorization_confirmed": True,
            "adoption_policy": "user_authorized_pipeline",
        },
        llm_execution_snapshot={"provider": "test", "model": "frozen"},
        initial_progress={"phase": "pending"},
    )
    return task, run


async def test_create_pending_run_preserves_public_workflow_task_identity(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(db_session, test_project_id)

    assert run.id == task.id
    assert run.task_id == task.id
    assert run.generation == 1
    assert run.status == "pending"
    assert run.progress == {"phase": "pending"}


async def test_claim_attempt_returns_immutable_owner_and_snapshots(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(db_session, test_project_id)
    lease_id = str(uuid.uuid4())

    attempt = await ImportWorkflowRunService().claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="deep_import",
        attempt=1,
        lease_id=lease_id,
    )

    assert attempt.owner.workflow_id == str(run.id)
    assert attempt.owner.task_id == str(task.id)
    assert attempt.owner.generation == 1
    assert attempt.owner.attempt == 1
    assert attempt.owner.lease_id == lease_id
    with pytest.raises(TypeError):
        attempt.authorization_snapshot["authorization_confirmed"] = False


async def test_resumed_attempt_rehydrates_authoritative_prepare_checkpoint(
    db_session,
    test_project_id: str,
) -> None:
    task, _run = await _create_pending_run(
        db_session,
        test_project_id,
        task_type="scene_auto_extraction",
    )
    service = ImportWorkflowRunService()
    first = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="scene_auto_extraction",
        attempt=1,
        lease_id=str(uuid.uuid4()),
    )
    await service.checkpoint(
        db_session,
        owner=first.owner,
        progress={"phase": "running"},
        prepare_checkpoint={
            "context_mode": "working",
            "include_pending_objects": True,
            "scene_stage_prepare": {
                "version": "scene-stage-prepare-v2",
                "input_fingerprint": "frozen-input",
            },
            # Dedicated columns must remain authoritative on rehydration.
            "novel_id": str(uuid.uuid4()),
            "authorization_snapshot": {"authorization_confirmed": False},
        },
    )
    await service.fail(
        db_session,
        owner=first.owner,
        progress={"phase": "failed"},
        recovery_required=True,
    )
    await service.resume(db_session, task_id=str(task.id))
    second = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="scene_auto_extraction",
        attempt=2,
        lease_id=str(uuid.uuid4()),
    )

    meta = second.meta_projection()
    assert meta["scene_stage_prepare"] == {
        "version": "scene-stage-prepare-v2",
        "input_fingerprint": "frozen-input",
    }
    assert meta["novel_id"] == test_project_id
    assert meta["authorization_snapshot"]["authorization_confirmed"] is True


async def test_stale_attempt_cannot_checkpoint_after_resume_generation(
    db_session,
    test_project_id: str,
) -> None:
    task, _run = await _create_pending_run(db_session, test_project_id)
    service = ImportWorkflowRunService()
    first = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="deep_import",
        attempt=1,
        lease_id=str(uuid.uuid4()),
    )
    await service.fail(
        db_session,
        owner=first.owner,
        progress={"phase": "failed", "recovery_required": True},
        recovery_required=True,
    )
    resumed = await service.resume(db_session, task_id=str(task.id))
    second = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="deep_import",
        attempt=2,
        lease_id=str(uuid.uuid4()),
    )

    assert resumed.generation == 2
    assert second.owner.generation == 2
    with pytest.raises(ImportWorkflowOwnershipLost):
        await service.checkpoint(
            db_session,
            owner=first.owner,
            progress={"phase": "done", "stale": True},
        )
    current = await service.get_by_task(db_session, task_id=str(task.id))
    assert current is not None
    assert current.progress == {"phase": "failed", "recovery_required": True}
    assert current.owner_attempt == 2


async def test_stale_failure_cannot_replace_completed_new_attempt(
    db_session,
    test_project_id: str,
) -> None:
    task, _run = await _create_pending_run(db_session, test_project_id)
    service = ImportWorkflowRunService()
    first = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="deep_import",
        attempt=1,
        lease_id=str(uuid.uuid4()),
    )
    await service.fail(
        db_session,
        owner=first.owner,
        progress={"phase": "failed"},
        recovery_required=True,
    )
    await service.resume(db_session, task_id=str(task.id))
    second = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="deep_import",
        attempt=2,
        lease_id=str(uuid.uuid4()),
    )
    await service.complete(
        db_session,
        owner=second.owner,
        progress={"phase": "done", "winner": 2},
    )

    with pytest.raises(ImportWorkflowOwnershipLost):
        await service.fail(
            db_session,
            owner=first.owner,
            progress={"phase": "failed", "winner": 1},
            recovery_required=True,
        )
    current = await service.get_by_task(db_session, task_id=str(task.id))
    assert current is not None
    assert current.status == "done"
    assert current.progress == {"phase": "done", "winner": 2}


async def test_reconcile_manual_failed_task_preserves_recovery_owner(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(db_session, test_project_id)
    task.status = "failed"
    task.recovery_policy = "manual_resume"
    task.result = {"recovery_required": True}
    task.meta = {
        **dict(task.meta or {}),
        "recovery_required": True,
    }
    await db_session.flush()

    changed = await ImportWorkflowRunService().reconcile_task_owners(db_session)

    assert changed == 1
    assert run.status == "failed"
    assert run.recovery_required is True
    assert run.owner_task_id is None
    assert run.owner_attempt is None
    assert run.owner_lease_id is None


async def test_reconcile_ordinary_manual_policy_failure_is_not_recoverable(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(db_session, test_project_id)
    task.status = "failed"
    task.recovery_policy = "manual_resume"
    task.result = {}
    task.meta = {"novel_id": test_project_id}
    await db_session.flush()

    changed = await ImportWorkflowRunService().reconcile_task_owners(db_session)

    assert changed == 1
    assert run.status == "failed"
    assert run.recovery_required is False
    assert (
        await ImportWorkflowRunService().get_active_for_novel(
            db_session,
            novel_id=test_project_id,
        )
        is None
    )


async def test_reconcile_failed_restartable_map_task_never_blocks_manual_recovery(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(
        db_session,
        test_project_id,
        task_type="map_observation_enrichment",
    )
    task.status = "failed"
    task.recovery_policy = "auto_requeue"
    task.result = {"recovery_required": True}
    task.meta = {
        "novel_id": test_project_id,
        "recovery_required": True,
    }
    await db_session.flush()

    changed = await ImportWorkflowRunService().reconcile_task_owners(db_session)

    assert changed == 1
    assert run.status == "failed"
    assert run.recovery_required is False
    assert (
        await ImportWorkflowRunService().get_active_for_novel(
            db_session,
            novel_id=test_project_id,
        )
        is None
    )


async def test_reconcile_restores_terminal_map_run_after_generic_retry(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(
        db_session,
        test_project_id,
        task_type="map_observation_enrichment",
    )
    task.status = "pending"
    run.status = "failed"
    run.recovery_required = False
    await db_session.flush()

    changed = await ImportWorkflowRunService().reconcile_scoped_task_owners(
        db_session,
        novel_id=test_project_id,
    )

    assert changed == 1
    assert run.status == "pending"
    assert (
        await ImportWorkflowRunService().get_active_for_novel(
            db_session,
            novel_id=test_project_id,
        )
    ) is run


async def test_reconcile_does_not_steal_project_from_newer_active_workflow(
    db_session,
    test_project_id: str,
) -> None:
    retried_task, retried_run = await _create_pending_run(
        db_session,
        test_project_id,
        task_type="map_observation_enrichment",
    )
    retried_task.status = "failed"
    retried_run.status = "failed"
    await db_session.flush()
    _active_task, active_run = await _create_pending_run(
        db_session,
        test_project_id,
        task_type="deep_import",
    )
    retried_task.status = "pending"
    await db_session.flush()

    await ImportWorkflowRunService().reconcile_scoped_task_owners(
        db_session,
        task_id=str(retried_task.id),
    )

    assert retried_run.status == "failed"
    assert active_run.status == "pending"
    with pytest.raises(ImportWorkflowOwnershipLost):
        await ImportWorkflowRunService().claim_attempt(
            db_session,
            task_id=str(retried_task.id),
            workflow_type="map_observation_enrichment",
            attempt=2,
            lease_id=str(uuid.uuid4()),
        )


async def test_reconcile_running_auto_retry_replaces_stale_attempt_owner(
    db_session,
    test_project_id: str,
) -> None:
    task, _run = await _create_pending_run(
        db_session,
        test_project_id,
        task_type="map_observation_enrichment",
    )
    task.recovery_policy = "auto_requeue"
    task.status = "running"
    task.attempt = 1
    task.lease_id = str(uuid.uuid4())
    await db_session.flush()
    service = ImportWorkflowRunService()
    await service.reconcile_task_owners(db_session)
    first = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="map_observation_enrichment",
        attempt=1,
        lease_id=str(task.lease_id),
    )

    task.attempt = 2
    task.lease_id = str(uuid.uuid4())
    await db_session.flush()
    await service.reconcile_task_owners(db_session)
    second = await service.claim_attempt(
        db_session,
        task_id=str(task.id),
        workflow_type="map_observation_enrichment",
        attempt=2,
        lease_id=str(task.lease_id),
    )

    assert second.owner.attempt == 2
    with pytest.raises(ImportWorkflowOwnershipLost):
        await service.checkpoint(
            db_session,
            owner=first.owner,
            progress={"phase": "stale"},
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "orchestrator.py",
        "map_observation_enrichment_workflow.py",
    ],
)
def test_workflow_orchestrators_do_not_import_async_task_orm(
    relative_path: str,
) -> None:
    source_path = IMPORTS_ROOT / relative_path
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    forbidden = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "infrastructure.tasks.models"
        and any(alias.name == "AsyncTask" for alias in node.names)
    ]

    assert forbidden == []


async def test_active_run_unique_index_is_project_scoped(
    db_session,
    project_factory,
    test_project_id: str,
) -> None:
    await _create_pending_run(db_session, test_project_id)
    duplicate_task = AsyncTask(
        id=uuid.uuid4(),
        task_type="scene_auto_extraction",
        status="pending",
        meta={"novel_id": test_project_id},
        result={},
    )
    db_session.add(duplicate_task)
    await db_session.flush()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await ImportWorkflowRunService().create_pending(
                db_session,
                task_id=str(duplicate_task.id),
                novel_id=test_project_id,
                workflow_type="scene_auto_extraction",
                stage="scenes",
                start_chapter=1,
                end_chapter=1,
                authorization_snapshot={},
                llm_execution_snapshot={},
            )

    other_project_id = str(await project_factory.create_project("other"))
    _other_task, other_run = await _create_pending_run(
        db_session,
        other_project_id,
    )
    assert str(other_run.novel_id) == other_project_id


async def test_cross_task_type_enqueue_reuses_project_run_without_orphan_task(
    db_session,
    test_project_id: str,
) -> None:
    task, run = await _create_pending_run(db_session, test_project_id)
    orchestrator = DeepImportOrchestrator()

    queued = await orchestrator._enqueue_workflow(
        db_session,
        task_type="scene_auto_extraction",
        novel_id=test_project_id,
        start_chapter=1,
        end_chapter=3,
        stage="scenes",
        context_mode="working",
        include_pending_objects=True,
        high_quality=False,
        replace_existing=False,
        authorization_snapshot={
            "authorization_confirmed": True,
            "adoption_policy": "user_authorized_pipeline",
        },
        llm_execution_snapshot={},
    )

    assert queued.task_id == str(task.id)
    assert queued.reused is True
    tasks = list((await db_session.execute(select(AsyncTask))).scalars())
    assert [item.id for item in tasks] == [task.id]
    current = await ImportWorkflowRunService().get_by_task(
        db_session,
        task_id=str(task.id),
    )
    assert current is run
