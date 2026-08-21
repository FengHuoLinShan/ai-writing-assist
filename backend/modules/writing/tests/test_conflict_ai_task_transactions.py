from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

from core.errors import NotFoundError, ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.writing.conflict_ai import (
    ConflictCheckAiReviewService,
    _task_source_fingerprint,
)
from modules.writing.models import WritingConflictCheck
from modules.writing.repositories import AI_REVIEW_TASK_OWNER_KEY


class _CheckpointSession:
    task_checkpoint_enabled = True

    def __init__(self) -> None:
        self._in_transaction = True
        self.commit_count = 0
        self.expire_all_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1
        self._in_transaction = False

    async def rollback(self) -> None:
        self.rollback_count += 1
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def expire_all(self) -> None:
        self.expire_all_count += 1


def _confirmed(markdown: str, *, source_id: str = "source-1") -> SimpleNamespace:
    return SimpleNamespace(
        rendered_markdown=markdown,
        compile_options={"chapter_index": 3, "scope": "chapter"},
        confirmation=SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            novel_id="11111111-1111-1111-1111-111111111111",
            action="writing.conflict_check.ai_review",
            task="review",
            scope="chapter",
            context_mode="canonical",
            include_pending_objects=False,
            selected_asset_ids={"project": ["project-1"]},
            excluded_asset_ids={},
            user_note=None,
            warnings=[],
            compile_options={"chapter_index": 3, "scope": "chapter"},
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


def _check(
    *,
    owner: str | None = "task-1",
    status: str = "running",
) -> SimpleNamespace:
    summary = {"total": 1, "by_severity": {"medium": 1}}
    if owner:
        summary[AI_REVIEW_TASK_OWNER_KEY] = owner
    return SimpleNamespace(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        novel_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        chapter_index=3,
        scene_id=None,
        draft_id=None,
        version_number=1,
        scope={"chapter_index": 3, "content_excerpt": "draft"},
        include_candidates=False,
        status="completed",
        summary_json=summary,
        ai_review_status=status,
        ai_review_confirmation_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
    )


def _item(*, evidence: str = "before") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        check_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        novel_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        kind="required_missing",
        severity="medium",
        source_module="outline",
        source_type="scene.must_happen",
        source_id="scene-1",
        evidence_summary=evidence,
        location_json={"target": "editor"},
        is_ai_judgment=False,
        needs_review=False,
        confidence=None,
        source_confirmation_id=None,
        llm_rationale=None,
        status="open",
        suggestion_status="not_requested",
        suggestion_confirmation_id=None,
        ai_suggestion=None,
        suggestion_error=None,
        created_at=None,
    )


def _repo(*pairs: tuple[object, list[object]]) -> SimpleNamespace:
    async def _update(_db, check, **values):
        for key, value in values.items():
            if key == "summary_json":
                check.summary_json = value
            elif key == "status":
                check.ai_review_status = value
            elif key == "confirmation_id":
                check.ai_review_confirmation_id = value
            elif key == "model":
                check.ai_review_model = value
            elif key == "error":
                check.ai_review_error = value
        return check

    return SimpleNamespace(
        get_check_for_ai_review_update=mock.AsyncMock(side_effect=list(pairs)),
        update_loaded_ai_review=mock.AsyncMock(side_effect=_update),
        append_items=mock.AsyncMock(return_value=[]),
    )


def _patch_facades(
    monkeypatch: pytest.MonkeyPatch,
    *confirmations: object,
    project_guard: mock.AsyncMock | None = None,
) -> tuple[mock.AsyncMock, mock.AsyncMock, mock.AsyncMock]:
    from modules.evidence import facade as context_facade
    from modules.project import facade as project_facade

    prepared = mock.AsyncMock(side_effect=list(confirmations))
    bound = mock.AsyncMock()
    guard = project_guard or mock.AsyncMock()
    monkeypatch.setattr(context_facade, "prepare_confirmed_ai_action", prepared)
    monkeypatch.setattr(context_facade, "bind_confirmed_action_result", bound)
    monkeypatch.setattr(project_facade, "require_active_project", guard)
    return prepared, bound, guard


