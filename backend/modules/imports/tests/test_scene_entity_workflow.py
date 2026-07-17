"""SceneEntityExtractionService 单元/集成测试。

覆盖 Phase 2 的实体/关系持久化、auto_ingested 元数据、Delta 记录。
"""


from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMInvalidResponseError,
    LLMRateLimitError,
)
from modules.imports.entity_extraction import (
    scene_entity_extraction as scene_entity_extraction_module,
)
from modules.imports.entity_extraction.scene_entity_bulk import BulkSceneEntityExtractor
from modules.imports.entity_extraction.scene_entity_extraction import (
    SceneEntityExtractionService,
)
from modules.imports.entity_extraction.scene_entity_phase2b_context import (
    build_phase2b_context_bundle,
    phase2b_scene_input_fingerprint,
)
from modules.imports.entity_extraction.scene_entity_text import (
    scene_chapter_ids,
    scene_chunks_by_chapter,
    scene_context_header,
    select_scene_text,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedCharacterLocationProposal,
    ExtractedEntity,
    SceneEntityExtractionOutput,
)
from modules.writing.contracts import WritingDraftContract


class _FakeSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeNestedDb:
    def begin_nested(self):
        return _FakeSavepoint()


def _phase2b_activation(novel_id: str, scene_id: str, text: str = "Scene 正文"):
    return SimpleNamespace(
        novel_id=novel_id,
        scene_id=scene_id,
        activation_version="import-context-v2",
        current_scene_text=text,
        current_scene_sources=[
            {"type": "source_range", "id": f"draft:{scene_id}", "content_hash": "h"}
        ],
        previous_briefs=[],
        previous_evidence=[],
        sources=[
            {"type": "source_range", "id": f"draft:{scene_id}", "content_hash": "h"}
        ],
        warnings=[],
        scene_card={},
        outline_context={"scenes": [], "arcs": [], "plot_threads": []},
        identity_candidates=[],
        relation_candidates=[],
        omitted_sources=[],
        context_fingerprint=f"context:{scene_id}:{text}",
    )


async def _phase2b_prepare_activation(
    _db,
    *,
    novel_id: str,
    scene_id: str,
    **_kwargs,
):
    return _phase2b_activation(novel_id, scene_id)


def _phase2b_test_fingerprint(novel_id: str, scene: dict, text: str) -> str:
    activation = _phase2b_activation(novel_id, str(scene["id"]), text)
    bundle = build_phase2b_context_bundle(
        activation,
        novel_id=novel_id,
        scene_id=str(scene["id"]),
    )
    return phase2b_scene_input_fingerprint(
        scene,
        text,
        bundle["context_fingerprint"],
    )


async def _snapshot_rows(db_session: AsyncSession, novel_id: str):
    from modules.context.facade import list_context_snapshots

    return await list_context_snapshots(db_session, novel_id=novel_id)


@contextmanager
def _patched_phase2_summaries(svc: SceneEntityExtractionService):
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(
                svc,
                "_phase2_audit_summary",
                autospec=True,
                return_value={},
            )
        )
        stack.enter_context(
            patch.object(
                svc,
                "_phase2_snapshot_health_summary",
                autospec=True,
                return_value={},
            )
        )
        yield


@pytest_asyncio.fixture
async def novel_with_drafts(db_session: AsyncSession):
    """创建一个项目并写入第 1、2 章 draft。"""
    from modules.project.schemas import ProjectCreate
    from modules.project.services import ProjectService
    from modules.writing.facade import create_draft_only

    project = await ProjectService().create_project(
        db_session,
        ProjectCreate(title="Scene Extraction Test", language="zh"),
    )
    novel_id = str(project.id)
    await create_draft_only(
        db_session,
        novel_id,
        chapter_index=1,
        title="第一章",
        content="主角克莱恩醒来。",
    )
    await create_draft_only(
        db_session,
        novel_id,
        chapter_index=2,
        title="第二章",
        content="他遇到了梅丽莎。",
    )
    return novel_id


@pytest.mark.asyncio
async def test_phase2b_entity_index_only_includes_working_statuses(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    from modules.world.facade import create_entity

    for name, status in [
        ("正史对象", "canonical"),
        ("草稿对象", "draft"),
        ("候选对象", "candidate"),
        ("废弃对象", "deprecated"),
        ("忽略对象", "ignored"),
    ]:
        await create_entity(
            db_session,
            novel_with_drafts,
            {"name": name, "entity_type": "character", "status": status},
        )

    index = await svc._build_alias_relation_entity_index(
        db_session,
        novel_with_drafts,
    )

    assert "正史对象" in index
    assert "草稿对象" in index
    assert "候选对象" in index
    assert "废弃对象" not in index
    assert "忽略对象" not in index


@pytest.mark.asyncio
async def test_phase2b_scene_failure_degrades_without_raising(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)

    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            autospec=True,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            side_effect=RuntimeError("schema mismatch"),
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b",
        )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7]
    assert result["degraded"] is True
    assert result["error_kind"] == "RuntimeError"
    assert result["error_message"] == "schema mismatch"


@pytest.mark.asyncio
async def test_phase2b_total_timeout_budget_degrades_remaining_scenes(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)

    async def slow_alias_relation_call(*_args, **_kwargs):
        await asyncio.Event().wait()
        return AliasRelationExtractionOutput(aliases=[], relations=[])

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_total_timeout_seconds",
        lambda: 0.01,
    )
    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            autospec=True,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            side_effect=slow_alias_relation_call,
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [
                {"scene_index": 7, "id": "scene-7"},
                {"scene_index": 8, "id": "scene-8"},
            ],
            workflow_id="wf-phase2b",
        )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7, 8]
    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert result["alias_relation_total_timeout_s"] == 0.01
    assert result["alias_relation_elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_phase2b_runs_llm_calls_concurrently_before_serial_persistence(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id="snapshot-shared")
    both_started = asyncio.Event()
    started_calls = 0

    async def concurrent_alias_relation_call(*_args, **_kwargs):
        nonlocal started_calls
        started_calls += 1
        if started_calls == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        return AliasRelationExtractionOutput(aliases=[], relations=[])

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_concurrency",
        lambda: 2,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_total_timeout_seconds",
        lambda: 1,
    )
    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            autospec=True,
            return_value="## 可用对象索引",
        ) as build_entity_index,
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            side_effect=concurrent_alias_relation_call,
        ),
        patch.object(
            svc,
            "_persist_alias_relation_output",
            autospec=True,
            return_value={"aliases": 0, "relations": 0},
        ) as persist_output,
        patch(
            "modules.context.facade.succeed_context_snapshot",
            autospec=True,
        ),
        patch(
            "modules.context.facade.fail_context_snapshot",
            autospec=True,
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [
                {"scene_index": 7, "id": "scene-7"},
                {"scene_index": 8, "id": "scene-8"},
            ],
            workflow_id="wf-phase2b",
        )

    assert started_calls == 2
    assert result["alias_relation_scenes"] == 2
    assert result["alias_relation_failed_scenes"] == []
    assert result["alias_relation_concurrency"] == 2
    assert build_entity_index.await_count == 0
    assert persist_output.await_count == 2
    assert {
        call.kwargs["context_snapshot_id"]
        for call in persist_output.await_args_list
    } == {"snapshot-shared"}


@pytest.mark.asyncio
async def test_phase2b_provider_call_has_no_open_database_transaction(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()

    async def assert_no_transaction(*_args, **_kwargs):
        assert db_session.in_transaction() is False
        return AliasRelationExtractionOutput()

    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            return_value=Mock(id=None),
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            side_effect=assert_no_transaction,
        ),
        patch.object(
            svc,
            "_persist_alias_relation_output",
            autospec=True,
            return_value={"aliases": 0, "relations": 0, "uncertain_count": 0},
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b-no-provider-transaction",
        )

    assert result["alias_relation_scenes"] == 1
    assert result["alias_relation_failed_scenes"] == []


