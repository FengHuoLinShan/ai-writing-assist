from __future__ import annotations

import asyncio
import copy
import hashlib
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import select

from core.errors import NotFoundError
from infrastructure.llm.health import LLMHealthResult
from modules.imports.adoption_policy import build_authorization_snapshot
from modules.imports.llm_schemas import SceneChunk
from modules.imports.orchestrator import (
    SCENE_STAGE_TASK_PREPARE_KEY,
    SCENE_STAGE_TASK_PREPARE_VERSION,
    DeepImportOrchestrator,
    DeepImportWorkflowFailedError,
    SceneStageInputDriftError,
)
from modules.imports.phase1a_context import (
    PHASE1A_CONTEXT_CONTRACT_VERSION,
    stable_context_hash,
)
from modules.imports.scene_commit import SceneCommitResult
from modules.imports.scene_enrichment import Phase1bEnrichmentResult
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_fusion_phase1c import Phase1cFusionResult
from modules.imports.scene_slicing import SceneSliceCandidate, SceneSlicingResult
from modules.imports.workflow import DeepImportWorkflow
from modules.project.contracts import ProjectLLMConfigurationError

pytestmark = pytest.mark.asyncio

NOVEL_ID = "11111111-1111-1111-1111-111111111111"


def _snapshot(novel_id: str = NOVEL_ID) -> dict:
    return {
        "version": "test-v1",
        "novel_id": novel_id,
        "profile": {
            "provider": "openai_compatible",
            "model": "frozen-model",
            "base_url": "https://example.invalid/v1",
            "extra": {"reasoning": "off"},
        },
        "profile_hash": "frozen-profile",
    }


def _authorization(novel_id: str = NOVEL_ID) -> dict:
    return build_authorization_snapshot(
        novel_id=novel_id,
        start_chapter=1,
        end_chapter=1,
        adoption_policy="user_authorized_pipeline",
        authorization_confirmed=True,
        stage="scenes",
    )


class _Task:
    def __init__(self, *, include_snapshot: bool = True) -> None:
        self.id = uuid.uuid4()
        self.task_type = "scene_auto_extraction"
        self.status = "running"
        self.attempt = 1
        self.lease_id = str(uuid.uuid4())
        self.progress = 0.0
        self.meta = {
            "novel_id": NOVEL_ID,
            "start_chapter": 1,
            "end_chapter": 1,
            "stage": "scenes",
            "high_quality": False,
            "replace_existing": False,
            "authorization_snapshot": _authorization(),
        }
        if include_snapshot:
            self.meta["llm_execution_snapshot"] = _snapshot()
        self.result: dict = {}

    def update_progress(self, value: float) -> None:
        self.progress = value


