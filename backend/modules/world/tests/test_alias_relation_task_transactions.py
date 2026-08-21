from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from unittest import mock

import pytest

from core.errors import NotFoundError
from infrastructure.tasks.models import AsyncTask
from modules.evidence.contracts import ContextConfirmationContract
from modules.world import tasks as world_tasks

pytestmark = pytest.mark.asyncio

NOVEL_ID = "11111111-1111-1111-1111-111111111111"
CONFIRMATION_ID = "22222222-2222-2222-2222-222222222222"
TASK_ID = "33333333-3333-3333-3333-333333333333"


class _CheckpointSession:
    task_checkpoint_enabled = True

    def __init__(self, *, lose_on_commit: int | None = None) -> None:
        self._in_transaction = True
        self.lose_on_commit = lose_on_commit
        self.commit_count = 0
        self.expire_all_count = 0

    async def commit(self) -> None:
        self.commit_count += 1
        self._in_transaction = False
        if self.commit_count == self.lose_on_commit:
            raise asyncio.CancelledError

    def in_transaction(self) -> bool:
        return self._in_transaction

    def expire_all(self) -> None:
        self.expire_all_count += 1

    def start_transaction(self) -> None:
        self._in_transaction = True


def _confirmation(**updates) -> ContextConfirmationContract:
    value = ContextConfirmationContract(
        id=CONFIRMATION_ID,
        novel_id=NOVEL_ID,
        action="world.alias_relations.extract",
        task="只基于已确认 Scene 补抽别名和关系",
        scope="chapter",
        context_mode="working",
        include_pending_objects=True,
        excluded_asset_ids={},
        selected_asset_ids={"world_entities": ["entity-1"]},
        user_note="不要推测未出现的对象",
        compile_options={"novel_id": NOVEL_ID, "task": "alias"},
        warnings=[],
        sections=[],
        budget_events=[],
        result_refs=[{"type": "task", "id": TASK_ID}],
        result_status="running",
        stale_reasons=[],
        compiled_at="2026-07-14T00:00:00+00:00",
        created_at="2026-07-14T00:00:00+00:00",
    )
    return replace(value, **updates)


def _snapshot() -> dict:
    return {
        "version": "1",
        "novel_id": NOVEL_ID,
        "profile_hash": "frozen-profile-hash",
    }


class _Task:
    def __init__(
        self,
        *,
        result: dict | None = None,
        include_snapshot: bool = True,
        task_id: str = TASK_ID,
    ):
        self.id = uuid.UUID(task_id)
        self.task_type = "world_alias_relation_extraction"
        self.status = "running"
        self.attempt = 1
        self.lease_id = str(uuid.uuid4())
        self.progress = 0.0
        self.meta = {
            "novel_id": NOVEL_ID,
            "context_confirmation_id": CONFIRMATION_ID,
            "start_chapter": 1,
            "end_chapter": 3,
            "scene_ids": ["scene-1"],
        }
        if include_snapshot:
            self.meta["llm_execution_snapshot"] = _snapshot()
        self.result = result or {}

    def update_progress(self, value: float) -> None:
        self.progress = value


class _Port:
    def __init__(self, db: _CheckpointSession) -> None:
        self.db = db
        self.prepare_calls: list[dict] = []
        self.execute_calls = 0
        self.finalize_calls = 0
        self.manifest = {
            "version": 2,
            "plan_fingerprint": "plan-1",
            "scenes": [],
        }
        self.receipt = {
            "version": 2,
            "plan_fingerprint": "plan-1",
            "receipt_hash": "receipt-1",
            "scenes": [],
        }

    async def prepare_alias_relation_task(self, db, **kwargs):
        assert db is self.db
        assert db.in_transaction() is True
        self.prepare_calls.append(kwargs)
        return {
            "manifest": self.manifest,
            "runtime_plan": {
                "version": 2,
                "plan_fingerprint": "plan-1",
                "scenes": [],
            },
        }

    async def execute_alias_relation_task(self, **_kwargs):
        self.execute_calls += 1
        assert self.db.in_transaction() is False
        return self.receipt

    async def finalize_alias_relation_task(self, db, **kwargs):
        self.finalize_calls += 1
        assert db.in_transaction() is True
        assert kwargs["receipt"] == self.receipt
        return {
            "summary": {
                "total_aliases": 2,
                "total_relations": 1,
                "alias_relation_scenes": 1,
            },
            "result_refs": [],
        }


