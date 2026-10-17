"""Real guide persistence/DI paths, with no paid task submission."""

from dataclasses import replace
from uuid import uuid4

import pytest

from core.config import get_settings
from core.container import container_scope
from core.errors import ValidationError
from core.service_keys import (
    EVOLUTION_READ_MAP_COLD_START_STATUS,
    WORLD_READ_MAP_COLD_START_DRAFTS,
)
from modules.account.facade import current_account_id
from modules.assistant.guided_flow import runtime
from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest
from modules.assistant.models import AssistantRun
from modules.evolution import assistant_tools


@pytest.mark.asyncio
async def test_guide_persists_scope_and_never_retries_unknown(
    db_session, test_project_id, monkeypatch
):
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: replace(
            get_settings(),
            assistant_enabled=True,
            assistant_guided_flows_enabled=True,
            guided_flow_project_allowlist=(test_project_id,),
        ),
    )
    operation_id = str(uuid4())
    arguments = {"operation_id": operation_id, "end_chapter": 3, "discover_spatial": True}
    expected_args = assistant_tools.PrepareSpatialReading.model_validate(
        arguments
    ).model_dump(mode="json")
    progress = {
        "status": "needs_reconciliation",
        "request": {**expected_args, "expected_fingerprint": "a" * 64},
    }
    calls = []

    async def preview(*args, **kwargs):
        calls.append("preview")
        return {"fingerprint": "a" * 64, "request_limit": 20}

    async def status(db, novel_id, run_key, actual_operation):
        assert novel_id == test_project_id and actual_operation == operation_id
        calls.append("status")
        return {**progress, "run_key": run_key, "operation_id": actual_operation}

    async def drafts(*args):
        return {
            "batches_ready": True,
            "candidate_count": 0,
            "saved_node_count": 1,
            "truncated": False,
            "items": [],
        }

    async def forbidden(*args, **kwargs):
        pytest.fail("Guide must never start or resume paid work")

    monkeypatch.setattr(assistant_tools.workflow, "preview_reading", preview)
    monkeypatch.setattr(assistant_tools.workflow, "start_reading", forbidden)
    monkeypatch.setattr(assistant_tools.workflow, "resume_reading", forbidden)
    owner = str(current_account_id())
    with container_scope(
        {
            EVOLUTION_READ_MAP_COLD_START_STATUS: status,
            WORLD_READ_MAP_COLD_START_DRAFTS: drafts,
        }
    ):
        view = await runtime.start(
            db_session,
            test_project_id,
            owner,
            GuidedFlowStartRequest(novel_id=test_project_id, flow_id="map_cold_start"),
        )
        assert view["stop"]["step_id"] == "scope"
        run_id = view["run_id"]
        view = await runtime.advance(
            db_session,
            test_project_id,
            run_id,
            owner,
            {
                "choice": {
                    "step_id": "scope",
                    "action": "prepare_preview",
                    "capability": "evolution.prepare_spatial_reading",
                    "arguments": arguments,
                }
            },
        )
        assert view["stop"]["step_id"] == "authorization"
        assert view["panel"]["authorization_required"] is True
        view = await runtime.advance(
            db_session,
            test_project_id,
            run_id,
            owner,
            {
                "choice": {
                    "step_id": "authorization",
                    "action": "bind_authorized_run",
                    "run_key": "reading-scope",
                }
            },
        )
        assert view["stop"]["step_id"] == "monitor"
        assert "未知" in view["stop"]["reason"]
        view = await runtime.advance(
            db_session,
            test_project_id,
            run_id,
            owner,
            {"choice": {"step_id": "monitor", "action": "refresh"}},
        )
        assert view["stop"]["step_id"] == "monitor"
        assert calls.count("preview") == 1
        progress["status"] = "completed"
        view = await runtime.view(db_session, test_project_id, run_id, owner)
        assert view["stop"]["step_id"] == "locations"
        assert view["panel"]["location_adoption"]["cross_domain_atomic"] is False
        view = await runtime.advance(
            db_session,
            test_project_id,
            run_id,
            owner,
            {"choice": {"step_id": "locations", "action": "refresh"}},
        )
        assert view["stop"]["step_id"] == "locations"
        view = await runtime.advance(
            db_session,
            test_project_id,
            run_id,
            owner,
            {"choice": {"step_id": "locations", "action": "finish"}},
        )
        assert view["status"] == "completed"
        run = await db_session.get(AssistantRun, __import__("uuid").UUID(run_id))
        assert run.checkpoint_json["artifacts"]["scope"]["arguments"] == expected_args


@pytest.mark.asyncio
async def test_map_guide_respects_default_off_and_project_allowlist(
    db_session, test_project_id, monkeypatch
):
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: replace(
            get_settings(), assistant_enabled=True, assistant_guided_flows_enabled=False
        ),
    )
    with pytest.raises(ValidationError, match="尚未开启"):
        await runtime.start(
            db_session,
            test_project_id,
            str(current_account_id()),
            GuidedFlowStartRequest(novel_id=test_project_id, flow_id="map_cold_start"),
        )
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: replace(
            get_settings(),
            assistant_enabled=True,
            assistant_guided_flows_enabled=True,
            guided_flow_project_allowlist=(str(uuid4()),),
        ),
    )
    with pytest.raises(ValidationError, match="尚未向当前作品开放"):
        await runtime.start(
            db_session,
            test_project_id,
            str(current_account_id()),
            GuidedFlowStartRequest(novel_id=test_project_id, flow_id="map_cold_start"),
        )