class _CheckpointSession:
    task_checkpoint_enabled = True

    def __init__(
        self,
        task: _Task,
        *,
        current_task: _Task | None = None,
        lose_on_commit: int | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.task = task
        self.current_task = current_task or copy.deepcopy(task)
        self.lose_on_commit = lose_on_commit
        self.events = events if events is not None else []
        self._in_transaction = True
        self.commit_count = 0
        self.rollback_count = 0
        self.expire_all_count = 0
        self.pending_assets: list[str] = []
        self.durable_assets: list[str] = []

    async def commit(self) -> None:
        self.commit_count += 1
        self.events.append(f"commit:{self.commit_count}")
        self._in_transaction = False
        if self.commit_count == self.lose_on_commit:
            self.pending_assets.clear()
            raise asyncio.CancelledError
        self.current_task.meta = copy.deepcopy(self.task.meta)
        self.current_task.result = copy.deepcopy(self.task.result)
        self.current_task.progress = self.task.progress
        self.current_task.status = self.task.status
        self.current_task.attempt = self.task.attempt
        self.current_task.lease_id = self.task.lease_id
        self.durable_assets.extend(self.pending_assets)
        self.pending_assets.clear()

    def expire_all(self) -> None:
        self.expire_all_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.pending_assets.clear()
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def start_transaction(self) -> None:
        self._in_transaction = True

    async def scalar(self, _statement):
        return self.current_task

    async def add(self, _value) -> None:
        """Coroutine-shaped add makes the RAG enqueue helper skip fake sessions."""


class _RecordingWorkflow(DeepImportWorkflow):
    def __init__(
        self,
        db,
        *,
        events: list[str],
        mutate_during_provider: Callable[[], None] | None = None,
        fail_phase1a: bool = False,
        real_commit: bool = False,
        commit_result: SceneCommitResult | None = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.events = events
        self.mutate_during_provider = mutate_during_provider
        self.fail_phase1a = fail_phase1a
        self.real_commit = real_commit
        self.commit_result = commit_result
        self.provider_calls = 0

    @staticmethod
    def _is_llm_health_required() -> bool:
        return True

    async def _check_llm_health(self, db, novel_id, project_settings=None):
        del novel_id, project_settings
        assert db is self.db
        assert db.in_transaction() is False
        self.events.append("health")
        return LLMHealthResult(ok=True, model="frozen-model")

    async def _run_phase1a_scene_slicing(
        self,
        db,
        novel_id,
        start_chapter,
        end_chapter,
        phase0_plan,
        *,
        on_batch_progress=None,
    ) -> SceneSlicingResult:
        del novel_id, start_chapter, end_chapter, phase0_plan
        assert db is self.db
        assert db.in_transaction() is False
        self.provider_calls += 1
        self.events.append("phase1a")
        if self.fail_phase1a:
            raise RuntimeError("provider interrupted after prepare")
        if on_batch_progress is not None:
            await on_batch_progress(1, 1, "window-1")
        if self.mutate_during_provider is not None:
            self.mutate_during_provider()
            self.mutate_during_provider = None
        return SceneSlicingResult(
            candidates=[
                SceneSliceCandidate(
                    candidate_id="scene-candidate-1",
                    source_window_id="window-1",
                    source_window_index=1,
                    title="Scene one",
                    goal="Advance the chapter",
                    start_chapter=1,
                    end_chapter=1,
                    boundary_status="complete",
                    source_chapter_indices=[1],
                    scene_chunks=[SceneChunk(chapter_index=1, start_paragraph=0)],
                )
            ],
            quality_stats={
                "total_batches": 1,
                "completed_batches": 1,
                "success": 1,
                "failed": 0,
                "fallback_count": 0,
                "scene_count": 1,
            },
        )

    async def _run_phase1b_enrichment(
        self,
        db,
        novel_id,
        phase1a_candidates,
        *,
        start_chapter,
        end_chapter,
        chapters,
        on_batch_progress=None,
    ) -> Phase1bEnrichmentResult:
        del novel_id, phase1a_candidates, start_chapter, end_chapter, chapters
        assert db is self.db
        assert db.in_transaction() is False
        self.provider_calls += 1
        self.events.append("phase1b")
        if on_batch_progress is not None:
            await on_batch_progress(1, 1, "scene-candidate-1")
        return Phase1bEnrichmentResult(
            candidates=[_final_candidate()],
            quality_stats={
                "total_windows": 1,
                "completed_windows": 1,
                "total_scenes": 1,
                "completed": 1,
                "failed": 0,
                "fallback_count": 0,
            },
        )

    async def _run_phase1c_scene_fusion(
        self,
        db,
        novel_id,
        candidates,
        *,
        chapters,
        project_profile=None,
        on_pair_progress=None,
    ) -> Phase1cFusionResult:
        del novel_id, chapters, project_profile
        assert db is self.db
        assert db.in_transaction() is False
        self.provider_calls += 1
        self.events.append("phase1c")
        if on_pair_progress is not None:
            await on_pair_progress(1, 1, "pair-1")
        return Phase1cFusionResult(
            candidates=list(candidates),
            quality_stats={"completed_pairs": 1},
        )

    async def _commit_fused_scenes(
        self,
        db,
        novel_id,
        candidates,
        *,
        workflow_id,
        fusion_suggestions=None,
        start_chapter=None,
        end_chapter=None,
        replace_existing=False,
    ) -> SceneCommitResult:
        assert db is self.db
        assert db.in_transaction() is True
        self.events.append("scene_write")
        if self.real_commit:
            return await super()._commit_fused_scenes(
                db,
                novel_id,
                candidates,
                workflow_id=workflow_id,
                fusion_suggestions=fusion_suggestions,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                replace_existing=replace_existing,
            )
        db.pending_assets.append("scene-1")
        if self.commit_result is not None:
            return self.commit_result
        return SceneCommitResult(
            created_count=1,
            created_scene_ids=["scene-1"],
            active_scene_changed=True,
        )


def _final_candidate() -> FinalSceneCandidate:
    return FinalSceneCandidate(
        candidate_id="final-scene-1",
        phase="phase1b_enrichment",
        title="Scene one",
        goal="Advance the chapter",
        scene_chunks=[SceneChunk(chapter_index=1, start_paragraph=0)],
        source_candidate_ids=["scene-candidate-1"],
        source_chapter_indices=[1],
        operation="kept",
        confidence=0.95,
        boundary_status="complete",
        needs_review=False,
    )


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        active=True,
        snapshot_valid=True,
        phase1a_context_marker="context-v1",
        context=SimpleNamespace(
            title="Frozen title",
            genre="mystery",
            tone="restrained",
        ),
        chapters=[
            {
                "chapter_index": 1,
                "title": "Chapter one",
                "content": "Frozen chapter source",
                "source_draft_id": "draft-1",
                "content_hash": "deliberately-not-trusted",
            }
        ],
    )


class _FrozenContextBuilder:
    def __init__(self, state: SimpleNamespace) -> None:
        self.state = state

    async def compile(self, db, *, novel_id, plan, boundary_chapters=None):
        del db, boundary_chapters
        assert novel_id == NOVEL_ID
        frozen = plan.model_copy(deep=True)
        windows = []
        for window in frozen.windows:
            reference = {
                "contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
                "window_id": window.window_id,
                "marker": self.state.phase1a_context_marker,
            }
            reference["content_hash"] = stable_context_hash(reference)
            window.left_boundary_context = ""
            window.reference_context = reference
            windows.append(
                {
                    "window_id": window.window_id,
                    "left_boundary_context": "",
                    "reference_context": reference,
                }
            )
        manifest = {
            "contract_version": PHASE1A_CONTEXT_CONTRACT_VERSION,
            "limits": {
                "left_boundary_chars": 2000,
                "characters": 6,
                "world_objects": 16,
            },
            "windows": windows,
        }
        manifest["fingerprint"] = stable_context_hash(manifest)
        frozen.phase1a_context = manifest
        return frozen


def _patch_inputs(
    monkeypatch: pytest.MonkeyPatch,
    db: _CheckpointSession,
    state: SimpleNamespace,
    events: list[str],
) -> tuple[mock.AsyncMock, mock.AsyncMock]:
    from infrastructure.tasks import facade as task_facade
    from modules.imports import chapter_loader
    from modules.project import facade as project_facade
    from modules.writing import facade as writing_facade

    async def _require_active(_db, novel_id):
        assert _db is db
        assert novel_id == NOVEL_ID
        db.start_transaction()
        events.append("project_lock")
        if not state.active:
            raise NotFoundError("project deleted")

    async def _get_context(_db, novel_id):
        assert _db is db
        assert novel_id == NOVEL_ID
        return state.context if state.active else None

    load = mock.AsyncMock(
        side_effect=lambda *_args, **_kwargs: copy.deepcopy(state.chapters)
    )

    async def _lock_chapters(_db, novel_id, chapter_indices):
        assert _db is db
        assert db.in_transaction() is True
        assert novel_id == NOVEL_ID
        assert chapter_indices == [1]
        events.append("writing_lock")

    lock = mock.AsyncMock(side_effect=_lock_chapters)
    monkeypatch.setattr(project_facade, "require_active_project", _require_active)
    monkeypatch.setattr(project_facade, "get_project_context", _get_context)
    monkeypatch.setattr(
        task_facade,
        "require_running_task_attempt",
        mock.AsyncMock(),
    )
    monkeypatch.setattr(chapter_loader, "load_chapter_range", load)
    monkeypatch.setattr(
        writing_facade,
        "lock_chapter_versions_for_revalidation",
        lock,
    )
    return load, lock


def _orchestrator(
    workflow: _RecordingWorkflow,
    state: SimpleNamespace,
    events: list[str],
    *,
    builder: mock.AsyncMock | None = None,
    restorer: mock.AsyncMock | None = None,
) -> tuple[DeepImportOrchestrator, mock.AsyncMock, mock.AsyncMock]:
    build = builder or mock.AsyncMock(return_value=_snapshot())

    async def _restore(_db, novel_id, snapshot):
        assert _db is workflow.db
        assert workflow.db.in_transaction() is True
        assert novel_id == NOVEL_ID
        assert snapshot == _snapshot()
        events.append("restore_snapshot")
        if not state.snapshot_valid:
            raise ProjectLLMConfigurationError(
                "project LLM endpoint or extra settings changed"
            )
        return {"llm": {"model": "frozen-model"}, "deep_import": {}}

    restore = restorer or mock.AsyncMock(side_effect=_restore)
    return (
        DeepImportOrchestrator(
            workflow=workflow,
            snapshot_builder=build,
            snapshot_restorer=restore,
            phase1a_context_builder=_FrozenContextBuilder(state),
        ),
        build,
        restore,
    )


@pytest.mark.parametrize(
    ("legacy", "high_quality"),
    [(False, False), (True, True)],
    ids=["submitted-snapshot", "legacy-high-quality"],
)
async def test_scene_task_checkpoints_prepare_then_commits_assets_atomically(
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
    high_quality: bool,
) -> None:
    events: list[str] = []
    state = _state()
    task = _Task(include_snapshot=not legacy)
    task.meta["high_quality"] = high_quality
    db = _CheckpointSession(task, events=events)
    load, lock = _patch_inputs(monkeypatch, db, state, events)
    workflow = _RecordingWorkflow(db, events=events)
    orchestrator, builder, restorer = _orchestrator(workflow, state, events)

    result = await orchestrator.run_stage_task(db, task, stage="scenes")

    assert result["phase"] == "done"
    assert db.commit_count == 2
    assert db.expire_all_count == 2
    assert db.durable_assets == ["scene-1"]
    assert db.pending_assets == []
    assert db.current_task.result["phase"] == "done"
    preparation = task.meta[SCENE_STAGE_TASK_PREPARE_KEY]
    assert preparation["version"] == SCENE_STAGE_TASK_PREPARE_VERSION
    assert preparation["phase1a_context_contract_version"] == (
        PHASE1A_CONTEXT_CONTRACT_VERSION
    )
    assert (
        preparation["phase1a_context_fingerprint"]
        == (preparation["phase1a_context"]["fingerprint"])
    )
    assert preparation["source_vector"] == [
        {
            "chapter_index": 1,
            "source_draft_id": "draft-1",
            "content_hash": hashlib.sha256(b"Frozen chapter source").hexdigest(),
        }
    ]
    assert (
        task.result["checkpoints"][SCENE_STAGE_TASK_PREPARE_KEY]["input_fingerprint"]
        == preparation["input_fingerprint"]
    )
    assert events.index("commit:1") < events.index("health")
    assert events.index("writing_lock") < events.index("scene_write")
    assert load.await_count == 2
    lock.assert_awaited_once()
    assert restorer.await_count == 2
    assert builder.await_count == int(legacy)
    assert workflow.provider_calls == (3 if high_quality else 2)
    assert ("phase1c" in events) is high_quality


async def test_scene_task_retry_reuses_legacy_snapshot_and_prepare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _state()
    first_task = _Task(include_snapshot=False)
    first_db = _CheckpointSession(first_task, events=events)
    _patch_inputs(monkeypatch, first_db, state, events)
    builder = mock.AsyncMock(return_value=_snapshot())
    first_workflow = _RecordingWorkflow(first_db, events=events, fail_phase1a=True)
    first_orchestrator, builder, _ = _orchestrator(
        first_workflow,
        state,
        events,
        builder=builder,
    )

    with pytest.raises(RuntimeError, match="provider interrupted"):
        await first_orchestrator.run_stage_task(first_db, first_task, stage="scenes")

    first_prepare = copy.deepcopy(
        first_db.current_task.meta[SCENE_STAGE_TASK_PREPARE_KEY]
    )
    assert first_db.commit_count == 1
    assert first_db.durable_assets == []

    current_task = first_db.current_task
    current_task.status = "running"
    current_task.attempt += 1
    current_task.lease_id = str(uuid.uuid4())
    retry_task = copy.deepcopy(current_task)
    retry_db = _CheckpointSession(
        retry_task,
        current_task=current_task,
        events=events,
    )
    _patch_inputs(monkeypatch, retry_db, state, events)
    retry_workflow = _RecordingWorkflow(retry_db, events=events)
    retry_orchestrator, _, _ = _orchestrator(
        retry_workflow,
        state,
        events,
        builder=builder,
    )

    result = await retry_orchestrator.run_stage_task(
        retry_db,
        retry_task,
        stage="scenes",
    )

    assert result["phase"] == "done"
    assert retry_task.meta[SCENE_STAGE_TASK_PREPARE_KEY] == first_prepare
    assert builder.await_count == 1
    assert retry_db.durable_assets == ["scene-1"]

    replay_task = copy.deepcopy(retry_db.current_task)
    replay_db = _CheckpointSession(
        replay_task,
        current_task=retry_db.current_task,
        events=events,
    )
    replay_workflow = _RecordingWorkflow(replay_db, events=events)
    replay_orchestrator, _, _ = _orchestrator(
        replay_workflow,
        state,
        events,
        builder=builder,
    )

    replay = await replay_orchestrator.run_stage_task(
        replay_db,
        replay_task,
        stage="scenes",
    )

    assert replay["phase"] == "done"
    assert replay_workflow.provider_calls == 0
    assert replay_db.commit_count == 0


async def test_unfinished_v1_scene_prepare_fails_closed_with_resubmit_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _state()
    task = _Task()
    task.meta[SCENE_STAGE_TASK_PREPARE_KEY] = {
        "version": "scene-stage-prepare-v1",
        "input_fingerprint": "legacy",
    }
    db = _CheckpointSession(task, events=events)
    _patch_inputs(monkeypatch, db, state, events)
    workflow = _RecordingWorkflow(db, events=events)
    orchestrator, _, _ = _orchestrator(workflow, state, events)

    with pytest.raises(SceneStageInputDriftError, match="submit a new"):
        await orchestrator.run_stage_task(db, task, stage="scenes")

    assert workflow.provider_calls == 0
    assert db.commit_count == 0


async def test_completed_v1_scene_prepare_remains_readable() -> None:
    events: list[str] = []
    state = _state()
    task = _Task()
    task.meta[SCENE_STAGE_TASK_PREPARE_KEY] = {
        "version": "scene-stage-prepare-v1",
        "input_fingerprint": "legacy",
    }
    task.result = {"phase": "done", "message": "legacy result"}
    db = _CheckpointSession(task, events=events)
    workflow = _RecordingWorkflow(db, events=events)
    orchestrator, _, _ = _orchestrator(workflow, state, events)

    result = await orchestrator.run_stage_task(db, task, stage="scenes")

    assert result["phase"] == "done"
    assert workflow.provider_calls == 0
    assert db.commit_count == 0


@pytest.mark.parametrize(
    ("drift", "expected_error"),
    [
        ("source", SceneStageInputDriftError),
        ("project_profile", SceneStageInputDriftError),
        ("project_deleted", NotFoundError),
        ("llm_profile", ProjectLLMConfigurationError),
        ("phase1a_context", SceneStageInputDriftError),
    ],
)
async def test_scene_task_discards_provider_result_on_business_input_drift(
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    expected_error: type[Exception],
) -> None:
    events: list[str] = []
    state = _state()
    task = _Task()
    db = _CheckpointSession(task, events=events)
    _patch_inputs(monkeypatch, db, state, events)

    def _mutate() -> None:
        if drift == "source":
            state.chapters[0]["content"] = "Concurrent source edit"
            state.chapters[0]["source_draft_id"] = "draft-2"
        elif drift == "project_profile":
            state.context.title = "Concurrent title edit"
        elif drift == "project_deleted":
            state.active = False
        elif drift == "phase1a_context":
            state.phase1a_context_marker = "context-v2"
        else:
            state.snapshot_valid = False

    workflow = _RecordingWorkflow(
        db,
        events=events,
        mutate_during_provider=_mutate,
    )
    orchestrator, _, _ = _orchestrator(workflow, state, events)

    with pytest.raises(expected_error):
        await orchestrator.run_stage_task(db, task, stage="scenes")

    assert db.commit_count == 1
    assert db.durable_assets == []
    assert db.pending_assets == []
    assert db.current_task.result["phase"] == "pending"


@pytest.mark.parametrize("fence_drift", ["lease", "task_novel"])
async def test_scene_task_dynamic_worker_fence_blocks_formal_scene_write(
    monkeypatch: pytest.MonkeyPatch,
    fence_drift: str,
) -> None:
    events: list[str] = []
    state = _state()
    task = _Task()
    db = _CheckpointSession(task, events=events)
    _patch_inputs(monkeypatch, db, state, events)

    def _mutate_fence() -> None:
        if fence_drift == "lease":
            db.current_task.lease_id = str(uuid.uuid4())
        else:
            db.current_task.meta = {
                **dict(db.current_task.meta),
                "novel_id": "22222222-2222-2222-2222-222222222222",
            }

    workflow = _RecordingWorkflow(
        db,
        events=events,
        mutate_during_provider=_mutate_fence,
    )
    orchestrator, _, _ = _orchestrator(workflow, state, events)

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.run_stage_task(db, task, stage="scenes")

    assert db.commit_count == 1
    assert db.durable_assets == []
    assert "scene_write" not in events


async def test_scene_task_final_checkpoint_rejection_rolls_back_scene_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _state()
    task = _Task()
    db = _CheckpointSession(task, lose_on_commit=2, events=events)
    _patch_inputs(monkeypatch, db, state, events)
    workflow = _RecordingWorkflow(db, events=events)
    orchestrator, _, _ = _orchestrator(workflow, state, events)

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.run_stage_task(db, task, stage="scenes")

    assert events[-2:] == ["scene_write", "commit:2"]
    assert db.durable_assets == []
    assert db.pending_assets == []
    assert db.current_task.result["phase"] == "pending"


async def test_scene_prepare_fingerprint_excludes_dynamic_attempt_and_lease() -> None:
    task = _Task()
    chapters = _state().chapters
    meta = dict(task.meta)
    first = DeepImportOrchestrator._build_scene_stage_preparation(  # noqa: SLF001
        task=task,
        meta=meta,
        novel_id=NOVEL_ID,
        start_chapter=1,
        end_chapter=1,
        high_quality=False,
        replace_existing=False,
        chapters=chapters,
        project_profile={"title": "Frozen", "genre": "", "tone": ""},
        llm_execution_snapshot=_snapshot(),
    )
    task.attempt += 1
    task.lease_id = str(uuid.uuid4())
    second = DeepImportOrchestrator._build_scene_stage_preparation(  # noqa: SLF001
        task=task,
        meta=meta,
        novel_id=NOVEL_ID,
        start_chapter=1,
        end_chapter=1,
        high_quality=False,
        replace_existing=False,
        chapters=chapters,
        project_profile={"title": "Frozen", "genre": "", "tone": ""},
        llm_execution_snapshot=_snapshot(),
    )

    assert first["input_fingerprint"] == second["input_fingerprint"]
    assert "attempt" not in first
    assert "lease_id" not in first


async def test_scene_prepare_fingerprint_includes_replace_existing() -> None:
    task = _Task()
    common = {
        "task": task,
        "meta": dict(task.meta),
        "novel_id": NOVEL_ID,
        "start_chapter": 1,
        "end_chapter": 1,
        "high_quality": False,
        "chapters": _state().chapters,
        "project_profile": {"title": "Frozen", "genre": "", "tone": ""},
        "llm_execution_snapshot": _snapshot(),
    }

    normal = DeepImportOrchestrator._build_scene_stage_preparation(  # noqa: SLF001
        **common,
        replace_existing=False,
    )
    replacement = DeepImportOrchestrator._build_scene_stage_preparation(  # noqa: SLF001
        **common,
        replace_existing=True,
    )

    assert normal["input_fingerprint"] != replacement["input_fingerprint"]
    assert replacement["replace_existing"] is True


async def test_failed_scene_commit_rolls_back_partial_replacement_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _state()
    task = _Task()
    task.meta["replace_existing"] = True
    db = _CheckpointSession(task, events=events)
    _patch_inputs(monkeypatch, db, state, events)
    workflow = _RecordingWorkflow(
        db,
        events=events,
        commit_result=SceneCommitResult(
            created_count=1,
            created_scene_ids=["partial-scene"],
            effective_scene_count=1,
            effective_coverage={
                "start_chapter": 1,
                "end_chapter": 1,
                "covered_chapters": [],
                "missing_chapters": [1],
                "coverage_complete": False,
            },
            active_scene_changed=True,
        ),
    )
    orchestrator, _, _ = _orchestrator(workflow, state, events)

    with pytest.raises(DeepImportWorkflowFailedError, match="Scene"):
        await orchestrator.run_stage_task(db, task, stage="scenes")

    assert db.commit_count == 1
    assert db.rollback_count >= 1
    assert db.durable_assets == []
    assert db.pending_assets == []


async def _create_real_scene_task(db_session, novel_id: str):
    from infrastructure.tasks.models import AsyncTask
    from modules.writing.facade import create_published_draft_only

    await create_published_draft_only(
        db_session,
        novel_id,
        1,
        "Chapter one",
        "A real frozen chapter source for Scene extraction.",
    )
    lease_id = str(uuid.uuid4())
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="scene_auto_extraction",
        status="running",
        attempt=1,
        max_attempts=2,
        recovery_policy="manual_resume",
        lease_id=lease_id,
        progress=0.0,
        meta={
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 1,
            "stage": "scenes",
            "high_quality": False,
            "replace_existing": False,
            "authorization_snapshot": _authorization(novel_id),
            "llm_execution_snapshot": _snapshot(novel_id),
        },
        result={},
    )
    db_session.add(task)
    await db_session.commit()
    db_session.expunge(task)
    return task, lease_id


