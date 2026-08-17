from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from infrastructure.llm.errors import LLMTimeoutError
from modules.imports.workflow_entity_phase import EntityExtractionPhaseRunner
from modules.imports.workflow_schemas import DeepImportProgress


@pytest.mark.asyncio
async def test_phase2_dedup_provider_failure_preserves_entities_and_runs_phase2b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    emit_progress = AsyncMock(side_effect=lambda *_args: events.append("checkpoint"))
    extract_aliases = AsyncMock(
        return_value={
            "total_aliases": 1,
            "total_relations": 2,
            "alias_relation_scenes": 1,
            "alias_relation_failed_scenes": [],
            "degraded": False,
            "alias_relation_checkpoints": {"phase2b": {"scenes": []}},
        }
    )
    workflow = SimpleNamespace(
        _emit_progress=emit_progress,
        _extract_alias_relations_by_scene=extract_aliases,
        _merge_checkpoints=Mock(side_effect=lambda *_args: events.append("phase2b")),
    )
    runner = EntityExtractionPhaseRunner(workflow)
    db = AsyncMock()
    db.task_checkpoint_enabled = True
    db.task_inline_execution_enabled = False

    async def fail_dedup(*_args, **_kwargs):
        events.append("dedup")
        raise LLMTimeoutError("provider timeout")

    monkeypatch.setattr(
        "modules.world.facade.dedupe_deep_import_workflow_candidates",
        fail_dedup,
    )
    source = {
        "total_created": 2,
        "total_relations": 0,
        "total_aliases": 0,
        "alias_relation_skipped": True,
        "phase2_dedup_counts": {},
    }

    result = await runner._run_dedup_then_phase2b(
        db,
        "00000000-0000-0000-0000-000000000001",
        DeepImportProgress(llm_execution_snapshot={"provider": "test"}),
        source,
        workflow_id="workflow-1",
        on_scene_progress=None,
        on_progress=None,
        start_chapter=1,
        end_chapter=1,
        progress_start=0.5,
        progress_end=0.9,
    )

    assert events == ["dedup", "checkpoint", "phase2b"]
    assert result["total_created"] == 2
    assert result["total_aliases"] == 1
    assert result["total_relations"] == 2
    assert result["phase2_dedup"]["degraded"] is True
    assert result["phase2_dedup_counts"]["auto_merged"] == 0