def _patch_handler_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    db: _CheckpointSession,
    port: _Port,
    *,
    confirmations: list[object] | None = None,
    active_side_effect: object | None = None,
) -> tuple[mock.AsyncMock, mock.AsyncMock, mock.AsyncMock]:
    from infrastructure.tasks import facade as task_facade
    from modules.evidence import facade as context_facade
    from modules.project import facade as project_facade

    async def _active(*_args, **_kwargs):
        db.start_transaction()
        if isinstance(active_side_effect, list):
            outcome = active_side_effect.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome

    active = mock.AsyncMock(side_effect=_active)
    exclusive = mock.AsyncMock(side_effect=_active)
    fresh = mock.AsyncMock(
        side_effect=confirmations or [_confirmation(), _confirmation()]
    )
    restore = mock.AsyncMock(return_value={"llm": {"model": "frozen-model"}})
    attached = mock.AsyncMock()
    monkeypatch.setattr(project_facade, "require_active_project", active)
    monkeypatch.setattr(
        project_facade,
        "require_active_project_exclusive",
        exclusive,
    )
    monkeypatch.setattr(project_facade, "restore_project_llm_execution_settings", restore)
    monkeypatch.setattr(
        task_facade,
        "list_running_task_types_for_novel",
        mock.AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        task_facade,
        "require_running_task_attempt",
        mock.AsyncMock(),
    )
    monkeypatch.setattr(context_facade, "require_fresh_confirmation", fresh)
    monkeypatch.setattr(context_facade, "attach_result_ref", attached)
    monkeypatch.setattr(world_tasks, "_container_get", lambda _name: port)
    return active, fresh, attached


async def test_handler_checkpoints_before_provider_and_finalizes_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _active, fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
    )
    task = _Task()

    result = await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert result["total_aliases"] == 2
    assert result["llm_execution_snapshot"] == _snapshot()
    assert port.execute_calls == 1
    assert port.finalize_calls == 1
    assert db.commit_count == 3
    assert db.expire_all_count == 3
    assert fresh.await_count == 2
    assert fresh.await_args_list[0].kwargs.get("for_update", False) is False
    assert fresh.await_args_list[-1].kwargs["for_update"] is True
    assert task.progress == 1.0
    assert task.result["_alias_relation_task_v2"]["stage"] == "done"
    attached.assert_awaited_once_with(
        db,
        novel_id=NOVEL_ID,
        confirmation_id=CONFIRMATION_ID,
        result_type="world_alias_relation_extraction",
        result_id=str(task.id),
        status="done",
    )


async def test_legacy_task_freezes_profile_before_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    db = _CheckpointSession()
    port = _Port(db)
    _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
        confirmations=[_confirmation(), _confirmation(), _confirmation()],
    )
    build = mock.AsyncMock(return_value=_snapshot())
    monkeypatch.setattr(project_facade, "build_project_llm_execution_snapshot", build)
    task = _Task(include_snapshot=False)

    await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert task.meta["llm_execution_snapshot"] == _snapshot()
    assert db.commit_count == 4
    build.assert_awaited_once_with(db, NOVEL_ID)


async def test_retry_reuses_validated_receipt_without_provider_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _patch_handler_dependencies(monkeypatch, db, port)
    task = _Task(
        result={
            "_alias_relation_task_v2": {
                "version": 2,
                "stage": "llm_complete",
                "manifest": port.manifest,
                "receipt": port.receipt,
            }
        }
    )

    await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert port.execute_calls == 0
    assert port.prepare_calls[0]["existing_manifest"] == port.manifest
    assert port.finalize_calls == 1
    assert db.commit_count == 2