@pytest.mark.asyncio
async def test_phase2b_records_checkpoints_and_progress(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)
    progress_events: list[tuple[int, int, str | None]] = []

    async def on_progress(
        completed: int,
        total: int,
        *,
        operation: str | None = None,
    ) -> None:
        progress_events.append((completed, total, operation))

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_total_timeout_seconds",
        lambda: 1,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_alias_relation_scene_char_limit",
        lambda: 5,
    )
    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            autospec=True,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            return_value=AliasRelationExtractionOutput(aliases=[], relations=[]),
        ),
        patch.object(
            svc,
            "_persist_alias_relation_output",
            autospec=True,
            return_value={"aliases": 1, "relations": 2},
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b",
            on_scene_progress=on_progress,
            existing_checkpoints={
                "phase2b": {
                    "scenes": [
                        {
                            "scene_id": "scene-7",
                            "status": "done",
                            "input_fingerprint": "stale-fingerprint",
                        }
                    ]
                }
            },
        )

    assert progress_events[0] == (0, 1, "alias_relation_extraction")
    assert progress_events[-1] == (1, 1, "alias_relation_extraction")
    checkpoints = result["alias_relation_checkpoints"]["phase2b"]["scenes"]
    assert len(checkpoints) == 1
    assert checkpoints[0] | {"input_fingerprint": None} == {
        "scene_id": "scene-7",
        "scene_index": 7,
        "position": 7,
        "status": "done",
        "aliases": 1,
        "relations": 2,
        "uncertain_items": 0,
        "retry_count": 0,
        "fallback": False,
        "source": "deep_import",
        "auto_ingested": True,
        "input_fingerprint": None,
    }
    assert len(checkpoints[0]["input_fingerprint"]) == 64
    assert checkpoints[0]["input_fingerprint"] == _phase2b_test_fingerprint(
        novel_with_drafts,
        {"scene_index": 7, "id": "scene-7"},
        "Scene 正文",
    )
    assert result["alias_relation_rerun_scenes"] == 1


@pytest.mark.parametrize("checkpoint_status", ["done", "skipped"])
@pytest.mark.asyncio
async def test_phase2b_existing_checkpoint_skips_scene(
    db_session: AsyncSession,
    novel_with_drafts: str,
    checkpoint_status: str,
) -> None:
    svc = SceneEntityExtractionService()
    progress_events: list[tuple[int, int]] = []

    async def on_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    scene = {"scene_index": 7, "id": "new-scene-7"}
    scene_text = "Scene 正文"
    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value=scene_text,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
        ) as call_alias_relation,
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [scene],
            workflow_id="wf-phase2b",
            existing_checkpoints={
                "phase2b": {
                    "scenes": [
                        {
                            "scene_id": "new-scene-7",
                            "scene_index": 7,
                            "status": checkpoint_status,
                            "aliases": 3,
                            "relations": 4,
                            "retry_count": 0,
                            "input_fingerprint": _phase2b_test_fingerprint(
                                novel_with_drafts,
                                scene,
                                scene_text,
                            ),
                        }
                    ]
                }
            },
            on_scene_progress=on_progress,
        )

    assert call_alias_relation.await_count == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_skipped_scenes"] == 1
    assert result["alias_relation_failed_scenes"] == []
    assert progress_events == [(0, 1), (1, 1)]
    checkpoint = result["alias_relation_checkpoints"]["phase2b"]["scenes"][0]
    assert checkpoint["scene_id"] == "new-scene-7"
    assert checkpoint["status"] == "skipped"
    assert checkpoint["aliases"] == 3
    assert checkpoint["relations"] == 4
    assert checkpoint["fallback"] is False


@pytest.mark.asyncio
async def test_phase2b_invalid_json_falls_back_to_empty_result(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    snapshot = Mock(id=None)

    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            autospec=True,
            return_value="## 可用对象索引\n- 克莱恩 (character)",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            return_value=snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            side_effect=LLMInvalidResponseError("truncated json"),
        ),
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b",
        )

    assert result["alias_relation_scenes"] == 1
    assert result["alias_relation_failed_scenes"] == []
    assert result["alias_relation_fallback_scenes"] == [7]
    assert result["degraded"] is False
    assert result["error_kind"] is None
    checkpoint = result["alias_relation_checkpoints"]["phase2b"]["scenes"][0]
    assert checkpoint["status"] == "done"
    assert checkpoint["fallback"] is True
    assert checkpoint["error_kind"] == "LLMInvalidResponseError"


@pytest.mark.asyncio
async def test_phase2b_watchdog_timeout_returns_degraded_result(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def stuck_alias_relation_run(*_args, **_kwargs):
        await asyncio.Event().wait()
        return {
            "total_aliases": 1,
            "total_relations": 1,
            "alias_relation_scenes": 1,
            "alias_relation_failed_scenes": [],
        }

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "_phase2_config.phase2_alias_relation_total_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "PHASE2_SCENE_TIMEOUT_GRACE_SECONDS",
        0,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "SceneEntityExtractionService._execute_alias_relation_phase",
        stuck_alias_relation_run,
    )

    result = await svc._run_alias_relation_phase(
        db_session,
        novel_with_drafts,
        [
            {"scene_index": 7, "id": "scene-7"},
            {"scene_index": 8, "id": "scene-8"},
        ],
        workflow_id="wf-phase2b-watchdog",
    )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7, 8]
    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert result["alias_relation_total_timeout_s"] == 0.01
    assert result["alias_relation_concurrency"] == 4


@pytest.mark.asyncio
async def test_phase2b_watchdog_uses_dynamic_timeout_for_large_scene_sets(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def quick_alias_relation_run(*_args, **_kwargs):
        return {
            "total_aliases": 0,
            "total_relations": 0,
            "alias_relation_scenes": 84,
            "alias_relation_failed_scenes": [],
            "alias_relation_total_timeout_s": 2895,
            "alias_relation_concurrency": 4,
        }

    monkeypatch.delenv("PHASE2_ALIAS_RELATION_TOTAL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "SceneEntityExtractionService._execute_alias_relation_phase",
        quick_alias_relation_run,
    )

    result = await svc._run_alias_relation_phase(
        db_session,
        novel_with_drafts,
        [{"scene_index": index, "id": f"scene-{index}"} for index in range(1, 85)],
        workflow_id="wf-phase2b-dynamic-watchdog",
    )

    assert result["alias_relation_scenes"] == 84
    assert result["alias_relation_failed_scenes"] == []


@pytest.mark.asyncio
async def test_optional_phase2b_skips_supplement_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    monkeypatch.delenv("PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED", raising=False)

    with patch.object(
        svc,
        "_run_alias_relation_phase",
        autospec=True,
    ) as run_alias_relation:
        result = await svc._run_optional_alias_relation_phase(
            Mock(),
            "novel-1",
            [{"scene_index": 1}],
            workflow_id="wf-optional-skip",
        )

    assert run_alias_relation.await_count == 0
    assert result["alias_relation_skipped"] is True
    assert result["alias_relation_failed_scenes"] == []
    assert result["degraded"] is False


@pytest.mark.asyncio
async def test_phase2a_only_alias_relation_result_skips_phase2b_even_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED", "1")

    with patch.object(
        svc,
        "_run_alias_relation_phase",
        autospec=True,
    ) as run_alias_relation:
        result = await svc._phase2_alias_relation_result(
            Mock(),
            "novel-1",
            [{"scene_index": 1}],
            workflow_id="wf-phase2a-skip",
            include_alias_relations=False,
        )

    assert run_alias_relation.await_count == 0
    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == []
    assert result["alias_relation_skipped"] is True
    assert result["alias_relation_skip_reason"] == "phase2a_only"


@pytest.mark.asyncio
async def test_optional_phase2b_runs_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    monkeypatch.setenv("PHASE2_ALIAS_RELATION_SUPPLEMENT_ENABLED", "1")

    with patch.object(
        svc,
        "_run_alias_relation_phase",
        autospec=True,
        return_value={
            "total_aliases": 1,
            "total_relations": 1,
            "alias_relation_scenes": 1,
            "alias_relation_failed_scenes": [],
            "degraded": False,
        },
    ) as run_alias_relation:
        result = await svc._run_optional_alias_relation_phase(
            Mock(),
            "novel-1",
            [{"scene_index": 1}],
            workflow_id="wf-optional-run",
        )

    assert run_alias_relation.await_count == 1
    assert result["total_aliases"] == 1
    assert result["total_relations"] == 1


@pytest.mark.asyncio
async def test_phase2b_snapshot_preparation_timeout_degrades_scene(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def slow_snapshot(*_args, **_kwargs):
        await asyncio.Event().wait()
        return Mock(id="snapshot-7")

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_alias_relation."
        "phase2_postprocess_timeout_seconds",
        lambda: 0.01,
    )
    with (
        patch.object(
            svc,
            "_prepare_import_context_activation",
            autospec=True,
            side_effect=_phase2b_prepare_activation,
        ),
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="Scene 正文",
        ),
        patch.object(
            svc,
            "_build_alias_relation_entity_index",
            autospec=True,
            return_value="## 可用对象索引",
        ),
        patch.object(
            svc,
            "_create_phase2b_snapshot",
            autospec=True,
            side_effect=slow_snapshot,
        ),
        patch.object(
            svc,
            "_call_alias_relation_extraction",
            autospec=True,
            return_value=AliasRelationExtractionOutput(aliases=[], relations=[]),
        ) as alias_call,
    ):
        result = await svc._run_alias_relation_phase(
            db_session,
            novel_with_drafts,
            [{"scene_index": 7, "id": "scene-7"}],
            workflow_id="wf-phase2b-snapshot-timeout",
        )

    assert result["total_aliases"] == 0
    assert result["total_relations"] == 0
    assert result["alias_relation_scenes"] == 0
    assert result["alias_relation_failed_scenes"] == [7]
    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    alias_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_phase2_postprocess_summary_timeout_returns_degraded(
    db_session: AsyncSession,
    novel_with_drafts: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    async def slow_summary(*_args, **_kwargs):
        await asyncio.Event().wait()
        return {"ok": True}

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "_phase2_config.phase2_postprocess_timeout_seconds",
        lambda: 0.01,
    )
    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction.phase2_snapshot_health_summary",
        slow_summary,
    )

    result = await svc._phase2_snapshot_health_summary(
        db_session,
        novel_with_drafts,
        workflow_id="wf-summary-timeout",
    )

    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert "snapshot_health_summary" in result["error_message"]


