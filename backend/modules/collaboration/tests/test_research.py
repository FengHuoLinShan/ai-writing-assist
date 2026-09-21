"""Persisted web-read receipts, bounded allowance and unchanged edit authority."""

from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
from infrastructure.llm.agent_runtime import AgentRunBudget
from modules.collaboration import cases, research
from modules.collaboration.contracts import Grant, InputManifest, RunCreate
from modules.collaboration.models import CollaborationRun
from modules.collaboration.tests.test_workspaces import setup_trial


async def test_external_read_receipts_are_reused_and_do_not_grant_writes(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, test_project_id
    case, _, _, _ = await setup_trial(db, nid, monkeypatch)
    result = await cases.submit_run(
        db, nid, case["id"], RunCreate(operation_id=uuid4(), expected_goal_version=1)
    )
    run = await db.get(CollaborationRun, UUID(result["run_id"]))
    manifest = InputManifest.model_validate(run.manifest_json)
    grant = Grant.model_validate(case["grant"]).model_copy(update={"allow_web": True})
    budget = AgentRunBudget(policy_version="collaboration_v2")
    calls = []

    async def fence(**_kwargs):
        pass

    async def checkpoint(values):
        run.budget_json = values
        await db.commit()

    async def search(question, **kwargs):
        assert kwargs["private_texts"] and kwargs["protected_terms"]
        await kwargs["before_request"]()
        calls.append("search")
        return {"hits": [{"url": "https://example.org/facts"}], "omissions": []}

    async def read(url, **kwargs):
        await kwargs["before_request"]()
        calls.append("read")
        return {
            "url": url,
            "title": "物理资料",
            "text": "水的沸点随气压改变。",
            "text_hash": "a" * 64,
            "content_hash": "b" * 64,
            "retrieved_at": "2026-09-20T00:00:00+00:00",
        }

    monkeypatch.setattr(research, "require_search_snapshot", lambda _snapshot: None)
    monkeypatch.setattr(research, "search_public_fact", search)
    monkeypatch.setattr(research, "read_public_page", read)
    params = dict(
        grant=grant,
        snapshot={"protocol": "test-transport"},
        budget=budget,
        checkpoint=checkpoint,
        fence=fence,
    )
    output = await research.collect_web(
        db, nid, result["run_id"], ["气压如何影响水的沸点"], manifest, **params
    )
    external = output.resources[-1]
    assert external.kind == "external_reference" and external.read_range
    assert external.key not in {ref.key for ref in grant.resources}
    replay = await research.collect_web(
        db, nid, result["run_id"], ["气压如何影响水的沸点"], manifest, **params
    )
    assert replay == output and calls == ["search", "read"] and budget.web_requests == 2
    with pytest.raises(ConflictError, match="没有公开资料"):
        await research.collect_web(
            db,
            nid,
            result["run_id"],
            ["气压如何影响水的沸点"],
            manifest,
            **{**params, "grant": grant.model_copy(update={"allow_web": False})},
        )