async def test_unfinished_v1_checkpoint_fails_closed_before_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _patch_handler_dependencies(monkeypatch, db, port)
    task = _Task(
        result={
            "_alias_relation_task_v1": {
                "version": 1,
                "stage": "llm_complete",
                "manifest": {"version": 1},
                "receipt": {"version": 1},
            }
        }
    )

    with pytest.raises(ValueError, match="v1 task.*submit the task again"):
        await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert port.prepare_calls == []
    assert port.execute_calls == 0
    assert port.finalize_calls == 0


async def test_final_confirmation_drift_keeps_receipt_but_writes_no_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _active, _fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
        confirmations=[
            _confirmation(),
            ValueError("context confirmation is stale_context"),
        ],
    )
    task = _Task()

    with pytest.raises(ValueError, match="stale_context"):
        await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert port.execute_calls == 1
    assert port.finalize_calls == 0
    assert db.commit_count == 2
    assert task.result["_alias_relation_task_v2"]["stage"] == "llm_complete"
    attached.assert_not_awaited()


async def test_final_rejects_concurrent_stale_reason_without_lost_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _active, fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
        confirmations=[
            _confirmation(),
            _confirmation(stale_reasons=["scene_text_changed"]),
        ],
    )
    task = _Task()

    with pytest.raises(ValueError, match="stale reasons"):
        await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert fresh.await_args_list[-1].kwargs["for_update"] is True
    assert port.execute_calls == 1
    assert port.finalize_calls == 0
    assert task.result["_alias_relation_task_v2"]["stage"] == "llm_complete"
    attached.assert_not_awaited()


async def test_superseded_task_discards_detached_provider_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    newer_task_id = "44444444-4444-4444-4444-444444444444"
    _active, fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
        confirmations=[
            _confirmation(),
            _confirmation(
                result_refs=[
                    {"type": "task", "id": TASK_ID},
                    {"type": "task", "id": newer_task_id},
                ],
            ),
        ],
    )
    task = _Task()

    with pytest.raises(ValueError, match="superseded"):
        await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert fresh.await_args_list[-1].kwargs["for_update"] is True
    assert port.execute_calls == 1
    assert port.finalize_calls == 0
    assert task.result["_alias_relation_task_v2"]["stage"] == "llm_complete"
    attached.assert_not_awaited()


@pytest.mark.parametrize(
    ("confirmation", "error"),
    [
        (_confirmation(result_status="confirmed"), "not running"),
        (_confirmation(stale_reasons=["entity_changed"]), "stale reasons"),
        (
            _confirmation(
                result_refs=[
                    {"type": "task", "id": TASK_ID},
                    {"type": "task", "id": "44444444-4444-4444-4444-444444444444"},
                ]
            ),
            "superseded",
        ),
    ],
)
async def test_prepare_requires_current_running_confirmation_owner(
    monkeypatch: pytest.MonkeyPatch,
    confirmation: ContextConfirmationContract,
    error: str,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _active, _fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
        confirmations=[confirmation],
    )

    with pytest.raises(ValueError, match=error):
        await world_tasks.handle_world_alias_relation_extraction(db, _Task())

    assert port.execute_calls == 0
    assert port.finalize_calls == 0
    assert db.commit_count == 0
    attached.assert_not_awaited()


async def test_project_deletion_before_finalize_discards_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    port = _Port(db)
    _active, _fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
        active_side_effect=[None, NotFoundError("Project deleted")],
    )

    with pytest.raises(NotFoundError, match="deleted"):
        await world_tasks.handle_world_alias_relation_extraction(db, _Task())

    assert port.execute_calls == 1
    assert port.finalize_calls == 0
    assert db.commit_count == 2
    attached.assert_not_awaited()


async def test_lease_loss_at_receipt_checkpoint_prevents_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession(lose_on_commit=2)
    port = _Port(db)
    _patch_handler_dependencies(monkeypatch, db, port)

    with pytest.raises(asyncio.CancelledError):
        task = _Task()
        await world_tasks.handle_world_alias_relation_extraction(db, task)

    assert port.execute_calls == 1
    assert port.finalize_calls == 0
    assert task.result["_alias_relation_task_v2"]["stage"] == "prepared"