@pytest.mark.asyncio
async def test_phase2_flush_timeout_returns_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()

    class SlowFlushDB:
        async def flush(self):
            await asyncio.Event().wait()

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_extraction."
        "_phase2_config.phase2_postprocess_timeout_seconds",
        lambda: 0.01,
    )

    result = await svc._phase2_flush_with_timeout(SlowFlushDB())

    assert result["degraded"] is True
    assert result["error_kind"] == "timeout"
    assert "db.flush" in result["error_message"]


@pytest.mark.asyncio
async def test_record_deltas_creates_memory_log_without_generic_map_noise(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    deltas = [
        DeltaEvent(
            category="ENTITY_CREATED",
            field="summary",
            old=None,
            new="summary text",
            meta={"source": "test"},
        )
    ]
    count = await svc._record_deltas(
        db_session,
        novel_with_drafts,
        deltas,
        scene_index=2,
        workflow_id="wf-delta",
        scene_id="00000000-0000-0000-0000-000000000002",
        scene_provenance_key="wf-delta:scene:2",
    )
    assert count == 1


    from modules.memory.models import DeltaLog
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_with_drafts, "novel_id")
    stmt = select(DeltaLog).where(DeltaLog.novel_id == nid, DeltaLog.scene_index == 2)
    result = await db_session.execute(stmt)
    items = result.scalars().all()
    assert len(items) == 1
    assert items[0].category == "ENTITY_CREATED"
    assert items[0].source == "deep_import"
    assert items[0].meta["workflow_id"] == "wf-delta"
    assert items[0].meta["scene_id"] == "00000000-0000-0000-0000-000000000002"
    assert items[0].meta["scene_provenance_key"] == "wf-delta:scene:2"
    assert items[0].meta["auto_ingested"] is True

    from modules.world.map_models import MapObservation

    obs_stmt = select(MapObservation).where(MapObservation.novel_id == nid)
    obs_result = await db_session.execute(obs_stmt)
    observations = obs_result.scalars().all()
    assert observations == []


@pytest.mark.asyncio
async def test_record_deltas_bridges_explicit_map_intent(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    count = await svc._record_deltas(
        db_session,
        novel_with_drafts,
        [
            DeltaEvent(
                category="POSITION_CHANGED",
                field="position",
                old="街口",
                new="教堂",
                meta={
                    "dynamic_type": "location",
                    "spatial_anchor": {"hex_q": 1, "hex_r": 2},
                    "evidence_text": "他从街口走进教堂。",
                },
            )
        ],
        scene_index=3,
        workflow_id="wf-map-delta",
        scene_id="00000000-0000-0000-0000-000000000003",
        scene_provenance_key="wf-map-delta:scene:3",
    )

    assert count == 1
    from modules.world.map_models import MapObservation
    from shared.utils import parse_uuid

    observations = list(
        (
            await db_session.execute(
                select(MapObservation).where(
                    MapObservation.novel_id
                    == parse_uuid(novel_with_drafts, "novel_id")
                )
            )
        ).scalars()
    )
    assert len(observations) == 1
    assert observations[0].dynamic_type == "location"
    assert observations[0].spatial_anchor == {"hex_q": 1, "hex_r": 2}
    assert observations[0].source_ref["source"] == "deep_import_delta_event"


@pytest.mark.asyncio
async def test_process_scene_captures_memory_snapshot(
    db_session: AsyncSession,
    novel_with_drafts: str,
) -> None:
    svc = SceneEntityExtractionService()
    scene = {
        "id": "scene-1",
        "novel_id": novel_with_drafts,
        "scene_index": 1,
        "chapter_ids": ["1"],
    }

    with (
        patch.object(
            svc,
            "_call_llm_extraction",
            return_value=Mock(
                entities=[
                    ExtractedEntity(
                        name="克莱恩",
                        entity_type="character",
                        suggested_action="create_new",
                    )
                ],
                relations=[],
                delta_events=[],
            ),
            autospec=True,
        ),
        patch(
            "modules.memory.facade.capture_snapshot",
            autospec=True,
        ) as mock_snapshot,
        patch(
            "modules.world.facade.find_similar_entities",
            autospec=True,
            return_value={},
        ),
    ):
        result = await svc._process_scene(
            db_session,
            novel_with_drafts,
            scene,
            scene_idx=0,
            existing_context="",
            accumulated_memory=[],
            seen_entity_keys=set(),
            workflow_id="wf-test-3",
        )

    assert result["created"] == 1
    mock_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_by_scenes_empty_route_skips_world_context() -> None:
    svc = SceneEntityExtractionService()
    db = Mock()

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=[]),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
        ) as world_context,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
        )

    world_context.assert_not_awaited()
    assert result["total_scenes"] == 0
    assert result["checkpoints"] == {"phase2": {"scenes": []}}


@pytest.mark.asyncio
async def test_extract_by_scenes_filters_explicit_repair_scene_ids() -> None:
    svc = SceneEntityExtractionService()
    target_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    scenes = [
        {
            "id": target_id,
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": other_id,
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    expected = {
        "total_scenes": 1,
        "total_created": 0,
        "failed_scene_indices": [],
        "checkpoints": {"phase2": {"scenes": []}},
    }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            autospec=True,
            return_value=expected,
        ) as process,
    ):
        result = await svc.extract_by_scenes(
            Mock(),
            "00000000-0000-0000-0000-000000000001",
            scene_ids=[target_id],
            existing_checkpoints={},
        )

    assert result is expected
    selected_scenes = process.await_args.args[2]
    assert [scene["id"] for scene in selected_scenes] == [target_id]


@pytest.mark.asyncio
async def test_extract_by_scenes_continues_after_single_transport_failure() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {"novel_id": "novel-1", "scene_index": 1, "chapter_ids": ["1"]},
        {"novel_id": "novel-1", "scene_index": 2, "chapter_ids": ["2"]},
    ]
    db = Mock()
    db.flush = AsyncMock()

    async def process_scene(*args, **kwargs):
        scene = args[2]
        if scene["scene_index"] == 1:
            raise LLMConnectionError("connection failed")
        return {
            "created": 1,
            "relations": 0,
            "deltas": 0,
            "created_entity_ids": ["entity-scene-2"],
            "created_relation_ids": [],
            "created_delta_ids": [],
            "updated_context": "updated",
            "updated_memory": [{"scene_index": 2, "entities": 1}],
        }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ) as world_context,
        patch.object(
            svc,
            "_process_scene",
            autospec=True,
            side_effect=process_scene,
        ) as process_scene,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    assert result["total_created"] == 1
    assert result["total_scenes"] == 2
    assert result["degraded"] is True
    assert result["error_kind"] == "connection_error"
    assert result["failed_scene_indices"] == [1]
    assert result["completed_scenes"] == 1
    assert result["skipped_scenes"] == 0
    assert result["stopped_early"] is False
    assert process_scene.await_count == 2
    world_context.assert_awaited_once_with(
        db,
        "00000000-0000-0000-0000-000000000001",
        reveal_mode="author_safe",
        limit=500,
        include_review=True,
    )


