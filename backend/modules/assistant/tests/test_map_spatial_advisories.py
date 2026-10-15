from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.assistant_operation_registry import (
    assistant_spatial_advisory_operations,
    world_map_operations,
    writing_candidate_operations,
    writing_generation_operations,
)
from core.config import get_settings
from core.errors import ConflictError
from infrastructure.llm.agent_runtime import AgentRunBudget
from modules.account.facade import current_account_id
from modules.assistant import map_spatial_advisories as service
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import AssistantToolContext
from modules.assistant.schemas import WorkContext
from modules.world.tests.test_map_spatial_advisory_integration import seed


@pytest.mark.asyncio
async def test_v6_reader_reaches_real_world_and_silences_one_versioned_reminder(
    db_session, test_project_id, monkeypatch
):
    scene, node, revision, places, _ = await seed(db_session, test_project_id)
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: replace(
            get_settings(), map_spatial_enabled_capabilities=("assistant.turn",)
        ),
    )

    async def checkpoint(value):
        return None

    work = WorkContext(page="map", scope="project", scene_id=scene.id)
    deps = AssistantToolContext(
        db_session,
        test_project_id,
        str(current_account_id()),
        work,
        None,
        AgentRunBudget(),
        checkpoint,
    )
    result = await service.map_spatial_advisories(SimpleNamespace(deps=deps))
    assert len(result["items"]) == 1
    item = result["items"][0]
    paths = item["repair_paths"]
    assert paths[0]["capability"] in writing_generation_operations
    assert paths[0]["targeted_capability"] in writing_candidate_operations
    assert paths[1]["capability"] in world_map_operations
    assert paths[1]["base_revision_id"] == str(revision.id)
    evidence_id = item["evidence_id"]
    await deps.revalidate([evidence_id])
    operation = assistant_spatial_advisory_operations[
        "assistant.silence_spatial_advisory"
    ]
    args = operation.schema.model_validate(item["silence"]["arguments"])
    context = AssistantOperationContext(str(uuid4()), str(current_account_id()), work)
    preview = await operation.prepare(db_session, test_project_id, args, context=context)
    await operation.apply(db_session, test_project_id, args, preview, context=context)
    result = await service.map_spatial_advisories(SimpleNamespace(deps=deps))
    assert result["items"] == [] and result["silenced_count"] == 1
    # Silence does not modify the World revision or erase the underlying finding.
    assert node.current_revision_id == revision.id
    places[1].status = "candidate"
    await db_session.flush()
    with pytest.raises(ConflictError, match="变化"):
        await deps.revalidate([evidence_id])
