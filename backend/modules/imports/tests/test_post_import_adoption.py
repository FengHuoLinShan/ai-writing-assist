from __future__ import annotations

import hashlib

import pytest

from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.workflow_schemas import DeepImportProgress
from modules.world.contracts import PostImportWorldAdoptionResultContract


@pytest.mark.asyncio
async def test_post_import_package_uses_frozen_phase2_result_refs(monkeypatch) -> None:
    captured = {}

    async def assemble(_db, request):
        captured["request"] = request
        return PostImportWorldAdoptionResultContract(
            suggestion_id="package-1", created=True
        )

    monkeypatch.setattr(
        "modules.world.facade.assemble_post_import_adoption_package", assemble
    )
    source_hash = hashlib.sha256(b"scene").hexdigest()
    progress = DeepImportProgress(
        checkpoints={
            "phase2": {
                "scenes": [
                    {
                        "scene_id": "scene-1",
                        "input_fingerprint": source_hash,
                        "created_entity_ids": ["entity-1"],
                        "created_relation_ids": ["relation-1"],
                    }
                ]
            }
        }
    )

    await DeepImportOrchestrator._assemble_post_import_package(
        None,
        progress,
        {"authorization_snapshot": {"authorized_at": "2026-08-13T00:00:00Z"}},
        "novel-1",
        "workflow-1",
    )

    source = captured["request"].scene_sources[0]
    assert source.source_hash == source_hash
    assert source.entity_ids == ("entity-1",)
    assert source.relation_ids == ("relation-1",)
    assert progress.phase_artifacts["post_import_adoption_package"] == {
        "suggestion_id": "package-1",
        "suggestion_ids": ["package-1"],
        "created": True,
    }


@pytest.mark.parametrize("review_enabled", [False, True])
async def test_smart_resolution_does_not_reintroduce_blanket_adoption_queue(monkeypatch, review_enabled):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from modules.imports.adoption_policy import build_authorization_snapshot
    authorization=build_authorization_snapshot(novel_id="novel-1",start_chapter=1,end_chapter=1,adoption_policy="user_authorized_pipeline",authorization_confirmed=True)
    if review_enabled:
        authorization["review_resolution"]={"version":"imports.review_resolution.v1"}
    progress=DeepImportProgress(phase="done",review_resolution={"counts":{"optional":1}} if review_enabled else {})
    orchestrator=DeepImportOrchestrator()
    monkeypatch.setattr(orchestrator.workflow,"run_step",AsyncMock(return_value=progress))
    monkeypatch.setattr(orchestrator,"_restore_llm_execution_snapshot",AsyncMock(return_value={}))
    assemble=AsyncMock()
    monkeypatch.setattr(orchestrator,"_assemble_post_import_package",assemble)
    task=SimpleNamespace(id="task-1",result={},task_type="deep_import",meta={"novel_id":"novel-1","start_chapter":1,"end_chapter":1,"authorization_snapshot":authorization})
    await orchestrator.run_task(None,task)
    assert assemble.await_count == (0 if review_enabled else 1)