@pytest.mark.asyncio
async def test_extract_by_scenes_stops_after_repeated_transport_failures() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {"novel_id": "novel-1", "scene_index": 1, "chapter_ids": ["1"]},
        {"novel_id": "novel-1", "scene_index": 2, "chapter_ids": ["2"]},
        {"novel_id": "novel-1", "scene_index": 3, "chapter_ids": ["3"]},
        {"novel_id": "novel-1", "scene_index": 4, "chapter_ids": ["4"]},
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            autospec=True,
            side_effect=LLMConnectionError("connection failed"),
        ) as process_scene,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    assert result["total_created"] == 0
    assert result["total_scenes"] == 4
    assert result["degraded"] is True
    assert result["error_kind"] == "connection_error"
    assert result["failed_scene_indices"] == [1, 2, 3]
    assert result["completed_scenes"] == 0
    assert result["skipped_scenes"] == 1
    assert result["stopped_early"] is True
    assert process_scene.await_count == 3


@pytest.mark.asyncio
async def test_phase2_records_checkpoint_for_each_successful_scene() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-b",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    db = Mock()
    db.flush = AsyncMock()

    async def process_scene(*args, **kwargs):
        scene = args[2]
        scene_idx = args[3]
        return {
            "created": 1,
            "relations": 1,
            "deltas": 1,
            "created_entity_ids": [f"entity-{scene['id']}"],
            "created_relation_ids": [f"relation-{scene['id']}"],
            "created_delta_ids": [f"delta-{scene['id']}"],
            "updated_context": "updated",
            "updated_memory": [{"scene_index": scene_idx, "entities": 1}],
        }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            autospec=True,
            side_effect=process_scene,
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-checkpoint",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert [checkpoint["scene_id"] for checkpoint in checkpoints] == [
        "scene-a",
        "scene-b",
    ]
    assert all(checkpoint["status"] == "done" for checkpoint in checkpoints)
    assert checkpoints[0]["created_entity_ids"] == ["entity-scene-a"]
    assert checkpoints[0]["created_relation_ids"] == ["relation-scene-a"]
    assert checkpoints[0]["created_delta_ids"] == ["delta-scene-a"]
    assert checkpoints[0]["workflow_id"] == "wf-phase2-checkpoint"
    assert checkpoints[0]["source"] == "deep_import"
    assert checkpoints[0]["auto_ingested"] is True


@pytest.mark.asyncio
async def test_phase2_small_sample_uses_bulk_extraction_with_scene_checkpoints() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-b",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_bulk",
            autospec=True,
            return_value={
                "created": 2,
                "relations": 1,
                "deltas": 1,
                "created_entity_ids": ["entity-a", "entity-b"],
                "created_relation_ids": ["relation-a"],
                "created_delta_ids": ["delta-a"],
            },
        ) as bulk,
        patch.object(svc, "_process_scene", autospec=True) as process_scene,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-bulk",
        )

    bulk.assert_awaited_once()
    process_scene.assert_not_awaited()
    assert result["total_created"] == 2
    assert result["completed_scenes"] == 2
    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert [checkpoint["scene_id"] for checkpoint in checkpoints] == [
        "scene-a",
        "scene-b",
    ]
    assert all(checkpoint["status"] == "done" for checkpoint in checkpoints)
    assert checkpoints[0]["created_entity_ids"] == ["entity-a", "entity-b"]


@pytest.mark.asyncio
async def test_phase2_small_sample_prefers_parallel_scene_llm() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 9)
    ]
    db = Mock()
    db.flush = AsyncMock()
    parallel_result = {
        "total_created": 24,
        "total_relations": 0,
        "total_deltas": 0,
        "total_scenes": 8,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 8,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
        "parallel_llm_fallback": True,
        "bulk_error_kind": "small_sample_parallel_default",
    }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            autospec=True,
            return_value=parallel_result,
        ) as parallel,
        patch.object(svc, "_process_scenes_bulk", autospec=True) as bulk,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-parallel-default",
        )

    parallel.assert_awaited_once()
    bulk.assert_not_awaited()
    assert result["total_created"] == 24
    assert result["bulk_error_kind"] == "small_sample_parallel_default"


@pytest.mark.asyncio
async def test_phase2_large_without_checkpoints_uses_batched_route() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 14)
    ]
    db = Mock()
    db.flush = AsyncMock()
    batched_result = {
        "total_created": 13,
        "total_relations": 0,
        "total_aliases": 0,
        "total_deltas": 0,
        "total_scenes": 13,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 13,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
    }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_batched",
            autospec=True,
            return_value=batched_result,
        ) as batched,
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            autospec=True,
        ) as parallel,
        patch.object(svc, "_process_scenes_bulk", autospec=True) as bulk,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-batched-route",
        )

    batched.assert_awaited_once()
    parallel.assert_not_awaited()
    bulk.assert_not_awaited()
    assert result["total_created"] == 13


@pytest.mark.asyncio
async def test_phase2_bulk_failure_uses_parallel_llm_fallback() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        }
    ]
    db = Mock()
    db.flush = AsyncMock()

    parallel_result = {
        "total_created": 3,
        "total_relations": 0,
        "total_deltas": 0,
        "total_scenes": 1,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 1,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
        "parallel_llm_fallback": True,
        "bulk_error_kind": "timeout",
    }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scenes_bulk",
            autospec=True,
            side_effect=TimeoutError("bulk timeout"),
        ) as bulk,
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            autospec=True,
            return_value=parallel_result,
        ) as parallel,
        patch.object(
            svc,
            "_phase2_alias_relation_result",
            autospec=True,
            return_value={"total_aliases": 2},
        ) as alias_result,
        patch.object(
            svc,
            "_merge_alias_relation_result",
            return_value={**parallel_result, "total_aliases": 2},
            autospec=True,
        ) as merge_alias,
        patch.object(svc, "_process_scene", autospec=True) as process_scene,
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-parallel",
        )

    bulk.assert_awaited_once()
    parallel.assert_awaited_once()
    alias_result.assert_awaited_once()
    merge_alias.assert_called_once()
    process_scene.assert_not_awaited()
    assert result["parallel_llm_fallback"] is True
    assert result["bulk_error_kind"] == "timeout"
    assert result["total_aliases"] == 2


@pytest.mark.asyncio
async def test_persistent_phase2_scene_threads_end_chapter_into_activation() -> None:
    svc = SceneEntityExtractionService()
    scene_id = str(uuid.uuid4())
    scenes = [
        {
            "id": scene_id,
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": 7,
            "chapter_ids": ["78", "79", "80", "81"],
        }
    ]
    expected = {
        "total_created": 0,
        "total_relations": 0,
        "total_aliases": 0,
        "total_deltas": 0,
        "total_scenes": 1,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "failed_scene_indices": [],
        "completed_scenes": 1,
        "skipped_scenes": 0,
        "rerun_scenes": 0,
        "stopped_early": False,
        "checkpoints": {"phase2": {"scenes": []}},
    }

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            autospec=True,
            return_value=expected,
        ) as activated,
    ):
        existing_checkpoints = {
            "phase2b": {
                "scenes": [
                    {
                        "scene_id": scene_id,
                        "status": "done",
                        "input_fingerprint": "phase2b-fingerprint",
                    }
                ]
            }
        }
        result = await svc.extract_by_scenes(
            Mock(),
            "00000000-0000-0000-0000-000000000001",
            end_chapter=80,
            existing_checkpoints=existing_checkpoints,
        )

    assert result is expected
    assert activated.await_args.kwargs["visible_until_chapter"] == 80
    assert (
        activated.await_args.kwargs["existing_alias_relation_checkpoints"]
        is existing_checkpoints
    )
    assert activated.await_args.args[2] == scenes


