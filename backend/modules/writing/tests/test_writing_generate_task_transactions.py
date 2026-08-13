from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.errors import LLMTimeoutError
from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.models import AsyncTask
from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.project.contracts import ProjectLLMConfigurationError
from modules.writing.services import WritingGenerationService


class _CheckpointSession:
    task_checkpoint_enabled = True

    def __init__(self, *, lose_lease: bool = False) -> None:
        self._in_transaction = True
        self._lose_lease = lose_lease
        self.commit_count = 0
        self.expire_all_count = 0

    async def commit(self) -> None:
        self.commit_count += 1
        self._in_transaction = False
        if self._lose_lease:
            raise asyncio.CancelledError

    def in_transaction(self) -> bool:
        return self._in_transaction

    def expire_all(self) -> None:
        self.expire_all_count += 1


def _confirmed(
    markdown: str,
    *,
    source_id: str = "source-1",
    pov: bool = False,
) -> SimpleNamespace:
    options = {"chapter_index": 3, "scope": "chapter"}
    if pov:
        options.update(
            {
                "scene_id": "scene-1",
                "reveal_mode": "character",
                "viewpoint_character_id": "character-1",
            }
        )
    return SimpleNamespace(
        rendered_markdown=markdown,
        compile_options=options,
        result_refs=[{"type": "task", "id": "task-1"}],
        confirmation=SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            novel_id="11111111-1111-1111-1111-111111111111",
            action="writing.generate",
            task="generate",
            scope="chapter",
            context_mode="canonical",
            include_pending_objects=False,
            selected_asset_ids={"project": ["project-1"]},
            excluded_asset_ids={},
            user_note=None,
            warnings=[],
            result_status="running",
            stale_reasons=[],
            compile_options=options,
        ),
        compiled=CompiledContext(
            sections=[
                ContextSection(
                    key="project_core",
                    tier=Tier.P0,
                    content=markdown,
                    token_count=3,
                    status="canonical",
                    sources=[{"type": "project", "id": source_id}],
                    retrieval_metadata={"latency_metadata": {"total_ms": 1.0}},
                )
            ],
            total_tokens=3,
            budget_tokens=4000,
        ),
    )


def _repo() -> SimpleNamespace:
    created: list[object] = []

    async def _create(_db, data, *, status):
        created.append(data)
        return SimpleNamespace(
            id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
            novel_id=uuid.UUID(data.novel_id),
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content,
            content_hash="a" * 64,
            version_number=1,
            status=status,
            conflict_check_snapshot_json=None,
            provenance_json=data.provenance_json,
            created_at=None,
            updated_at=None,
        )

    return SimpleNamespace(
        created=created,
        create_with_status=mock.AsyncMock(side_effect=_create),
        get_latest_by_chapter=mock.AsyncMock(return_value=None),
        get_for_update=mock.AsyncMock(return_value=None),
    )


def _patch_facades(
    monkeypatch: pytest.MonkeyPatch,
    *confirmations: object,
    guard_terms: list[object] | None = None,
    project_guard: mock.AsyncMock | None = None,
) -> tuple[mock.AsyncMock, mock.AsyncMock, mock.AsyncMock, mock.AsyncMock]:
    from modules.context import facade as context_facade
    from modules.project import facade as project_facade

    prepared = mock.AsyncMock(side_effect=list(confirmations))
    hidden = mock.AsyncMock(return_value=list(guard_terms or []))
    bound = mock.AsyncMock()
    guard = project_guard or mock.AsyncMock()
    monkeypatch.setattr(context_facade, "prepare_confirmed_ai_action", prepared)
    monkeypatch.setattr(context_facade, "build_hidden_guard_context", hidden)
    monkeypatch.setattr(context_facade, "bind_confirmed_action_result", bound)
    monkeypatch.setattr(project_facade, "require_active_project", guard)
    return prepared, hidden, bound, guard


