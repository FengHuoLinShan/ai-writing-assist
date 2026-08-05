from __future__ import annotations

import ast
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.enqueuer import enqueue_coalesced_task, enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_ordinary_enqueue_requires_explicit_owner_choice() -> None:
    with pytest.raises(TypeError, match="novel_id"):
        enqueue_task(MagicMock(), "unknown-task")


def test_production_ordinary_enqueue_calls_pass_explicit_novel_id() -> None:
    missing: list[str] = []
    direct_construction: list[str] = []
    for source_path in BACKEND_ROOT.rglob("*.py"):
        if "tests" in source_path.parts or source_path.name.startswith("test_"):
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            is_enqueue_call = (
                isinstance(node.func, ast.Name) and node.func.id == "enqueue_task"
            ) or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "enqueue_task"
            )
            if is_enqueue_call and not any(
                keyword.arg == "novel_id" for keyword in node.keywords
            ):
                missing.append(f"{source_path.relative_to(BACKEND_ROOT)}:{node.lineno}")
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "AsyncTask"
                and source_path.relative_to(BACKEND_ROOT)
                != Path("infrastructure/tasks/enqueuer.py")
            ):
                direct_construction.append(
                    f"{source_path.relative_to(BACKEND_ROOT)}:{node.lineno}"
                )

    assert missing == []
    assert direct_construction == []


def test_ordinary_enqueue_rejects_metadata_only_or_mismatched_identity() -> None:
    db = MagicMock()
    project_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="explicit novel_id"):
        enqueue_task(
            db,
            "unknown-task",
            meta={"novel_id": project_id},
            novel_id=None,
        )
    with pytest.raises(ValueError, match="does not match"):
        enqueue_task(
            db,
            "unknown-task",
            meta={"novel_id": project_id},
            novel_id=str(uuid.uuid4()),
        )
    with pytest.raises(ValueError, match="UUID"):
        enqueue_task(db, "unknown-task", novel_id="not-a-uuid")


def test_ordinary_enqueue_canonicalizes_project_identity() -> None:
    db = MagicMock()
    project_id = uuid.uuid4()

    enqueue_task(
        db,
        "unknown-task",
        meta={"novel_id": str(project_id).upper()},
        novel_id=str(project_id),
    )

    task = db.add.call_args.args[0]
    assert task.novel_id == project_id
    assert task.meta == {"novel_id": str(project_id)}


def test_registered_owner_scope_is_enforced() -> None:
    registry = TaskRegistry()

    async def handler(db, task):
        return {}

    registry.register("test-global-task", handler, owner_scope="global")
    try:
        db = MagicMock()
        enqueue_task(db, "test-global-task", novel_id=None)
        with pytest.raises(ValueError, match="global tasks"):
            enqueue_task(db, "test-global-task", novel_id=str(uuid.uuid4()))
    finally:
        registry.unregister("test-global-task")


@pytest.mark.asyncio
async def test_coalesced_enqueue_populates_identity_projection(
    db_session: AsyncSession,
) -> None:
    project_id = str(uuid.uuid4())

    queued = await enqueue_coalesced_task(
        db_session,
        task_type="unknown-coalesced-task",
        novel_id=project_id,
        scope=("scope",),
    )
    task = await db_session.get(AsyncTask, uuid.UUID(queued.task_id))

    assert task is not None
    assert task.novel_id == uuid.UUID(project_id)
    assert task.meta == {"novel_id": project_id}


@pytest.mark.asyncio
async def test_orm_identity_is_synced_then_immutable(db_session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    task = AsyncTask(
        task_type="identity-test",
        meta={"novel_id": str(project_id).upper()},
    )
    db_session.add(task)
    await db_session.flush()

    assert task.novel_id == project_id
    assert task.meta == {"novel_id": str(project_id)}

    task.meta = {"novel_id": str(uuid.uuid4())}
    with pytest.raises(ValueError, match="cannot change"):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_orm_rejects_column_reassignment_but_allows_other_metadata(
    db_session: AsyncSession,
) -> None:
    task = AsyncTask(
        task_type="identity-test",
        novel_id=uuid.uuid4(),
        meta={},
    )
    db_session.add(task)
    await db_session.flush()

    task.meta = {**(task.meta or {}), "checkpoint": "updated"}
    await db_session.flush()

    task.novel_id = uuid.uuid4()
    with pytest.raises(ValueError, match="cannot change"):
        await db_session.flush()
    await db_session.rollback()
