from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest

from infrastructure.llm.schemas import LLMCallResponse
from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.outline.ai_workflow_service import OutlineAIWorkflowService
from modules.outline.generation.context_builder import PlotStructureContext
from modules.outline.generator import PlotStructureGenerator

pytestmark = [pytest.mark.asyncio]


class _CheckpointSession:
    task_checkpoint_enabled = True

    def __init__(self) -> None:
        self._in_transaction = True
        self.commit_count = 0
        self.expire_all_count = 0
        self.flush_count = 0

    async def commit(self) -> None:
        self.commit_count += 1
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def expire_all(self) -> None:
        self.expire_all_count += 1

    async def flush(self) -> None:
        self.flush_count += 1


def _prepared_confirmation(
    markdown: str,
    *,
    source_id: str = "project-source-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        rendered_markdown=markdown,
        compile_options={"scope": "chapter", "budget_tokens": 4000},
        confirmation=SimpleNamespace(
            selected_asset_ids={"project": ["novel-1"]},
            excluded_asset_ids={},
            warnings=[],
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


def _patch_confirmation_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *markdown_versions: str,
) -> tuple[mock.AsyncMock, mock.AsyncMock, mock.AsyncMock]:
    versions = markdown_versions or ("confirmed markdown", "confirmed markdown")
    prepared = mock.AsyncMock(
        side_effect=[_prepared_confirmation(markdown) for markdown in versions]
    )
    attached = mock.AsyncMock()
    project_guard = mock.AsyncMock()
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.prepare_confirmed_ai_action",
        prepared,
    )
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.context_facade.attach_result_ref",
        attached,
    )
    monkeypatch.setattr(
        OutlineAIWorkflowService,
        "_require_active_project",
        project_guard,
    )
    return prepared, attached, project_guard


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        (
            "analyze_for_task",
            {
                "confirmation_id": "confirmation-1",
                "task_id": "task-1",
                "llm_execution_snapshot": {"profile_hash": "frozen"},
            },
        ),
        (
            "generate_for_task",
            {
                "confirmation_id": "confirmation-1",
                "task_id": "task-1",
                "start_chapter": 1,
                "end_chapter": 3,
                "llm_execution_snapshot": {"profile_hash": "frozen"},
            },
        ),
        (
            "extract_chapter_scenes_for_task",
            {
                "confirmation_id": "confirmation-1",
                "task_id": "task-1",
                "chapter_index": 1,
                "llm_execution_snapshot": {"profile_hash": "frozen"},
            },
        ),
        (
            "generate_legacy_preview_for_task",
            {
                "start_chapter": 1,
                "end_chapter": 3,
                "llm_execution_snapshot": {"profile_hash": "frozen"},
            },
        ),
    ],
)
async def test_task_only_workflows_reject_ordinary_sessions(
    method_name: str,
    kwargs: dict,
) -> None:
    db = SimpleNamespace(task_checkpoint_enabled=False)
    service = OutlineAIWorkflowService(llm_client=mock.MagicMock())

    with pytest.raises(RuntimeError, match="fenced TaskWorker handler session"):
        await getattr(service, method_name)(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            **kwargs,
        )


async def test_analyze_task_restores_frozen_profile_and_waits_without_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _prepared, attached, project_guard = _patch_confirmation_dependencies(
        monkeypatch,
        "confirmed markdown",
        "confirmed markdown",
    )
    events: list[str] = []

    class _Client:
        model_name = "frozen-model"
        close = mock.AsyncMock()

        async def generate(self, _request):
            events.append("llm")
            assert db.in_transaction() is False
            return LLMCallResponse(content="analysis", model=self.model_name)

    client = _Client()

    async def _restore(_db, novel_id, snapshot):
        events.append("restore")
        assert db.in_transaction() is True
        assert novel_id.endswith("1111")
        assert snapshot == {"profile_hash": "frozen"}
        return {"llm": {"model": "frozen-model"}}

    def _create(settings, *, novel_id):
        events.append("create")
        assert settings["llm"]["model"] == "frozen-model"
        assert novel_id.endswith("1111")
        return client

    with (
        mock.patch(
            "modules.project.facade.restore_project_llm_execution_settings",
            side_effect=_restore,
            autospec=True,
        ) as restore_snapshot,
        mock.patch(
            "modules.project.facade.create_project_snapshot_llm_client",
            side_effect=_create,
            autospec=True,
        ) as create_client,
    ):
        result = await OutlineAIWorkflowService().analyze_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            confirmation_id="confirmation-1",
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert result == {"analysis": "analysis"}
    assert events == ["restore", "create", "llm"]
    assert db.commit_count == 1
    assert db.expire_all_count == 1
    assert db.flush_count == 1
    assert project_guard.await_count == 2
    restore_snapshot.assert_awaited_once()
    create_client.assert_called_once()
    client.close.assert_awaited_once()
    attached.assert_awaited_once_with(
        db,
        confirmation_id="confirmation-1",
        result_type="outline_analysis",
        result_id="task-1",
        status="done",
    )