class _Client:
    model_name = "live-model"

    def __init__(self, db: _CheckpointSession, outcome: object = "candidate") -> None:
        self._db = db
        self._outcome = outcome
        self.requests: list[object] = []

    async def generate(self, request):
        assert self._db.in_transaction() is False
        self.requests.append(request)
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return LLMCallResponse(content=str(self._outcome), model=self.model_name)


def _snapshot() -> dict:
    return {"profile": {"model": "frozen-model"}, "profile_hash": "frozen"}


async def test_task_only_generation_rejects_ordinary_sessions() -> None:
    service = WritingGenerationService(llm_client=mock.MagicMock())

    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await service.generate_candidate_for_task(
            SimpleNamespace(task_checkpoint_enabled=False),
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )


async def test_generation_wait_parse_and_sanitize_run_without_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    confirmed = _confirmed("same context")
    repo = _repo()
    prepared, _hidden, bound, guard = _patch_facades(
        monkeypatch,
        confirmed,
        copy.deepcopy(confirmed),
    )
    client = _Client(db, "<script>bad()</script>正文<b>加粗</b>")

    result = await WritingGenerationService(
        repo=repo,
        llm_client=client,
    ).generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title="<b>第三章</b>",
        instruction="continue",
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )

    assert result.content == "正文加粗"
    assert result.title == "第三章"
    assert result.provenance_json["source_task_id"] == "task-1"
    assert client.requests[0].model == "frozen-model"
    assert db.commit_count == 1
    assert db.expire_all_count == 1
    assert guard.await_count == 2
    assert "for_update" not in prepared.await_args_list[0].kwargs
    assert prepared.await_args_list[1].kwargs["for_update"] is True
    bound.assert_awaited_once()


async def test_generation_uses_requested_chapter_when_scene_anchor_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    confirmed = _confirmed("scene-spanning context")
    confirmed.compile_options.update(
        {
            "chapter_index": 4,
            "requested_chapter_index": 3,
            "scene_id": "scene-spanning-chapters",
        }
    )
    repo = _repo()
    _patch_facades(monkeypatch, confirmed, copy.deepcopy(confirmed))
    client = _Client(db)

    result = await WritingGenerationService(
        repo=repo,
        llm_client=client,
    ).generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )

    assert result.chapter_index == 3
    assert len(client.requests) == 1


@pytest.mark.parametrize("drift", ["rendered", "evidence"])
async def test_generation_discards_context_and_evidence_drift(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    db = _CheckpointSession()
    before = _confirmed("same context", source_id="source-before")
    after = copy.deepcopy(before)
    if drift == "rendered":
        after.rendered_markdown = "changed context"
        after.compiled.sections[0].content = "changed context"
    else:
        after.compiled.sections[0].sources = [{"type": "project", "id": "source-after"}]
    repo = _repo()
    _patch_facades(monkeypatch, before, after)

    with pytest.raises(ValidationError, match="discarded stale result"):
        await WritingGenerationService(
            repo=repo,
            llm_client=_Client(db),
        ).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    repo.create_with_status.assert_not_awaited()


async def test_generation_ignores_latency_only_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    before = _confirmed("same context")
    after = copy.deepcopy(before)
    after.compiled.sections[0].retrieval_metadata["latency_metadata"] = {
        "total_ms": 987.0,
        "retrieve_ms": 654.0,
    }
    repo = _repo()
    _patch_facades(monkeypatch, before, after)

    result = await WritingGenerationService(
        repo=repo,
        llm_client=_Client(db),
    ).generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )

    assert result.status == "candidate"
    repo.create_with_status.assert_awaited_once()


@pytest.mark.parametrize("drift", ["done", "superseded", "stale_reasons"])
async def test_generation_discards_confirmation_lifecycle_drift(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    db = _CheckpointSession()
    before = _confirmed("same context")
    after = copy.deepcopy(before)
    if drift == "done":
        after.confirmation.result_status = "done"
    elif drift == "superseded":
        after.result_refs.append({"type": "task", "id": "newer-task"})
    else:
        after.confirmation.stale_reasons = ["source_changed"]
    repo = _repo()
    client = _Client(db)
    _patch_facades(monkeypatch, before, after)

    with pytest.raises(ValidationError):
        await WritingGenerationService(
            repo=repo,
            llm_client=client,
        ).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    assert len(client.requests) == 1
    repo.create_with_status.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["not_running", "unowned", "chapter"])