class _Client:
    model_name = "task-model"

    def __init__(self, db: _CheckpointSession, outcome: object | None = None) -> None:
        self._db = db
        self._outcome = outcome

    async def generate_structured(self, _request, schema, **_kwargs):
        assert self._db.in_transaction() is False
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return schema(issues=self._outcome or [])


async def test_task_only_review_rejects_ordinary_sessions() -> None:
    service = ConflictCheckAiReviewService(
        mock.MagicMock(),
        llm_client=mock.MagicMock(),
    )

    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await service.run_for_task(
            SimpleNamespace(task_checkpoint_enabled=False),
            novel_id="11111111-1111-1111-1111-111111111111",
            check_id="22222222-2222-2222-2222-222222222222",
            context_confirmation_id="33333333-3333-3333-3333-333333333333",
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )


@pytest.mark.parametrize("drift", ["check", "item", "context"])
async def test_task_review_discards_check_item_and_context_drift(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    db = _CheckpointSession()
    before_check = _check()
    after_check = copy.deepcopy(before_check)
    before_items = [_item()]
    after_items = copy.deepcopy(before_items)
    before_context = _confirmed("context before")
    after_context = copy.deepcopy(before_context)
    if drift == "check":
        after_check.scope["content_excerpt"] = "concurrent edit"
    elif drift == "item":
        after_items[0].evidence_summary = "concurrent item edit"
    else:
        after_context.rendered_markdown = "context after"
        after_context.compiled.sections[0].content = "context after"

    repo = _repo((before_check, before_items), (after_check, after_items))
    _patch_facades(monkeypatch, before_context, after_context)
    result, items = await ConflictCheckAiReviewService(
        repo,
        llm_client=_Client(db),
    ).run_for_task(
        db,
        novel_id=str(before_check.novel_id),
        check_id=str(before_check.id),
        context_confirmation_id=str(before_check.ai_review_confirmation_id),
        task_id="task-1",
        llm_execution_snapshot={"profile_hash": "frozen"},
    )

    assert result.ai_review_status == "failed"
    assert "discarded stale result" in result.ai_review_error
    assert items == after_items
    repo.append_items.assert_not_awaited()
    assert db.commit_count == 1
    assert db.expire_all_count == 1


async def test_superseded_task_cannot_overwrite_newer_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    before = _check(owner="task-1")
    newer = _check(owner="task-2", status="done")
    newer.ai_review_model = "newer-model"
    repo = _repo((before, [_item()]), (newer, [_item(evidence="newer success")]))
    _patch_facades(monkeypatch, _confirmed("same"), _confirmed("same"))

    with pytest.raises(ValidationError, match="superseded"):
        await ConflictCheckAiReviewService(
            repo,
            llm_client=_Client(db),
        ).run_for_task(
            db,
            novel_id=str(before.novel_id),
            check_id=str(before.id),
            context_confirmation_id=str(before.ai_review_confirmation_id),
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
            allow_unowned_legacy=True,
        )

    assert newer.ai_review_status == "done"
    assert newer.ai_review_model == "newer-model"
    repo.update_loaded_ai_review.assert_not_awaited()
    repo.append_items.assert_not_awaited()


async def test_cancelled_task_cannot_overwrite_newer_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    before = _check(owner="task-1")
    newer = _check(owner="task-2", status="done")
    newer.ai_review_model = "newer-model"
    repo = _repo((before, [_item()]), (newer, [_item(evidence="newer success")]))
    _patch_facades(monkeypatch, _confirmed("same"))

    with pytest.raises(asyncio.CancelledError):
        await ConflictCheckAiReviewService(
            repo,
            llm_client=_Client(db, asyncio.CancelledError()),
        ).run_for_task(
            db,
            novel_id=str(before.novel_id),
            check_id=str(before.id),
            context_confirmation_id=str(before.ai_review_confirmation_id),
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert newer.ai_review_status == "done"
    assert newer.ai_review_model == "newer-model"
    repo.update_loaded_ai_review.assert_not_awaited()
    assert db.rollback_count == 1


async def test_client_close_error_cannot_overwrite_newer_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.project import facade as project_facade

    db = _CheckpointSession()
    before = _check(owner="task-1")
    newer = _check(owner="task-2", status="done")
    newer.ai_review_model = "newer-model"
    repo = _repo((before, [_item()]), (newer, [_item(evidence="newer success")]))
    _patch_facades(monkeypatch, _confirmed("same"))

    class _ClosingClient(_Client):
        async def close(self) -> None:
            raise RuntimeError("provider close failed")

    client = _ClosingClient(db)
    monkeypatch.setattr(
        project_facade,
        "restore_project_llm_execution_settings",
        mock.AsyncMock(return_value={"llm": {"model": "task-model"}}),
    )
    monkeypatch.setattr(
        project_facade,
        "create_project_snapshot_llm_client",
        mock.MagicMock(return_value=client),
    )

    with pytest.raises(ValidationError, match="superseded"):
        await ConflictCheckAiReviewService(repo).run_for_task(
            db,
            novel_id=str(before.novel_id),
            check_id=str(before.id),
            context_confirmation_id=str(before.ai_review_confirmation_id),
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert newer.ai_review_status == "done"
    assert newer.ai_review_model == "newer-model"
    repo.update_loaded_ai_review.assert_not_awaited()


async def test_legacy_retry_cannot_claim_ownerless_terminal_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    newer = _check(owner=None, status="done")
    repo = _repo((newer, [_item(evidence="newer sync success")]))
    _patch_facades(monkeypatch, _confirmed("same"))

    with pytest.raises(ValidationError, match="superseded"):
        await ConflictCheckAiReviewService(
            repo,
            llm_client=_Client(db),
        ).run_for_task(
            db,
            novel_id=str(newer.novel_id),
            check_id=str(newer.id),
            context_confirmation_id=str(newer.ai_review_confirmation_id),
            task_id="legacy-task",
            llm_execution_snapshot={"profile_hash": "frozen"},
            allow_unowned_legacy=True,
        )

    repo.update_loaded_ai_review.assert_not_awaited()
    assert db.commit_count == 0


def test_task_source_fingerprint_ignores_latency_but_tracks_evidence_sources() -> None:
    check = _check()
    items = [_item()]
    before = _confirmed("same", source_id="source-1")
    latency_only = copy.deepcopy(before)
    latency_only.compiled.sections[0].retrieval_metadata["latency_metadata"] = {
        "total_ms": 999.0
    }
    different_source = _confirmed("same", source_id="source-2")

    fingerprint = _task_source_fingerprint(before, check, items)
    assert _task_source_fingerprint(latency_only, check, items) == fingerprint
    assert _task_source_fingerprint(different_source, check, items) != fingerprint


async def test_task_cancellation_converges_owned_review_to_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    before = _check()
    after = copy.deepcopy(before)
    repo = _repo((before, [_item()]), (after, [_item()]))
    _patch_facades(monkeypatch, _confirmed("same"))

    with pytest.raises(asyncio.CancelledError):
        await ConflictCheckAiReviewService(
            repo,
            llm_client=_Client(db, asyncio.CancelledError()),
        ).run_for_task(
            db,
            novel_id=str(before.novel_id),
            check_id=str(before.id),
            context_confirmation_id=str(before.ai_review_confirmation_id),
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert after.ai_review_status == "failed"
    assert after.ai_review_error == "Conflict review task was cancelled"
    assert db.commit_count == 2


async def test_project_delete_before_finalize_prevents_domain_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    check = _check()
    repo = _repo((check, [_item()]))
    guard = mock.AsyncMock(
        side_effect=[None, NotFoundError("Project was permanently deleted")]
    )
    _patch_facades(
        monkeypatch,
        _confirmed("same"),
        _confirmed("same"),
        project_guard=guard,
    )

    with pytest.raises(NotFoundError, match="permanently deleted"):
        await ConflictCheckAiReviewService(
            repo,
            llm_client=_Client(db),
        ).run_for_task(
            db,
            novel_id=str(check.novel_id),
            check_id=str(check.id),
            context_confirmation_id=str(check.ai_review_confirmation_id),
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    repo.update_loaded_ai_review.assert_not_awaited()
    repo.append_items.assert_not_awaited()


async def test_task_provider_error_is_redacted_in_log_and_persisted_state(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    db = _CheckpointSession()
    before = _check()
    after = copy.deepcopy(before)
    repo = _repo((before, [_item()]), (after, [_item()]))
    _patch_facades(monkeypatch, _confirmed("same"))
    secret = "sk-super-secret-token"

    with caplog.at_level(logging.WARNING):
        result, _items = await ConflictCheckAiReviewService(
            repo,
            llm_client=_Client(
                db,
                RuntimeError(f"provider failed api_key={secret}"),
            ),
        ).run_for_task(
            db,
            novel_id=str(before.novel_id),
            check_id=str(before.id),
            context_confirmation_id=str(before.ai_review_confirmation_id),
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert result.ai_review_status == "failed"
    assert secret not in result.ai_review_error
    assert secret not in caplog.text


async def test_legacy_task_freezes_snapshot_before_review_checkpoint() -> None:
    from modules.writing.tasks import _require_llm_execution_snapshot

    db = _CheckpointSession()
    task = SimpleNamespace(meta={"novel_id": "novel-1"})
    snapshot = {"profile_hash": "frozen"}
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
        )

    assert result == snapshot
    assert legacy is True
    assert task.meta["llm_execution_snapshot"] == snapshot
    assert task.meta["_legacy_unowned_ai_review"] is True
    assert db.commit_count == 1
    assert db.expire_all_count == 1
    project_guard.assert_awaited_once_with(db, "novel-1")
    build_snapshot.assert_awaited_once_with(db, "novel-1")

    replay_snapshot, replay_legacy = await _require_llm_execution_snapshot(
        db,
        task,
        dict(task.meta),
        "novel-1",
    )
    assert replay_snapshot == snapshot
    assert replay_legacy is True


async def test_real_task_session_checkpoints_before_provider_wait(
    db_session,
    test_project_id: str,
) -> None:
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.evidence.facade import confirm_context

    confirmation = await confirm_context(
        db_session,
        novel_id=test_project_id,
        action="writing.conflict_check.ai_review",
        task="review task transaction boundary",
        scope="project",
        chapter_index=3,
    )
    task_id = uuid.uuid4()
    check = WritingConflictCheck(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(test_project_id),
        chapter_index=3,
        scene_id=None,
        draft_id=None,
        version_number=1,
        scope={"chapter_index": 3, "content_excerpt": "draft"},
        include_candidates=False,
        status="completed",
        summary_json={AI_REVIEW_TASK_OWNER_KEY: str(task_id)},
        ai_review_enabled=True,
        ai_review_status="running",
        ai_review_confirmation_id=uuid.UUID(confirmation.id),
    )
    lease_id = str(uuid.uuid4())
    task = AsyncTask(
        id=task_id,
        task_type="writing_conflict_ai_review",
        status="running",
        progress=0.1,
        meta={"novel_id": test_project_id},
        result={},
        lease_id=lease_id,
    )
    db_session.add_all([check, task])
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
        model_name = "task-model"

        async def generate_structured(self, _request, schema, **_kwargs):
            transaction_states.append(task_session.in_transaction())
            return schema(issues=[])

    task_session.set_task_commit_hook(_checkpoint)
    try:
        result, items = await ConflictCheckAiReviewService(
            repo=__import__(
                "modules.writing.repositories",
                fromlist=["WritingConflictCheckRepository"],
            ).WritingConflictCheckRepository(),
            llm_client=_RealClient(),
        ).run_for_task(
            task_session,
            novel_id=test_project_id,
            check_id=str(check.id),
            context_confirmation_id=confirmation.id,
            task_id=str(task_id),
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

        assert result.ai_review_status == "done"
        assert items == []
        assert transaction_states == [False]
        assert checkpoint_count == 1
    finally:
        await task_session.close()