def _real_orchestrator(task_session, novel_id: str, events: list[str]):
    workflow = _RecordingWorkflow(
        task_session,
        events=events,
        real_commit=True,
    )

    async def _restore(db, requested_novel_id, snapshot):
        assert db is task_session
        assert db.in_transaction() is True
        assert requested_novel_id == novel_id
        assert snapshot == _snapshot(novel_id)
        return {"llm": {"model": "frozen-model"}, "deep_import": {}}

    orchestrator = DeepImportOrchestrator(
        workflow=workflow,
        snapshot_builder=mock.AsyncMock(
            side_effect=AssertionError("submitted task must reuse frozen snapshot")
        ),
        snapshot_restorer=mock.AsyncMock(side_effect=_restore),
    )
    return orchestrator, workflow


async def test_real_task_handler_rejected_final_checkpoint_rolls_back_scenes(
    db_session,
    test_project_id: str,
) -> None:
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.worker import _TaskHandlerSession
    from modules.story.outline_state.models import Scene

    task, lease_id = await _create_real_scene_task(db_session, test_project_id)
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
        if checkpoint_count == 2:
            return False
        return await TaskLifecycleService().checkpoint_running_attempt(
            task_session,
            task=task,
            lease_id=lease_id,
        )

    task_session.set_task_commit_hook(_checkpoint)
    orchestrator, workflow = _real_orchestrator(
        task_session,
        test_project_id,
        [],
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await orchestrator.run_stage_task(task_session, task, stage="scenes")
    finally:
        await task_session.close()

    db_session.expire_all()
    persisted = await db_session.get(AsyncTask, task.id)
    scenes = list(
        (
            await db_session.execute(
                select(Scene).where(Scene.novel_id == uuid.UUID(test_project_id))
            )
        ).scalars()
    )
    assert checkpoint_count == 2
    assert workflow.provider_calls == 2
    assert scenes == []
    assert persisted is not None
    assert persisted.status == "running"
    assert persisted.result["phase"] == "pending"
    assert SCENE_STAGE_TASK_PREPARE_KEY in persisted.meta


async def test_real_terminal_finalize_rejection_replays_done_without_provider(
    db_session,
    test_project_id: str,
) -> None:
    from infrastructure.tasks.lifecycle import TaskLifecycleService
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.worker import TaskWorker, _TaskHandlerSession
    from modules.story.outline_state.models import Scene

    task, lease_id = await _create_real_scene_task(db_session, test_project_id)
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

    task_session.set_task_commit_hook(_checkpoint)
    orchestrator, workflow = _real_orchestrator(
        task_session,
        test_project_id,
        [],
    )
    try:
        result = await orchestrator.run_stage_task(
            task_session,
            task,
            stage="scenes",
        )
        assert result["phase"] == "done"
        assert workflow.provider_calls == 2
        assert checkpoint_count == 2

        manager = SimpleNamespace(engine=bind, session_factory=None)
        reject_guard = mock.AsyncMock(return_value=False)
        rejected = await TaskWorker(
            db_manager=manager,
            task_commit_guard=reject_guard,
            heartbeat_interval=60.0,
        )._finalize_task(
            task_session,
            task=task,
            task_id=task.id,
            lease_id=lease_id,
            status="done",
            result_data=result,
        )
        assert rejected is False
        reject_guard.assert_awaited_once()

        db_session.expire_all()
        checkpointed = await db_session.get(AsyncTask, task.id)
        assert checkpointed is not None
        assert checkpointed.status == "running"
        assert checkpointed.result["phase"] == "done"
        first_scenes = list(
            (
                await db_session.execute(
                    select(Scene).where(Scene.novel_id == uuid.UUID(test_project_id))
                )
            ).scalars()
        )
        assert len(first_scenes) == 1

        task_session.set_task_commit_hook(_checkpoint)
        replay_orchestrator, replay_workflow = _real_orchestrator(
            task_session,
            test_project_id,
            [],
        )
        replay = await replay_orchestrator.run_stage_task(
            task_session,
            task,
            stage="scenes",
        )
        assert replay["phase"] == "done"
        assert replay_workflow.provider_calls == 0
        assert checkpoint_count == 2

        accepted = await TaskWorker(
            db_manager=manager,
            heartbeat_interval=60.0,
        )._finalize_task(
            task_session,
            task=task,
            task_id=task.id,
            lease_id=lease_id,
            status="done",
            result_data=replay,
        )
        assert accepted is True
    finally:
        await task_session.close()

    db_session.expire_all()
    finalized = await db_session.get(AsyncTask, task.id)
    final_scenes = list(
        (
            await db_session.execute(
                select(Scene).where(Scene.novel_id == uuid.UUID(test_project_id))
            )
        ).scalars()
    )
    assert finalized is not None
    assert finalized.status == "done"
    assert finalized.result["phase"] == "done"
    assert len(final_scenes) == 1