@pytest.mark.parametrize(
    "writer_type",
    [
        "deep_import",
        "scene_auto_extraction",
        "world_object_auto_extraction",
    ],
)
async def test_running_source_writer_defers_finalization(
    monkeypatch: pytest.MonkeyPatch,
    writer_type: str,
) -> None:
    from infrastructure.tasks import facade as task_facade

    db = _CheckpointSession()
    port = _Port(db)
    _active, _fresh, attached = _patch_handler_dependencies(
        monkeypatch,
        db,
        port,
    )
    monkeypatch.setattr(
        task_facade,
        "list_running_task_types_for_novel",
        mock.AsyncMock(return_value=[writer_type]),
    )

    with pytest.raises(RuntimeError, match="source writer tasks run"):
        await world_tasks.handle_world_alias_relation_extraction(db, _Task())

    assert port.execute_calls == 1
    assert port.finalize_calls == 0
    assert db.commit_count == 2
    attached.assert_not_awaited()


async def test_source_writer_query_is_novel_scoped_and_excludes_current_task(
    db_session,
    project_novel_id: str,
    other_novel_id: str,
) -> None:
    from infrastructure.tasks.facade import list_running_task_types_for_novel

    current_id = uuid.uuid4()
    db_session.add_all(
        [
            AsyncTask(
                id=current_id,
                task_type="world_alias_relation_extraction",
                status="running",
                meta={"novel_id": project_novel_id},
                attempt=1,
                lease_id=str(uuid.uuid4()),
            ),
            AsyncTask(
                id=uuid.uuid4(),
                task_type="deep_import",
                status="running",
                meta={"novel_id": project_novel_id},
                attempt=1,
                lease_id=str(uuid.uuid4()),
            ),
            AsyncTask(
                id=uuid.uuid4(),
                task_type="world_object_auto_extraction",
                status="running",
                meta={"novel_id": other_novel_id},
                attempt=1,
                lease_id=str(uuid.uuid4()),
            ),
            AsyncTask(
                id=uuid.uuid4(),
                task_type="scene_auto_extraction",
                status="done",
                meta={"novel_id": project_novel_id},
                attempt=1,
            ),
        ]
    )
    await db_session.flush()

    result = await list_running_task_types_for_novel(
        db_session,
        novel_id=project_novel_id,
        task_types={
            "deep_import",
            "scene_auto_extraction",
            "world_object_auto_extraction",
            "world_alias_relation_extraction",
        },
        exclude_task_id=str(current_id),
    )

    assert result == ["deep_import"]


async def test_project_finalizer_seam_compiles_to_exclusive_row_lock() -> None:
    from sqlalchemy.dialects import postgresql

    from modules.project.repositories import ProjectRepository

    statements: list[object] = []

    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return object()

    class _Db:
        async def execute(self, statement):
            statements.append(statement)
            return _Result()

    project_id = uuid.UUID(NOVEL_ID)
    await ProjectRepository().get_active_for_update(
        _Db(),  # type: ignore[arg-type]
        project_id,
    )

    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert project_id in statements[0].compile().params.values()
    assert "FOR UPDATE" in sql
    assert "FOR SHARE" not in sql


async def test_confirmation_finalizer_seam_compiles_to_row_lock() -> None:
    from sqlalchemy.dialects import postgresql

    from modules.evidence.compilation.repositories import ContextConfirmationRepository

    statements: list[object] = []

    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return object()

    class _Db:
        async def execute(self, statement):
            statements.append(statement)
            return _Result()

    confirmation_id = uuid.UUID(CONFIRMATION_ID)
    await ContextConfirmationRepository().get(
        _Db(),  # type: ignore[arg-type]
        confirmation_id,
        novel_id=uuid.UUID(NOVEL_ID),
        for_update=True,
    )

    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert confirmation_id in statements[0].compile().params.values()
    assert "FOR UPDATE" in sql