async def test_real_task_handler_session_checkpoints_before_provider_wait(
    db_session,
    sample_novel_id: str,
) -> None:
    import uuid

    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.context.facade import confirm_context, require_confirmation

    confirmation = await confirm_context(
        db_session,
        novel_id=sample_novel_id,
        action="outline.analyze",
        task="验证真实 task session transaction boundary",
        scope="project",
    )
    lease_id = str(uuid.uuid4())
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="outline_analyze",
        status="running",
        progress=0.25,
        meta={"novel_id": sample_novel_id},
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

    class _Client:
        model_name = "test-model"

        async def generate(self, _request):
            transaction_states.append(task_session.in_transaction())
            return LLMCallResponse(content="analysis")

    task_session.set_task_commit_hook(_checkpoint)
    try:
        result = await OutlineAIWorkflowService(
            llm_client=_Client(),
        ).analyze_for_task(
            task_session,
            novel_id=sample_novel_id,
            confirmation_id=confirmation.id,
            task_id=str(task.id),
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

        tracked = await require_confirmation(
            task_session,
            novel_id=sample_novel_id,
            action="outline.analyze",
            confirmation_id=confirmation.id,
        )
        assert result == {"analysis": "analysis"}
        assert transaction_states == [False]
        assert checkpoint_count == 1
        checkpointed_task = await task_session.get(AsyncTask, task.id)
        assert checkpointed_task is not None
        assert checkpointed_task.lease_id == lease_id
        assert checkpointed_task.progress == 0.25
        assert checkpointed_task.heartbeat_at is not None
        assert {
            "type": "outline_analysis",
            "id": str(task.id),
        } in tracked.result_refs
    finally:
        await task_session.close()


async def test_scene_extract_task_waits_without_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _patch_confirmation_dependencies(
        monkeypatch,
        "confirmed markdown",
        "confirmed markdown",
    )
    transaction_states: list[bool] = []

    class _Client:
        model_name = "test-model"

        async def generate_structured(self, _request, schema, **_kwargs):
            transaction_states.append(db.in_transaction())
            return schema(scenes=[{"title": "Scene A", "chapter_ids": []}])

    result = await OutlineAIWorkflowService(
        llm_client=_Client(),
    ).extract_chapter_scenes_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        confirmation_id="confirmation-1",
        task_id="task-1",
        chapter_index=7,
        llm_execution_snapshot={"profile_hash": "frozen"},
    )

    assert transaction_states == [False]
    assert db.commit_count == 1
    assert db.expire_all_count == 1
    assert result["total_scenes"] == 1
    assert result["draft_scenes"][0]["chapter_ids"] == ["7"]


async def test_generate_tasks_wait_without_transaction_and_revalidate_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _patch_confirmation_dependencies(
        monkeypatch,
        "confirmed markdown",
        "confirmed markdown",
    )
    generator_plan = object()
    transaction_states: list[bool] = []
    generator = SimpleNamespace(
        prepare_task_preview=mock.AsyncMock(return_value=generator_plan),
        require_task_preview_fresh=mock.AsyncMock(),
    )

    async def _execute(_plan, *, llm_client):
        assert llm_client.model_name == "test-model"
        transaction_states.append(db.in_transaction())
        return {
            "total_threads": 1,
            "total_arcs": 0,
            "total_scenes": 0,
            "draft_structure": {"threads": [{"name": "主线"}]},
            "requires_apply": True,
        }

    generator.execute_task_preview = mock.AsyncMock(side_effect=_execute)
    monkeypatch.setattr(
        "modules.outline.ai_workflow_service.PlotStructureGenerator",
        lambda: generator,
    )
    client = SimpleNamespace(model_name="test-model")

    result = await OutlineAIWorkflowService(
        llm_client=client,
    ).generate_for_task(
        db,
        novel_id="11111111-1111-1111-1111-111111111111",
        confirmation_id="confirmation-1",
        task_id="task-1",
        start_chapter=1,
        end_chapter=3,
        llm_execution_snapshot={"profile_hash": "frozen"},
    )

    assert transaction_states == [False]
    assert db.commit_count == 1
    assert result["source_task_id"] == "task-1"
    assert db.expire_all_count == 1
    generator.require_task_preview_fresh.assert_awaited_once_with(db, generator_plan)
    prepared_settings = generator.prepare_task_preview.await_args.kwargs[
        "project_settings_snapshot"
    ]
    assert prepared_settings["_deep_import_settings_frozen"] is True

    legacy_db = _CheckpointSession()
    legacy_result = await OutlineAIWorkflowService(
        llm_client=client,
    ).generate_legacy_preview_for_task(
        legacy_db,
        novel_id="11111111-1111-1111-1111-111111111111",
        start_chapter=1,
        end_chapter=3,
        llm_execution_snapshot={"profile_hash": "frozen"},
    )

    assert legacy_result["total_threads"] == 1
    assert transaction_states == [False, False]
    assert legacy_db.commit_count == 1
    assert legacy_db.expire_all_count == 1
    assert generator.require_task_preview_fresh.await_count == 2