@pytest.mark.asyncio
async def test_parallel_llm_fallback_extracts_before_serial_persistence() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
            "title": f"Scene {index}",
        }
        for index in (1, 2)
    ]
    db = Mock()
    db.flush = AsyncMock()
    events: list[str] = []
    llm_barrier = asyncio.Event()
    llm_calls = 0

    async def load_scene(_db, scene):
        return f"正文 {scene['scene_index']}"

    async def create_snapshot(*_args, **_kwargs):
        scene = _args[2]
        return Mock(id=f"snapshot-{scene['scene_index']}")

    async def call_llm(chapters_text: str, *_args, **_kwargs):
        nonlocal llm_calls
        events.append(f"llm-{chapters_text[-1]}")
        llm_calls += 1
        if llm_calls == len(scenes):
            llm_barrier.set()
        await llm_barrier.wait()
        return SceneEntityExtractionOutput(
            entities=[
                ExtractedEntity(
                    name=f"实体{chapters_text[-1]}",
                    entity_type="character",
                    suggested_action="create_new",
                )
            ],
            relations=[],
            delta_events=[],
        )

    async def persist_entities(*_args, **kwargs):
        result_refs = kwargs["result_refs"]
        scene_index = kwargs["scene_index"]
        events.append(f"persist-{scene_index}")
        result_refs.append({"type": "core_entity", "id": f"entity-{scene_index}"})
        return 1

    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, side_effect=load_scene),
        patch.object(
            svc, "_create_phase2_snapshot", autospec=True, side_effect=create_snapshot
        ),
        patch.object(svc, "_call_llm_extraction", autospec=True, side_effect=call_llm),
        patch.object(
            svc, "_persist_entities", autospec=True, side_effect=persist_entities
        ),
        patch.object(
            svc,
            "_persist_relations",
            autospec=True,
            return_value=0,
        ) as persist_relations,
        patch.object(
            svc,
            "_record_deltas",
            autospec=True,
            return_value=0,
        ),
        patch.object(
            svc,
            "_supplement_small_sample_entities",
            autospec=True,
            return_value={
                "created": 0,
                "created_entity_ids": [],
                "supplemental_llm_created": 0,
                "fallback_created": 0,
                "supplemental_error_kind": None,
            },
        ),
        _patched_phase2_summaries(svc),
        patch("modules.context.facade.succeed_context_snapshot", autospec=True),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await svc._process_scenes_parallel_llm(
            db,
            "00000000-0000-0000-0000-000000000001",
            scenes,
            "无已有对象",
            workflow_id="wf-phase2-parallel",
            on_scene_progress=None,
            bulk_error_kind="schema_error",
        )

    first_persist_index = min(
        index for index, event in enumerate(events) if event.startswith("persist-")
    )
    assert all(event.startswith("llm-") for event in events[:first_persist_index])
    assert result["parallel_llm_fallback"] is True
    assert result["bulk_error_kind"] == "schema_error"
    assert result["total_created"] == 2
    persist_relations.assert_not_awaited()
    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert [checkpoint["created_entity_ids"] for checkpoint in checkpoints] == [
        ["entity-1"],
        ["entity-2"],
    ]


@pytest.mark.asyncio
async def test_parallel_phase2_skips_unresolved_scene_without_failing_stage() -> None:
    svc = SceneEntityExtractionService()
    scene = {
        "id": "transient-scene-without-exact-span",
        "novel_id": "novel-1",
        "scene_index": 58,
        "chapter_ids": ["13"],
        "title": "待修复 Scene",
    }
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(
            svc,
            "_load_scene_chapters",
            autospec=True,
            return_value="",
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc._process_scenes_parallel_llm(
            db,
            "00000000-0000-0000-0000-000000000001",
            [scene],
            "无已有对象",
            workflow_id="wf-phase2-unresolved",
            on_scene_progress=None,
            bulk_error_kind="unified_activation:fresh",
            include_alias_relations=False,
        )

    assert result["failed_scene_indices"] == []
    assert result["failed_scene_ids"] == []
    assert result["skipped_scenes"] == 1
    assert result["unresolved_scene_indices"] == [58]
    assert result["degraded"] is True
    checkpoint = result["checkpoints"]["phase2"]["scenes"][0]
    assert checkpoint["status"] == "skipped"
    assert checkpoint["error_kind"] == "current_scene_span_coverage_missing"


@pytest.mark.asyncio
async def test_parallel_phase2_closes_db_transaction_before_provider_call(
    db_session: AsyncSession,
) -> None:
    svc = SceneEntityExtractionService()
    scene = {
        "id": "transient-scene",
        "novel_id": "00000000-0000-0000-0000-000000000001",
        "scene_index": 3,
        "chapter_ids": ["3"],
        "title": "事务边界",
    }

    async def load_scene(db: AsyncSession, _scene: dict) -> str:
        await db.execute(select(1))
        assert db.in_transaction()
        return "沈砚走进青石镇。"

    async def call_llm(*_args, **_kwargs) -> SceneEntityExtractionOutput:
        assert not db_session.in_transaction()
        return SceneEntityExtractionOutput()

    progress_events: list[tuple[int, int]] = []

    async def on_scene_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    async def persist_entities(*_args, **kwargs) -> int:
        assert progress_events == [(1, 1)]
        stats = kwargs["persistence_stats"]
        stats["action_counts"]["link_to_existing"] += 1
        stats["dedup_counts"]["skipped"] += 1
        stats["linked_to_existing"] += 1
        return 0

    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, side_effect=load_scene),
        patch.object(
            svc,
            "_create_phase2_snapshot",
            autospec=True,
            return_value=Mock(id=None),
        ),
        patch.object(svc, "_call_llm_extraction", autospec=True, side_effect=call_llm),
        patch.object(
            svc,
            "_persist_entities",
            autospec=True,
            side_effect=persist_entities,
        ),
        patch.object(svc, "_record_deltas", autospec=True, return_value=0),
        _patched_phase2_summaries(svc),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await svc._process_scenes_parallel_llm(
            db_session,
            scene["novel_id"],
            [scene],
            "无已有对象",
            workflow_id="wf-no-provider-transaction",
            on_scene_progress=on_scene_progress,
            bulk_error_kind="unified_activation:fresh",
            include_alias_relations=False,
        )

    assert result["completed_scenes"] == 1
    assert progress_events == [(1, 1)]
    assert result["phase2_action_counts"]["link_to_existing"] == 1
    assert result["phase2_dedup_counts"]["skipped"] == 1
    assert result["phase2_linked_to_existing"] == 1


@pytest.mark.asyncio
async def test_parallel_phase2_format_diagnostics_do_not_throttle_or_skip_scenes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"transient-scene-{index}",
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": index,
            "chapter_ids": [str(index)],
            "title": f"Scene {index}",
        }
        for index in range(1, 8)
    ]
    llm_calls = 0
    progress_events: list[tuple[int, int]] = []

    async def load_scene(_db: AsyncSession, scene: dict) -> str:
        return f"{scene['title']} 正文"

    async def call_llm(*_args, **kwargs) -> SceneEntityExtractionOutput:
        nonlocal llm_calls
        llm_calls += 1
        if llm_calls <= 3:
            kwargs["diagnostics"].append({"kind": "partial_list_validation"})
        return SceneEntityExtractionOutput()

    async def on_scene_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_parallel."
        "phase2_parallel_scene_concurrency",
        lambda: 4,
    )
    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, side_effect=load_scene),
        patch.object(
            svc,
            "_create_phase2_snapshot",
            autospec=True,
            return_value=Mock(id=None),
        ),
        patch.object(svc, "_call_llm_extraction", autospec=True, side_effect=call_llm),
        patch.object(svc, "_persist_entities", autospec=True, return_value=0),
        patch.object(svc, "_record_deltas", autospec=True, return_value=0),
        _patched_phase2_summaries(svc),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await svc._process_scenes_parallel_llm(
            db_session,
            scenes[0]["novel_id"],
            scenes,
            "无已有对象",
            workflow_id="wf-adaptive-throttle",
            on_scene_progress=on_scene_progress,
            bulk_error_kind="unified_activation:batched",
            include_alias_relations=False,
        )

    assert llm_calls == len(scenes)
    assert result["completed_scenes"] == len(scenes)
    assert len(result["checkpoints"]["phase2"]["scenes"]) == len(scenes)
    assert progress_events[-1] == (len(scenes), len(scenes))
    assert [completed for completed, _total in progress_events] == list(
        range(1, len(scenes) + 1)
    )
    assert result["phase2_throttle_reasons"] == []