async def test_generation_rejects_invalid_task_confirmation_before_provider(
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    db = _CheckpointSession()
    confirmed = _confirmed("same context")
    if invalid == "not_running":
        confirmed.confirmation.result_status = "confirmed"
    elif invalid == "unowned":
        confirmed.result_refs = [{"type": "task", "id": "another-task"}]
    else:
        confirmed.compile_options["chapter_index"] = 2
    repo = _repo()
    client = _Client(db)
    _patch_facades(monkeypatch, confirmed)

    with pytest.raises(ValidationError):
        await WritingGenerationService(
            repo=repo,
            llm_client=client,
        ).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    assert client.requests == []
    assert db.commit_count == 0
    repo.create_with_status.assert_not_awaited()


async def test_generation_lease_loss_at_checkpoint_writes_no_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession(lose_lease=True)
    repo = _repo()
    _patch_facades(monkeypatch, _confirmed("same context"))

    with pytest.raises(asyncio.CancelledError):
        await WritingGenerationService(
            repo=repo,
            llm_client=_Client(db),
        ).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    repo.create_with_status.assert_not_awaited()


async def test_project_delete_before_finalize_writes_no_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    repo = _repo()
    project_guard = mock.AsyncMock(
        side_effect=[None, NotFoundError("Project was permanently deleted")]
    )
    _patch_facades(
        monkeypatch,
        _confirmed("same context"),
        project_guard=project_guard,
    )

    with pytest.raises(NotFoundError, match="permanently deleted"):
        await WritingGenerationService(
            repo=repo,
            llm_client=_Client(db),
        ).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    repo.create_with_status.assert_not_awaited()


async def test_pov_guard_uses_frozen_terms_outside_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    before = _confirmed("POV context", pov=True)
    after = copy.deepcopy(before)
    term = SimpleNamespace(
        phrase="隐藏真相",
        rule="hidden_truth_match",
        severity="error",
        source_type="core_entity",
        source_id="entity-1",
        source_label="hidden",
    )
    repo = _repo()
    _prepared, hidden, _bound, _guard = _patch_facades(
        monkeypatch,
        before,
        after,
        guard_terms=[term],
    )
    payload = (
        '{"pov_state":{"perceived_facts":[]},'
        '"draft_prose":"她说出了隐藏真相。","uncertainties":[]}'
    )
    service = WritingGenerationService(repo=repo, llm_client=_Client(db, payload))
    original_validate = service._pov_guard.validate

    def _validate(**kwargs):
        assert db.in_transaction() is False
        return original_validate(**kwargs)

    monkeypatch.setattr(service._pov_guard, "validate", _validate)
    result = await service.generate_candidate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        chapter_index=3,
        title=None,
        instruction=None,
        context_confirmation_id="33333333-3333-3333-3333-333333333333",
        source_task_id="task-1",
        llm_execution_snapshot=_snapshot(),
    )

    assert result.provenance_json["generation_profile"] == "pov_character"
    assert result.provenance_json["pov_validation"]["status"] == "failed"
    assert hidden.await_count == 2