async def test_current_attempt_finalizer_seam_compiles_to_exact_row_lock() -> None:
    from sqlalchemy.dialects import postgresql

    from infrastructure.tasks.lifecycle import TaskLifecycleService

    statements: list[object] = []

    class _Result:
        @staticmethod
        def scalar_one_or_none():
            return uuid.UUID(TASK_ID)

    class _Db:
        async def execute(self, statement):
            statements.append(statement)
            return _Result()

    lease_id = str(uuid.uuid4())
    await TaskLifecycleService().require_running_attempt(
        _Db(),  # type: ignore[arg-type]
        task_id=TASK_ID,
        task_type="world_alias_relation_extraction",
        novel_id=NOVEL_ID,
        lease_id=lease_id,
        attempt=7,
    )

    compiled = statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    values = set(compiled.params.values())
    assert "FOR UPDATE" in sql
    assert "FOR SHARE" not in sql
    assert {
        uuid.UUID(TASK_ID),
        "world_alias_relation_extraction",
        uuid.UUID(NOVEL_ID),
        "running",
        lease_id,
        7,
    }.issubset(values)


async def test_real_task_handler_session_fences_each_checkpoint(
    db_session,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.evidence.facade import (
        attach_result_ref,
        confirm_context,
        require_confirmation,
    )
    from modules.project import facade as project_facade

    confirmation = await confirm_context(
        db_session,
        novel_id=project_novel_id,
        action="world.alias_relations.extract",
        task="真实 task handler session 事务边界",
        scope="project",
    )
    lease_id = str(uuid.uuid4())
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="world_alias_relation_extraction",
        status="running",
        attempt=1,
        lease_id=lease_id,
        progress=0.0,
        meta={
            "novel_id": project_novel_id,
            "context_confirmation_id": confirmation.id,
            "start_chapter": 1,
            "end_chapter": 1,
            "scene_ids": [],
            "llm_execution_snapshot": {
                **_snapshot(),
                "novel_id": project_novel_id,
            },
        },
        result={},
    )
    db_session.add(task)
    await attach_result_ref(
        db_session,
        novel_id=project_novel_id,
        confirmation_id=confirmation.id,
        result_type="task",
        result_id=str(task.id),
        status="running",
    )
    await db_session.commit()
    db_session.expunge(task)

    bind = db_session.bind
    assert bind is not None
    task_session = _TaskHandlerSession(
        bind=bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    checkpoint_count = 0

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return await TaskLifecycleService().checkpoint_running_attempt(
            task_session,
            task=task,
            lease_id=lease_id,
        )

    class _RealPort(_Port):
        async def execute_alias_relation_task(self, **kwargs):
            assert task_session.in_transaction() is False
            return await super().execute_alias_relation_task(**kwargs)

    port = _RealPort(task_session)  # type: ignore[arg-type]
    monkeypatch.setattr(world_tasks, "_container_get", lambda _name: port)
    monkeypatch.setattr(
        project_facade,
        "restore_project_llm_execution_settings",
        mock.AsyncMock(return_value={"llm": {"model": "frozen-model"}}),
    )
    task_session.set_task_commit_hook(_checkpoint)
    try:
        result = await world_tasks.handle_world_alias_relation_extraction(
            task_session,
            task,
        )
        tracked = await require_confirmation(
            task_session,
            novel_id=project_novel_id,
            action="world.alias_relations.extract",
            confirmation_id=confirmation.id,
        )
        assert result["total_aliases"] == 2
        assert checkpoint_count == 3
        assert {
            "type": "world_alias_relation_extraction",
            "id": str(task.id),
        } in tracked.result_refs
    finally:
        await task_session.close()


async def test_real_worker_rejected_final_checkpoint_rolls_back_domain_and_binding(
    test_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from infrastructure.tasks.registry import TaskRegistry
    from infrastructure.tasks.worker import TaskWorker
    from modules.evidence.compilation.models import ContextConfirmation
    from modules.evidence.facade import attach_result_ref, confirm_context
    from modules.project.models import Project
    from modules.world.models import CoreEntity
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    task_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    confirmation_id: str | None = None
    guard_calls = 0

    class _Manager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    class _MutatingPort(_Port):
        async def finalize_alias_relation_task(self, db, **kwargs):
            self.finalize_calls += 1
            assert db.in_transaction() is True
            assert kwargs["receipt"] == self.receipt
            entity = await db.get(CoreEntity, entity_id)
            assert entity is not None
            entity.content_json = {"aliases": ["must-roll-back"]}
            await db.flush()
            return {
                "summary": {
                    "total_aliases": 1,
                    "total_relations": 0,
                    "alias_relation_scenes": 1,
                },
                "result_refs": [{"type": "core_entity", "id": str(entity_id)}],
            }

    async def _reject_final_checkpoint(db, task) -> bool:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 3:
            return False
        return await _guard_active_task_project_finalize(db, task)

    registry = TaskRegistry()
    assert (
        registry.get_handler("world_alias_relation_extraction")
        is world_tasks.handle_world_alias_relation_extraction
    )
    try:
        async with sessions() as setup_db:
            setup_db.add(
                Project(
                    id=novel_uuid,
                    title="alias final checkpoint rollback",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )
            setup_db.add(
                CoreEntity(
                    id=entity_id,
                    novel_id=novel_uuid,
                    entity_type="character",
                    name="Rollback Target",
                    status="canonical",
                    content_json={"aliases": []},
                )
            )
            await setup_db.flush()
            confirmation = await confirm_context(
                setup_db,
                novel_id=novel_id,
                action="world.alias_relations.extract",
                task="worker final checkpoint rollback",
                scope="project",
                context_mode="working",
            )
            confirmation_id = confirmation.id
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type="world_alias_relation_extraction",
                    status="pending",
                    meta={
                        "novel_id": novel_id,
                        "context_confirmation_id": confirmation.id,
                        "start_chapter": 1,
                        "end_chapter": 1,
                        "scene_ids": [],
                        "llm_execution_snapshot": {
                            **_snapshot(),
                            "novel_id": novel_id,
                        },
                    },
                )
            )
            await attach_result_ref(
                setup_db,
                novel_id=novel_id,
                confirmation_id=confirmation.id,
                result_type="task",
                result_id=str(task_id),
                status="running",
            )
            await setup_db.commit()

        class _DeferredPort(_MutatingPort):
            async def prepare_alias_relation_task(self, db, **kwargs):
                self.db = db
                return await super().prepare_alias_relation_task(db, **kwargs)

        port = _DeferredPort(None)  # type: ignore[arg-type]

        monkeypatch.setattr(world_tasks, "_container_get", lambda _name: port)
        monkeypatch.setattr(
            "modules.project.facade.restore_project_llm_execution_settings",
            mock.AsyncMock(return_value={"llm": {"model": "frozen-model"}}),
        )

        worker = TaskWorker(
            db_manager=_Manager(),
            heartbeat_interval=60.0,
            task_preflight=_require_active_task_project,
            task_commit_guard=_reject_final_checkpoint,
        )
        returned = await worker.run_once()

        assert returned is not None
        assert returned.id == task_id
        assert returned.status == "cancelled"
        assert returned.progress == 0.75
        assert returned.result["_alias_relation_task_v2"]["stage"] == "llm_complete"
        assert guard_calls == 4
        assert port.execute_calls == 1
        assert port.finalize_calls == 1

        async with sessions() as verify_db:
            entity = await verify_db.get(CoreEntity, entity_id)
            assert entity is not None
            assert entity.content_json == {"aliases": []}
            confirmation_row = await verify_db.get(
                ContextConfirmation,
                uuid.UUID(str(confirmation_id)),
            )
            assert confirmation_row is not None
            assert confirmation_row.result_status == "running"
            assert confirmation_row.result_refs == [{"type": "task", "id": str(task_id)}]
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(CoreEntity).where(CoreEntity.id == entity_id))
            if confirmation_id is not None:
                await cleanup_db.execute(
                    delete(ContextConfirmation).where(
                        ContextConfirmation.id == uuid.UUID(confirmation_id)
                    )
                )
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup_db.execute(delete(Project).where(Project.id == novel_uuid))