@pytest.mark.asyncio
async def test_parallel_phase2_transport_throttle_does_not_skip_scenes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"transient-scene-{index}",
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": index,
            "chapter_ids": [str(index)],
            "title": f"Scene {index}",
        }
        for index in range(1, 8)
    ]
    llm_calls = 0
    progress_events: list[tuple[int, int]] = []

    async def load_scene(_db: AsyncSession, scene: dict) -> str:
        return f"{scene['title']} 正文"

    async def call_llm(*_args, **_kwargs) -> SceneEntityExtractionOutput:
        nonlocal llm_calls
        llm_calls += 1
        if llm_calls <= 2:
            raise TimeoutError("provider timed out")
        return SceneEntityExtractionOutput()

    async def on_scene_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_parallel."
        "phase2_parallel_scene_concurrency",
        lambda: 4,
    )
    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, side_effect=load_scene),
        patch.object(
            svc,
            "_create_phase2_snapshot",
            autospec=True,
            return_value=Mock(id=None),
        ),
        patch.object(svc, "_call_llm_extraction", autospec=True, side_effect=call_llm),
        patch.object(svc, "_persist_entities", autospec=True, return_value=0),
        patch.object(svc, "_record_deltas", autospec=True, return_value=0),
        _patched_phase2_summaries(svc),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await svc._process_scenes_parallel_llm(
            db_session,
            scenes[0]["novel_id"],
            scenes,
            "无已有对象",
            workflow_id="wf-transport-throttle",
            on_scene_progress=on_scene_progress,
            bulk_error_kind="unified_activation:batched",
            include_alias_relations=False,
        )

    assert llm_calls == len(scenes)
    assert result["completed_scenes"] == len(scenes) - 2
    assert len(result["checkpoints"]["phase2"]["scenes"]) == len(scenes)
    assert len(result["failed_scene_indices"]) == 2
    assert progress_events[-1] == (len(scenes), len(scenes))
    assert [completed for completed, _total in progress_events] == list(
        range(1, len(scenes) + 1)
    )
    assert result["phase2_throttle_reasons"] == ["transport_failure_window"]


@pytest.mark.asyncio
async def test_parallel_phase2_single_rate_limit_throttles_without_skipping_scenes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"rate-limited-scene-{index}",
            "novel_id": "00000000-0000-0000-0000-000000000001",
            "scene_index": index,
            "chapter_ids": [str(index)],
            "title": f"Scene {index}",
        }
        for index in range(1, 8)
    ]
    llm_calls = 0
    progress_events: list[tuple[int, int]] = []

    async def load_scene(_db: AsyncSession, scene: dict) -> str:
        return f"{scene['title']} 正文"

    async def call_llm(*_args, **_kwargs) -> SceneEntityExtractionOutput:
        nonlocal llm_calls
        llm_calls += 1
        if llm_calls == 1:
            raise LLMRateLimitError(retry_after=1.0)
        return SceneEntityExtractionOutput()

    async def on_scene_progress(completed: int, total: int) -> None:
        progress_events.append((completed, total))

    monkeypatch.setattr(
        "modules.imports.entity_extraction.scene_entity_parallel."
        "phase2_parallel_scene_concurrency",
        lambda: 4,
    )
    with (
        patch.object(svc, "_load_scene_chapters", autospec=True, side_effect=load_scene),
        patch.object(
            svc,
            "_create_phase2_snapshot",
            autospec=True,
            return_value=Mock(id=None),
        ),
        patch.object(svc, "_call_llm_extraction", autospec=True, side_effect=call_llm),
        patch.object(svc, "_persist_entities", autospec=True, return_value=0),
        patch.object(svc, "_record_deltas", autospec=True, return_value=0),
        _patched_phase2_summaries(svc),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await svc._process_scenes_parallel_llm(
            db_session,
            scenes[0]["novel_id"],
            scenes,
            "无已有对象",
            workflow_id="wf-rate-limit-throttle",
            on_scene_progress=on_scene_progress,
            bulk_error_kind="unified_activation:batched",
            include_alias_relations=False,
        )

    assert llm_calls == len(scenes)
    assert result["completed_scenes"] == len(scenes) - 1
    assert len(result["checkpoints"]["phase2"]["scenes"]) == len(scenes)
    assert len(result["failed_scene_indices"]) == 1
    assert progress_events[-1] == (len(scenes), len(scenes))
    assert [completed for completed, _total in progress_events] == list(
        range(1, len(scenes) + 1)
    )
    assert result["phase2_throttle_reasons"] == ["rate_limit_window"]


@pytest.mark.asyncio
async def test_phase2_batched_progress_callback_uses_db_lock() -> None:
    svc = SceneEntityExtractionService()
    db = Mock()
    db_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    progress_lock_states: list[bool] = []
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in (1, 2)
    ]

    async def process_scene(*_args, **kwargs):
        assert kwargs["db_lock"] is db_lock
        return {
            "created": 1,
            "relations": 0,
            "deltas": 0,
            "created_entity_ids": [],
            "created_relation_ids": [],
            "created_delta_ids": [],
            "updated_context": "updated",
            "updated_memory": [],
        }

    async def on_scene_progress(_completed: int, _total: int) -> None:
        progress_lock_states.append(db_lock.locked())

    with (
        patch.object(
            svc,
            "_process_scene",
            autospec=True,
            side_effect=process_scene,
        ),
        patch.object(
            svc,
            "_current_scene_input_fingerprint",
            autospec=True,
            return_value="batched-fingerprint",
        ),
    ):
        result = await svc._process_scene_batch_serial(
            db,
            "00000000-0000-0000-0000-000000000001",
            scenes,
            batch_index=0,
            existing_context="无已有对象",
            workflow_id="wf-phase2-lock",
            completed_counter={"value": 0},
            progress_lock=progress_lock,
            db_lock=db_lock,
            total_scenes=len(scenes),
            on_scene_progress=on_scene_progress,
        )

    assert result["created"] == 2
    assert progress_lock_states == [True, True]
    assert all(
        checkpoint["input_fingerprint"] == "batched-fingerprint"
        for checkpoint in result["checkpoints"]
    )


@pytest.mark.asyncio
async def test_phase2_batched_failed_batch_records_scene_ids_and_fallback_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE2_BATCH_SIZE_SCENES", "12")
    monkeypatch.setenv("PHASE2_BATCH_CONCURRENCY", "6")
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "novel_id": "novel-1",
            "scene_index": 0,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 14)
    ]
    db = Mock()

    async def process_batch(*_args, **kwargs):
        if kwargs["batch_index"] == 0:
            raise RuntimeError("session state changed")
        return {
            "created": 1,
            "relations": 0,
            "deltas": 0,
            "failed_scene_indices": [],
            "failed_scene_ids": [],
            "checkpoints": [],
            "degraded": False,
            "error_kind": None,
            "error_message": None,
            "persistence_stats": svc._empty_phase2_persistence_stats(),
        }

    with (
        patch.object(
            svc,
            "_process_scene_batch_serial",
            autospec=True,
            side_effect=process_batch,
        ),
        patch.object(
            svc,
            "_run_boundary_supplements",
            autospec=True,
            return_value={
                "phase2_boundary_windows_total": 1,
                "phase2_boundary_windows_completed": 0,
                "phase2_boundary_supplement_counts": {
                    "created": 0,
                    "aliases": 0,
                    "relations": 0,
                    "link_suggestions": 0,
                    "conflicts": 0,
                    "failed": 0,
                },
                "degraded": False,
                "error_kind": None,
                "error_message": None,
            },
        ),
        patch.object(
            svc,
            "_phase2_flush_with_timeout",
            autospec=True,
            return_value={"degraded": False, "error_kind": None, "error_message": None},
        ),
        _patched_phase2_summaries(svc),
        patch.object(
            svc,
            "_phase2_alias_relation_result",
            autospec=True,
            return_value=svc._skipped_alias_relation_result(13, reason="test"),
        ),
    ):
        result = await svc._process_scenes_batched(
            db,
            "00000000-0000-0000-0000-000000000001",
            scenes,
            "无已有对象",
            workflow_id="wf-phase2-failed-batch",
            on_scene_progress=None,
        )

    assert result["phase2_failed_batches"] == [0]
    assert result["failed_scene_indices"] == list(range(1, 13))
    assert result["failed_scene_ids"] == [f"scene-{index}" for index in range(1, 13)]


@pytest.mark.asyncio
async def test_bulk_llm_extractions_keep_successful_groups_when_one_group_fails() -> None:
    svc = SceneEntityExtractionService()
    output = SceneEntityExtractionOutput(
        entities=[
            ExtractedEntity(
                name="克莱恩",
                entity_type="character",
                suggested_action="create_new",
            )
        ],
        relations=[],
        delta_events=[],
    )

    async def call_llm(chapters_text: str, *_args, **_kwargs):
        if "Scene 4" in chapters_text:
            raise TimeoutError("slow group")
        return output

    with patch.object(
        svc,
        "_call_llm_extraction",
        autospec=True,
        side_effect=call_llm,
    ):
        results = await svc._call_bulk_llm_extractions(
            [f"Scene {index}" for index in range(1, 7)],
            "无已有对象",
            "批量上下文",
        )

    assert len(results) == 5
    assert all(result == output for result in results)