async def test_task_generator_budget_uses_frozen_snapshot_not_current_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE3_STRUCTURE_MAX_TOKENS", "199999")
    settings = OutlineAIWorkflowService._frozen_generator_settings(
        {
            "profile_hash": "frozen",
            "deep_import": {"phase3": {"structure_max_tokens": 12345}},
        }
    )

    assert PlotStructureGenerator._structure_max_tokens(settings) == 12345


async def test_confirmed_task_rejects_context_drift_before_attaching_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _prepared, attached, _guard = _patch_confirmation_dependencies(
        monkeypatch,
        "context before LLM",
        "context after concurrent edit",
    )

    class _Client:
        model_name = "test-model"

        async def generate(self, _request):
            assert db.in_transaction() is False
            return LLMCallResponse(content="stale analysis")

    with pytest.raises(ValueError, match="discarded stale result"):
        await OutlineAIWorkflowService(llm_client=_Client()).analyze_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            confirmation_id="confirmation-1",
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert db.commit_count == 1
    assert db.expire_all_count == 1
    attached.assert_not_awaited()


async def test_confirmed_task_rejects_equal_text_with_changed_evidence_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    prepared, attached, _guard = _patch_confirmation_dependencies(
        monkeypatch,
        "same rendered context",
        "same rendered context",
    )
    prepared.side_effect = [
        _prepared_confirmation("same rendered context", source_id="source-before"),
        _prepared_confirmation("same rendered context", source_id="source-after"),
    ]

    class _Client:
        model_name = "test-model"

        async def generate(self, _request):
            assert db.in_transaction() is False
            return LLMCallResponse(content="stale analysis")

    with pytest.raises(ValueError, match="discarded stale result"):
        await OutlineAIWorkflowService(llm_client=_Client()).analyze_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            confirmation_id="confirmation-1",
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    attached.assert_not_awaited()


async def test_confirmed_context_fingerprint_ignores_retrieval_latency() -> None:
    first = _prepared_confirmation("same", source_id="source-1").compiled
    second = _prepared_confirmation("same", source_id="source-1").compiled
    first.sections[0].retrieval_metadata["latency_metadata"] = {"total_ms": 1.0}
    second.sections[0].retrieval_metadata["latency_metadata"] = {"total_ms": 999.0}

    assert OutlineAIWorkflowService._compiled_context_fingerprint(
        first
    ) == OutlineAIWorkflowService._compiled_context_fingerprint(second)


@pytest.mark.parametrize("exception", [RuntimeError("provider failed")])
async def test_task_external_error_does_not_attach_partial_result(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
) -> None:
    db = _CheckpointSession()
    _prepared, attached, _guard = _patch_confirmation_dependencies(
        monkeypatch,
        "confirmed markdown",
    )

    class _Client:
        model_name = "test-model"

        async def generate(self, _request):
            assert db.in_transaction() is False
            raise exception

    with pytest.raises(RuntimeError, match="provider failed"):
        await OutlineAIWorkflowService(llm_client=_Client()).analyze_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            confirmation_id="confirmation-1",
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert db.commit_count == 1
    assert db.in_transaction() is False
    attached.assert_not_awaited()


async def test_task_cancellation_does_not_attach_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _CheckpointSession()
    _prepared, attached, _guard = _patch_confirmation_dependencies(
        monkeypatch,
        "confirmed markdown",
    )

    class _Client:
        model_name = "test-model"

        async def generate(self, _request):
            assert db.in_transaction() is False
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await OutlineAIWorkflowService(llm_client=_Client()).analyze_for_task(
            db,
            novel_id="11111111-1111-1111-1111-111111111111",
            confirmation_id="confirmation-1",
            task_id="task-1",
            llm_execution_snapshot={"profile_hash": "frozen"},
        )

    assert db.commit_count == 1
    assert db.in_transaction() is False
    attached.assert_not_awaited()