async def test_task_client_closes_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    repo = _repo()
    _patch_facades(monkeypatch, _confirmed("same context"))
    client = _Client(db, asyncio.CancelledError())
    client.close = mock.AsyncMock()  # type: ignore[attr-defined]
    with (
        mock.patch(
            "modules.project.facade.restore_project_llm_execution_settings",
            autospec=True,
            return_value={"llm": {"model": "frozen-model"}},
        ),
        mock.patch(
            "modules.project.facade.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await WritingGenerationService(
                repo=repo,
            ).generate_candidate_for_task(
                db,
                novel_id="11111111-1111-1111-1111-111111111111",
                chapter_index=3,
                title=None,
                instruction=None,
                context_confirmation_id="33333333-3333-3333-3333-333333333333",
                source_task_id="task-1",
                llm_execution_snapshot=_snapshot(),
            )

    client.close.assert_awaited_once()
    repo.create_with_status.assert_not_awaited()


async def test_task_client_closes_once_and_revalidates_profile_before_finalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    repo = _repo()
    _patch_facades(
        monkeypatch,
        _confirmed("same context"),
        _confirmed("same context"),
    )
    client = _Client(db)

    async def _close() -> None:
        assert db.in_transaction() is False

    client.close = mock.AsyncMock(side_effect=_close)  # type: ignore[attr-defined]
    with (
        mock.patch(
            "modules.project.facade.restore_project_llm_execution_settings",
            autospec=True,
            side_effect=[
                {"llm": {"model": "frozen-model"}},
                {"llm": {"model": "frozen-model"}},
            ],
        ) as restore_snapshot,
        mock.patch(
            "modules.project.facade.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ) as create_client,
    ):
        result = await WritingGenerationService(repo=repo).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    assert result.status == "candidate"
    assert restore_snapshot.await_count == 2
    create_client.assert_called_once()
    assert create_client.call_args.kwargs["timeout_override"] == 1800
    client.close.assert_awaited_once()


async def test_project_profile_drift_before_finalize_writes_no_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    repo = _repo()
    _patch_facades(monkeypatch, _confirmed("same context"))
    client = _Client(db)
    client.close = mock.AsyncMock()  # type: ignore[attr-defined]
    with (
        mock.patch(
            "modules.project.facade.restore_project_llm_execution_settings",
            autospec=True,
            side_effect=[
                {"llm": {"model": "frozen-model"}},
                ProjectLLMConfigurationError(
                    "Project LLM provider changed after the task started"
                ),
            ],
        ) as restore_snapshot,
        mock.patch(
            "modules.project.facade.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ),
    ):
        with pytest.raises(ProjectLLMConfigurationError, match="provider changed"):
            await WritingGenerationService(repo=repo).generate_candidate_for_task(
                db,
                novel_id="11111111-1111-1111-1111-111111111111",
                chapter_index=3,
                title=None,
                instruction=None,
                context_confirmation_id="33333333-3333-3333-3333-333333333333",
                source_task_id="task-1",
                llm_execution_snapshot=_snapshot(),
            )

    assert restore_snapshot.await_count == 2
    client.close.assert_awaited_once()
    repo.create_with_status.assert_not_awaited()


async def test_provider_error_is_redacted_and_writes_no_candidate(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _CheckpointSession()
    repo = _repo()
    _patch_facades(monkeypatch, _confirmed("same context"))
    secret = "sk-generation-secret"

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError) as exc_info:
            await WritingGenerationService(
                repo=repo,
                llm_client=_Client(
                    db,
                    RuntimeError(f"provider failed api_key={secret}"),
                ),
            ).generate_candidate_for_task(
                db,
                novel_id="11111111-1111-1111-1111-111111111111",
                chapter_index=3,
                title=None,
                instruction=None,
                context_confirmation_id="33333333-3333-3333-3333-333333333333",
                source_task_id="task-1",
                llm_execution_snapshot=_snapshot(),
            )

    assert secret not in str(exc_info.value)
    assert secret not in caplog.text
    repo.create_with_status.assert_not_awaited()


async def test_retryable_provider_error_keeps_task_retry_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    repo = _repo()
    _patch_facades(monkeypatch, _confirmed("same context"))
    timeout = LLMTimeoutError("provider timed out")

    with pytest.raises(LLMTimeoutError) as exc_info:
        await WritingGenerationService(
            repo=repo,
            llm_client=_Client(db, timeout),
        ).generate_candidate_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )

    assert exc_info.value is timeout
    repo.create_with_status.assert_not_awaited()


async def test_generation_legacy_task_freezes_and_reuses_snapshot() -> None:
    from modules.writing.tasks import _require_llm_execution_snapshot

    db = _CheckpointSession()
    task = SimpleNamespace(meta={"novel_id": "novel-1"})
    snapshot = _snapshot()
    with (
        mock.patch(
            "modules.project.facade.require_active_project",
            autospec=True,
        ) as project_guard,
        mock.patch(
            "modules.project.facade.build_project_llm_execution_snapshot",
            autospec=True,
            return_value=snapshot,
        ) as build_snapshot,
    ):
        result, legacy = await _require_llm_execution_snapshot(
            db,
            task,
            dict(task.meta),
            "novel-1",
            legacy_meta_key=None,
        )
        replay, replay_legacy = await _require_llm_execution_snapshot(
            db,
            task,
            dict(task.meta),
            "novel-1",
            legacy_meta_key=None,
        )

    assert result == replay == snapshot
    assert legacy is replay_legacy is False
    assert "_legacy_unowned_ai_review" not in task.meta
    assert db.commit_count == 1
    assert db.expire_all_count == 1
    project_guard.assert_awaited_once_with(db, "novel-1")
    build_snapshot.assert_awaited_once_with(db, "novel-1")


async def test_real_task_session_checkpoints_before_provider_wait(
    db_session,
    test_project_id: str,
) -> None:
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.context.facade import bind_confirmed_action_result, confirm_context

    task_id = uuid.uuid4()
    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        task="real task transaction boundary",
        scope="project",
        chapter_index=3,
    )
    await bind_confirmed_action_result(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="task",
        result_id=str(task_id),
        status="running",
    )
    lease_id = str(uuid.uuid4())
    task = AsyncTask(
        id=task_id,
        task_type="writing_generate",
        status="running",
        progress=0.25,
        meta={"novel_id": test_project_id},
        result={},
        lease_id=lease_id,
    )
    db_session.add(task)
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
    transaction_states: list[bool] = []

    async def _checkpoint() -> bool:
        nonlocal checkpoint_count
        checkpoint_count += 1
        return await TaskLifecycleService().checkpoint_running_attempt(
            task_session,
            task=task,
            lease_id=lease_id,
        )

    class _RealClient:
        model_name = "frozen-model"

        async def generate(self, _request):
            transaction_states.append(task_session.in_transaction())
            return LLMCallResponse(content="candidate")

    task_session.set_task_commit_hook(_checkpoint)
    try:
        result = await WritingGenerationService(
            llm_client=_RealClient(),
        ).generate_candidate_for_task(
            task_session,
            novel_id=test_project_id,
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id=confirmation.id,
            source_task_id=str(task_id),
            llm_execution_snapshot=_snapshot(),
        )

        assert result.status == "candidate"
        assert transaction_states == [False]
        assert checkpoint_count == 1
        checkpointed = await task_session.get(AsyncTask, task_id)
        assert checkpointed is not None
        assert checkpointed.progress == 0.25
        assert checkpointed.heartbeat_at is not None
    finally:
        await task_session.close()


async def test_real_worker_rejected_finalization_rolls_back_candidate_and_binding(
    test_engine,
) -> None:
    from infrastructure.tasks.registry import TaskRegistry
    from infrastructure.tasks.worker import TaskWorker
    from modules.context.facade import bind_confirmed_action_result, confirm_context
    from modules.context.models import ContextConfirmation
    from modules.project.models import Project
    from modules.writing.models import WritingDraft
    from modules.writing.tasks import handle_writing_generate
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
    confirmation_id: str | None = None
    registry = TaskRegistry()
    registered_here = False
    if registry.get_handler("writing_generate") is None:
        registry.register(
            "writing_generate",
            handle_writing_generate,
            recovery_policy="restart_origin",
        )
        registered_here = True
    else:
        assert registry.get_handler("writing_generate") is handle_writing_generate

    class _Manager:
        def __init__(self) -> None:
            self.engine = test_engine
            self.session_factory = sessions

    class _CancellingClient:
        model_name = "frozen-model"

        def __init__(self) -> None:
            self.close_count = 0

        async def generate(self, _request):
            # The provider wait is transaction-free, so cancellation can win the
            # task lease before the final candidate transaction starts.
            async with sessions() as cancel_db:
                current = await cancel_db.get(AsyncTask, task_id)
                assert current is not None
                assert current.status == "running"
                current.mark_cancelled()
                await cancel_db.commit()
            return LLMCallResponse(content="must be rolled back", model=self.model_name)

        async def close(self) -> None:
            self.close_count += 1

    client = _CancellingClient()
    try:
        async with sessions() as setup_db:
            setup_db.add(
                Project(
                    id=novel_uuid,
                    title="writing worker rollback",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )
            await setup_db.flush()
            confirmation = await confirm_context(
                setup_db,
                novel_id=novel_id,
                action="writing.generate",
                task="worker finalization rollback",
                scope="project",
                chapter_index=3,
            )
            confirmation_id = confirmation.id
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type="writing_generate",
                    status="pending",
                    meta={
                        "novel_id": novel_id,
                        "chapter_index": 3,
                        "context_confirmation_id": confirmation.id,
                        "llm_execution_snapshot": _snapshot(),
                    },
                )
            )
            await bind_confirmed_action_result(
                setup_db,
                novel_id=novel_id,
                confirmation_id=confirmation.id,
                result_type="task",
                result_id=str(task_id),
                status="running",
            )
            await setup_db.commit()

        with (
            mock.patch(
                "modules.project.facade.restore_project_llm_execution_settings",
                autospec=True,
                return_value={"llm": {"model": "frozen-model"}},
            ) as restore_snapshot,
            mock.patch(
                "modules.project.facade.create_project_snapshot_llm_client",
                autospec=True,
                return_value=client,
            ),
        ):
            returned = await TaskWorker(
                db_manager=_Manager(),
                heartbeat_interval=60.0,
                task_preflight=_require_active_task_project,
                task_commit_guard=_guard_active_task_project_finalize,
            ).run_once()

        assert returned is not None
        assert returned.id == task_id
        assert returned.status == "cancelled"
        assert restore_snapshot.await_count == 2
        assert client.close_count == 1
        async with sessions() as verify_db:
            drafts = list(
                (
                    await verify_db.execute(
                        select(WritingDraft).where(
                            WritingDraft.novel_id == novel_uuid,
                        )
                    )
                ).scalars()
            )
            assert drafts == []
            confirmation_row = await verify_db.get(
                ContextConfirmation,
                uuid.UUID(str(confirmation_id)),
            )
            assert confirmation_row is not None
            assert confirmation_row.result_status == "running"
            assert confirmation_row.result_refs == [{"type": "task", "id": str(task_id)}]
    finally:
        if registered_here:
            registry.unregister("writing_generate")
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(WritingDraft).where(WritingDraft.novel_id == novel_uuid)
            )
            if confirmation_id is not None:
                await cleanup_db.execute(
                    delete(ContextConfirmation).where(
                        ContextConfirmation.id == uuid.UUID(confirmation_id)
                    )
                )
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup_db.execute(delete(Project).where(Project.id == novel_uuid))


async def test_generation_confirmation_cannot_cross_novels(
    db_session,
    test_project_id: str,
) -> None:
    from modules.context.facade import confirm_context
    from modules.project.models import Project

    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        task="novel isolation",
        scope="project",
    )
    foreign_id = str(uuid.uuid4())
    db_session.add(Project(id=uuid.UUID(foreign_id), title="foreign"))
    await db_session.flush()
    db_session.task_checkpoint_enabled = True  # type: ignore[attr-defined]

    with pytest.raises((NotFoundError, ValueError)):
        await WritingGenerationService(
            llm_client=mock.MagicMock(),
        ).generate_candidate_for_task(
            db_session,
            novel_id=foreign_id,
            chapter_index=3,
            title=None,
            instruction=None,
            context_confirmation_id=confirmation.id,
            source_task_id="task-1",
            llm_execution_snapshot=_snapshot(),
        )