@pytest.mark.asyncio
async def test_bulk_llm_extractions_use_fast_no_retry_calls() -> None:
    svc = SceneEntityExtractionService()
    output = SceneEntityExtractionOutput(
        entities=[],
        relations=[],
        delta_events=[],
    )
    calls: list[dict] = []

    async def call_llm(_chapters_text: str, *_args, **kwargs):
        calls.append(kwargs)
        return output

    with patch.object(
        svc,
        "_call_llm_extraction",
        autospec=True,
        side_effect=call_llm,
    ):
        await svc._call_bulk_llm_extractions(
            ["Scene 1"],
            "无已有对象",
            "批量上下文",
        )

    assert calls == [
        {
            "max_tokens": scene_entity_extraction_module.PHASE2_BULK_MAX_TOKENS,
            "client_timeout": (
                scene_entity_extraction_module.PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS
            ),
            "max_fix_attempts": 0,
            "transport_retries": False,
            "diagnostics": [],
        }
    ]


@pytest.mark.asyncio
async def test_bulk_scene_entity_extractor_prefetches_scene_drafts_once() -> None:
    scenes = [
        {
            "id": "scene-1",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1", "2"],
        },
        {
            "id": "scene-2",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2", "3"],
        },
    ]
    calls: list[tuple[str, list[int]]] = []

    async def list_latest_drafts_for_chapters(_db, novel_id, chapter_indices):
        calls.append((novel_id, list(chapter_indices)))
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=index,
                title=f"第{index}章",
                content=f"第{index}章正文",
            )
            for index in chapter_indices
        ]

    service = Mock()
    service._scene_source_chapter_index.return_value = 1
    service._scene_chunks_by_chapter.side_effect = scene_chunks_by_chapter
    service._scene_chapter_ids.side_effect = scene_chapter_ids
    service._select_scene_text.side_effect = select_scene_text
    service._scene_context_header.side_effect = scene_context_header
    service._bulk_entity_memory_context.return_value = "批量上下文"
    service._create_phase2_snapshot = AsyncMock(return_value=Mock(id="snapshot-1"))
    service._call_bulk_llm_extractions = AsyncMock(
        return_value=[SceneEntityExtractionOutput()]
    )
    service._persist_entities = AsyncMock(return_value=0)
    service._persist_relations = AsyncMock(return_value=0)
    service._record_deltas = AsyncMock(return_value=0)
    service._scene_id.return_value = "scene-1"
    service._scene_provenance_key.return_value = "wf:scene-1"
    service._result_ref_ids.return_value = []
    service._load_scene_chapters = AsyncMock(
        side_effect=AssertionError("bulk extractor should prefetch drafts once")
    )

    with (
        patch(
            "modules.writing.facade.list_latest_drafts_for_chapters",
            autospec=True,
            side_effect=list_latest_drafts_for_chapters,
        ),
        patch("modules.context.facade.succeed_context_snapshot", autospec=True),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await BulkSceneEntityExtractor(service).run(
            Mock(),
            "novel-1",
            scenes,
            "无已有对象",
            workflow_id="wf-bulk",
        )

    assert result["created"] == 0
    assert calls == [("novel-1", [1, 2, 3])]
    service._load_scene_chapters.assert_not_awaited()
    service._call_bulk_llm_extractions.assert_awaited_once()
    scene_texts = service._call_bulk_llm_extractions.await_args.args[0]
    assert "第1章正文" in scene_texts[0]
    assert "第2章正文" in scene_texts[0]
    assert "第2章正文" in scene_texts[1]
    assert "第3章正文" in scene_texts[1]


@pytest.mark.asyncio
async def test_bulk_map_proposals_keep_their_source_scene_provenance() -> None:
    scenes = [
        {
            "id": "scene-1",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-2",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]

    async def list_latest_drafts_for_chapters(_db, novel_id, chapter_indices):
        return [
            WritingDraftContract(
                novel_id=novel_id,
                chapter_index=index,
                title=f"第{index}章",
                content=f"第{index}章正文",
            )
            for index in chapter_indices
        ]

    outputs = [
        SceneEntityExtractionOutput(
            map_observation_proposals=[
                ExtractedCharacterLocationProposal(
                    proposal_type="character_location",
                    character_name="沈砚",
                    location_name=f"地点{index}",
                    quote=f"沈砚到达地点{index}。",
                    confidence=0.9,
                )
            ]
        )
        for index in (1, 2)
    ]
    service = Mock()
    service._scene_source_chapter_index.side_effect = lambda scene: scene["scene_index"]
    service._scene_chunks_by_chapter.side_effect = scene_chunks_by_chapter
    service._scene_chapter_ids.side_effect = scene_chapter_ids
    service._select_scene_text.side_effect = select_scene_text
    service._scene_context_header.side_effect = scene_context_header
    service._scene_input_fingerprint.side_effect = lambda scene, _text: (
        f"fingerprint-{scene['id']}"
    )
    service._bulk_entity_memory_context.return_value = "批量上下文"
    service._create_phase2_snapshot = AsyncMock(return_value=Mock(id="snapshot-1"))
    service._call_bulk_llm_extractions = AsyncMock(return_value=list(enumerate(outputs)))
    service._persist_entities = AsyncMock(return_value=0)
    service._persist_relations = AsyncMock(return_value=0)
    service._record_deltas = AsyncMock(return_value=0)
    service._record_map_observation_proposals = AsyncMock(
        return_value={"created": 1, "reused": 0}
    )
    service._scene_id.side_effect = lambda scene: scene["id"]
    service._scene_provenance_key.side_effect = lambda _workflow_id, scene: (
        f"wf:{scene['id']}"
    )
    service._result_ref_ids.return_value = []
    authorization_snapshot = {"authorization_confirmed": True}

    with (
        patch(
            "modules.writing.facade.list_latest_drafts_for_chapters",
            autospec=True,
            side_effect=list_latest_drafts_for_chapters,
        ),
        patch("modules.context.facade.succeed_context_snapshot", autospec=True),
        patch("modules.memory.facade.capture_snapshot", autospec=True),
    ):
        result = await BulkSceneEntityExtractor(service).run(
            Mock(),
            "novel-1",
            scenes,
            "无已有对象",
            workflow_id="wf-bulk",
            authorization_snapshot=authorization_snapshot,
        )

    calls = service._record_map_observation_proposals.await_args_list
    assert [call.kwargs["scene_id"] for call in calls] == ["scene-1", "scene-2"]
    assert [call.kwargs["scene_index"] for call in calls] == [1, 2]
    assert [call.kwargs["source_chapter_index"] for call in calls] == [1, 2]
    assert [call.kwargs["scene_source_fingerprint"] for call in calls] == [
        "fingerprint-scene-1",
        "fingerprint-scene-2",
    ]
    assert all(
        call.kwargs["authorization_snapshot"] is authorization_snapshot for call in calls
    )
    assert result["map_observation_candidates"] == {"created": 2, "reused": 0}


@pytest.mark.asyncio
async def test_small_sample_bulk_supplements_low_entity_count() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "title": f"关键 Scene {index}",
        }
        for index in range(8)
    ]
    created_payloads: list[dict] = []

    async def create_entity(_db, _novel_id, payload):
        created_payloads.append(payload)
        return {"id": f"entity-{len(created_payloads)}"}

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeDb:
        def begin_nested(self):
            return FakeSavepoint()

    with (
        patch(
            "modules.world.facade.create_entity",
            autospec=True,
            side_effect=create_entity,
        ),
        patch.object(
            svc,
            "_supplement_small_sample_entities_with_llm",
            autospec=True,
            return_value={"created": 0, "created_entity_ids": []},
        ),
    ):
        result = await svc._supplement_small_sample_entities(
            db=FakeDb(),
            nid="00000000-0000-0000-0000-000000000001",
            scenes=scenes,
            current_count=16,
            workflow_id="wf-phase2",
        )

    assert result == {
        "created": 2,
        "created_entity_ids": ["entity-1", "entity-2"],
        "supplemental_llm_created": 0,
        "fallback_created": 2,
        "supplemental_error_kind": None,
    }
    assert created_payloads[0]["content_json"]["_meta"]["needs_review"] is True
    assert (
        created_payloads[0]["content_json"]["_meta"]["fallback"]
        == "small_sample_entity_minimum"
    )
    assert created_payloads[0]["status"] == "candidate"


@pytest.mark.asyncio
async def test_small_sample_bulk_uses_llm_supplement_before_fallback() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "title": f"关键 Scene {index}",
            "chapter_ids": [str(index)],
            "novel_id": "novel-1",
        }
        for index in range(1, 9)
    ]

    with patch.object(
        svc,
        "_supplement_small_sample_entities_with_llm",
        autospec=True,
        return_value={
            "created": 13,
            "created_entity_ids": [f"llm-entity-{index}" for index in range(13)],
        },
    ) as llm_supplement:
        result = await svc._supplement_small_sample_entities(
            db=Mock(),
            nid="00000000-0000-0000-0000-000000000001",
            scenes=scenes,
            current_count=16,
            workflow_id="wf-phase2",
        )

    llm_supplement.assert_awaited_once()
    assert result["created"] == 13
    assert result["supplemental_llm_created"] == 13
    assert result["fallback_created"] == 0
    assert result["created_entity_ids"][0] == "llm-entity-0"