async def test_generator_task_plan_rejects_source_drift() -> None:
    context_builder = SimpleNamespace(
        build=mock.AsyncMock(
            side_effect=[
                PlotStructureContext(markdown="source before"),
                PlotStructureContext(markdown="source after"),
            ]
        )
    )
    generator = PlotStructureGenerator(
        context_builder=context_builder,
        llm_client=mock.MagicMock(),
        persister=mock.MagicMock(),
    )
    plan = await generator.prepare_task_preview(
        mock.AsyncMock(),
        novel_id="11111111-1111-1111-1111-111111111111",
        start_chapter=1,
        end_chapter=3,
    )

    with pytest.raises(ValueError, match="discarded stale preview"):
        await generator.require_task_preview_fresh(mock.AsyncMock(), plan)


async def test_legacy_task_freezes_missing_profile_before_workflow_checkpoint() -> None:
    from modules.outline.tasks import _require_llm_execution_snapshot

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
        result = await _require_llm_execution_snapshot(
            db,
            task,
            dict(task.meta),
            "novel-1",
        )

    assert result == snapshot
    assert task.meta["llm_execution_snapshot"] == snapshot
    assert db.commit_count == 1
    project_guard.assert_awaited_once_with(db, "novel-1")
    build_snapshot.assert_awaited_once_with(db, "novel-1")


async def test_task_confirmation_prepare_matches_legacy_compile_render(
    db_session,
    sample_novel_id: str,
) -> None:
    from modules.context.facade import (
        compile_from_confirmation,
        confirm_context,
        render_compiled_context,
    )

    confirmation = await confirm_context(
        db_session,
        novel_id=sample_novel_id,
        action="outline.analyze",
        task="验证 task-only context materialization",
        scope="project",
    )
    legacy_markdown = render_compiled_context(
        await compile_from_confirmation(
            db_session,
            novel_id=sample_novel_id,
            action="outline.analyze",
            confirmation_id=confirmation.id,
        )
    )

    plan = await OutlineAIWorkflowService._prepare_confirmed_task_prompt(
        db_session,
        novel_id=sample_novel_id,
        action="outline.analyze",
        confirmation_id=confirmation.id,
    )

    assert plan.rendered_markdown == legacy_markdown


@pytest.mark.parametrize(
    ("handler_name", "service_method", "meta", "expected_kwargs", "result"),
    [
        (
            "handle_outline_analyze",
            "analyze_for_task",
            {
                "novel_id": "11111111-1111-1111-1111-111111111111",
                "context_confirmation_id": "confirmation-1",
                "instruction": "分析节奏",
            },
            {"instruction": "分析节奏"},
            {"analysis": "ok"},
        ),
        (
            "handle_outline_generate",
            "generate_for_task",
            {
                "novel_id": "11111111-1111-1111-1111-111111111111",
                "context_confirmation_id": "confirmation-1",
                "start_chapter": 2,
                "end_chapter": 4,
            },
            {"start_chapter": 2, "end_chapter": 4},
            {"total_threads": 1, "total_arcs": 0},
        ),
        (
            "handle_outline_chapter_scenes_extract",
            "extract_chapter_scenes_for_task",
            {
                "novel_id": "11111111-1111-1111-1111-111111111111",
                "context_confirmation_id": "confirmation-1",
                "chapter_index": 7,
                "instruction": "提取 Scene",
            },
            {"chapter_index": 7, "instruction": "提取 Scene"},
            {"total_scenes": 1},
        ),
    ],
)
async def test_outline_handlers_delegate_only_to_task_workflow_seams(
    handler_name: str,
    service_method: str,
    meta: dict,
    expected_kwargs: dict,
    result: dict,
) -> None:
    from modules.outline import tasks as outline_tasks

    snapshot = {"profile_hash": "frozen"}
    task = SimpleNamespace(
        id="task-1",
        meta={**meta, "llm_execution_snapshot": snapshot},
        update_progress=mock.MagicMock(),
    )
    db = SimpleNamespace(task_checkpoint_enabled=True)
    with mock.patch(
        "modules.outline.ai_workflow_service.OutlineAIWorkflowService",
        autospec=True,
    ) as service_cls:
        service = service_cls.return_value
        method = getattr(service, service_method)
        method.return_value = result

        actual = await getattr(outline_tasks, handler_name)(db, task)

    assert actual == result
    method.assert_awaited_once_with(
        db,
        novel_id=meta["novel_id"],
        confirmation_id="confirmation-1",
        task_id="task-1",
        llm_execution_snapshot=snapshot,
        progress_callback=task.update_progress,
        **expected_kwargs,
    )


async def test_task_only_methods_are_not_cross_module_facade_exports() -> None:
    from modules.outline import facade

    assert not {
        "analyze_for_task",
        "generate_for_task",
        "extract_chapter_scenes_for_task",
        "generate_legacy_preview_for_task",
    }.intersection(facade.__all__)
