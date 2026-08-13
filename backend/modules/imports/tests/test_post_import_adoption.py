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
        "created": True,
    }