@pytest.mark.asyncio
async def test_small_sample_supplement_includes_review_entities_for_dedup() -> None:
    svc = SceneEntityExtractionService()
    svc._load_small_sample_chapters_text = AsyncMock(return_value="chapter text")
    svc._call_llm_extraction = AsyncMock(return_value=SimpleNamespace(entities=[]))
    svc._persist_entities = AsyncMock(return_value=0)
    world_context = AsyncMock(return_value=SimpleNamespace(entities=[]))
    nid = uuid.uuid4()
    db = Mock()

    with patch(
        "modules.world.facade.get_world_context",
        autospec=True,
        side_effect=world_context,
    ):
        result = await BulkSceneEntityExtractor(svc).supplement_with_llm(
            db,
            nid,
            [{"chapter_ids": ["1"]}],
            needed=3,
            workflow_id="wf-review-dedup",
        )

    assert result == {"created": 0, "created_entity_ids": []}
    world_context.assert_awaited_once_with(
        db,
        str(nid),
        reveal_mode="author_safe",
        limit=500,
        include_review=True,
    )


@pytest.mark.asyncio
async def test_small_sample_supplement_timeout_falls_back(monkeypatch) -> None:
    import modules.imports.entity_extraction as public_module

    monkeypatch.setattr(
        public_module,
        "PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS",
        0.01,
    )
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "title": f"关键 Scene {index}",
            "chapter_ids": [str(index)],
            "novel_id": "novel-1",
        }
        for index in range(1, 9)
    ]
    created_payloads: list[dict] = []

    async def slow_supplement(*_args, **_kwargs):
        await asyncio.Event().wait()
        return {"created": 1, "created_entity_ids": ["too-late"]}

    async def create_entity(_db, _novel_id, payload):
        created_payloads.append(payload)
        return {"id": f"entity-{len(created_payloads)}"}

    class FakeSavepoint:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeDb:
        def begin_nested(self):
            return FakeSavepoint()

    with (
        patch.object(
            svc,
            "_supplement_small_sample_entities_with_llm",
            autospec=True,
            side_effect=slow_supplement,
        ),
        patch(
            "modules.world.facade.create_entity",
            autospec=True,
            side_effect=create_entity,
        ),
    ):
        result = await svc._supplement_small_sample_entities(
            db=FakeDb(),
            nid="00000000-0000-0000-0000-000000000001",
            scenes=scenes,
            current_count=16,
            workflow_id="wf-phase2",
        )

    assert result["supplemental_llm_created"] == 0
    assert result["fallback_created"] == 2
    assert result["supplemental_error_kind"] == "timeout"
    assert result["created_entity_ids"] == ["entity-1", "entity-2"]
    assert created_payloads[0]["content_json"]["_meta"]["needs_review"] is True


def test_trim_supplement_chapter_text_keeps_head_and_tail() -> None:
    chapter_text = "A" * 5000 + "MIDDLE" + "Z" * 5000

    trimmed = SceneEntityExtractionService._trim_supplement_chapter_text(chapter_text)

    assert len(trimmed) < len(chapter_text)
    assert trimmed.startswith("A" * 100)
    assert trimmed.endswith("Z" * 100)
    assert "章节中段已压缩" in trimmed


def test_bulk_entity_memory_context_adds_1_to_7_recall_guidance() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": f"scene-{index}",
            "scene_index": index,
            "chapter_ids": [str(index)],
        }
        for index in range(1, 8)
    ]

    context = svc._bulk_entity_memory_context(scenes)

    assert "整体目标应接近 24-32 个长期资产" in context
    assert "主要人物及别名" in context
    assert "神秘学概念/力量体系" in context


def test_bulk_entity_memory_context_keeps_generic_guidance_for_other_ranges() -> None:
    svc = SceneEntityExtractionService()
    context = svc._bulk_entity_memory_context(
        [
            {
                "id": "scene-10",
                "scene_index": 10,
                "chapter_ids": ["10"],
            }
        ]
    )

    assert "小样本批量实体提取" in context
    assert "整体目标应接近 24-32 个长期资产" not in context


@pytest.mark.asyncio
async def test_phase2_recovery_skips_successful_scene_and_reruns_failed_scene() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-a",
            "novel_id": "novel-1",
            "scene_index": 1,
            "chapter_ids": ["1"],
        },
        {
            "id": "scene-b",
            "novel_id": "novel-1",
            "scene_index": 2,
            "chapter_ids": ["2"],
        },
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            autospec=True,
            return_value={
                "created": 1,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": ["entity-scene-b"],
                "created_relation_ids": [],
                "created_delta_ids": [],
                "updated_context": "updated",
                "updated_memory": [{"scene_index": 2, "entities": 1}],
            },
        ) as process_scene,
        patch.object(
            svc,
            "_current_scene_input_fingerprint",
            autospec=True,
            return_value="current-fingerprint",
        ),
        patch.object(svc, "_process_scenes_bulk", autospec=True) as bulk,
        patch.object(
            svc,
            "_process_scenes_parallel_llm",
            autospec=True,
        ) as parallel,
        patch.object(svc, "_process_scenes_batched", autospec=True) as batched,
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-recovery",
            existing_checkpoints={
                "phase2": {
                    "scenes": [
                        {
                            "scene_id": "scene-a",
                            "status": "done",
                            "retry_count": 0,
                            "input_fingerprint": "current-fingerprint",
                        },
                        {
                            "scene_id": "scene-b",
                            "status": "failed",
                            "retry_count": 0,
                            "input_fingerprint": "current-fingerprint",
                        },
                    ]
                }
            },
        )

    assert result["skipped_scenes"] == 1
    assert result["rerun_scenes"] == 1
    assert process_scene.await_count == 1
    bulk.assert_not_awaited()
    parallel.assert_not_awaited()
    batched.assert_not_awaited()
    processed_scene = process_scene.await_args.args[2]
    assert processed_scene["id"] == "scene-b"
    checkpoints = result["checkpoints"]["phase2"]["scenes"]
    assert checkpoints[0]["scene_id"] == "scene-a"
    assert checkpoints[0]["status"] == "skipped"
    assert checkpoints[1]["scene_id"] == "scene-b"
    assert checkpoints[1]["status"] == "done"
    assert checkpoints[1]["retry_count"] == 1


@pytest.mark.asyncio
async def test_phase2_failed_scene_checkpoint_contains_error_status() -> None:
    svc = SceneEntityExtractionService()
    scenes = [
        {
            "id": "scene-failed",
            "novel_id": "novel-1",
            "scene_index": 5,
            "chapter_ids": ["5"],
        }
    ]
    db = Mock()
    db.flush = AsyncMock()

    with (
        patch.object(svc, "_get_scenes", autospec=True, return_value=scenes),
        patch(
            "modules.world.facade.get_world_context",
            autospec=True,
            return_value=Mock(entities=[]),
        ),
        patch.object(
            svc,
            "_process_scene",
            autospec=True,
            side_effect=RuntimeError("phase2 boom"),
        ),
        _patched_phase2_summaries(svc),
    ):
        result = await svc.extract_by_scenes(
            db,
            "00000000-0000-0000-0000-000000000001",
            workflow_id="wf-phase2-failed",
            existing_checkpoints={"unrelated-scene": {"status": "done"}},
        )

    checkpoint = result["checkpoints"]["phase2"]["scenes"][0]
    assert checkpoint["scene_id"] == "scene-failed"
    assert checkpoint["status"] == "failed"
    assert checkpoint["error_kind"] == "RuntimeError"
    assert checkpoint["error"] == "phase2 boom"
