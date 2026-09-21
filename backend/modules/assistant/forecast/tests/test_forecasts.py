"""Saved-only reading, provider-only analysis, precise decisions and stale results."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime, service
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.models import AssistantNotice
from modules.writing.facade import create_draft_only


def settings_on(monkeypatch):
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_forecast_enabled=True,
        assistant_forecast_semantic_enabled=True,
    )
    for module in ("runtime", "service", "api", "policy"):
        monkeypatch.setattr(
            f"modules.assistant.forecast.{module}.get_settings", lambda: settings
        )


async def test_provider_only_forecast_read_decide_and_no_old_resurrection(
    async_client, db_session, test_project_id, account_llm_connection, monkeypatch
):
    settings_on(monkeypatch)
    db, nid = db_session, test_project_id
    draft = await create_draft_only(
        db, nid, 1, "小镇", "她把铜铃放进衣袋。铁匠欲言又止。"
    )
    focus = {
        "client_context_id": str(uuid4()),
        "focus_seq": 1,
        "page": "writing",
        "draft_id": draft.id,
        "expected_source_hash": draft.content_hash,
        "editor_state": "saved",
    }
    url = "/api/assistant/forecasts"
    before = await db.scalar(select(func.count()).select_from(AsyncTask))
    response = await async_client.post(
        f"{url}/feed", params={"novel_id": nid}, json={"context": focus}
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "not_checked"
    assert response.json()["references"][0]["resource_id"] == draft.id
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == before
    calls = []
    choices = []

    async def provider(self, request):
        assert not db.in_transaction()
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        calls.append(schema["title"])
        if schema["title"] == "ForecastOutput":
            inputs = json.loads(
                next(m.content for m in request.messages if m.role == "user")
            )
            assert inputs["author_decisions"] == choices
            value = {
                "items": [
                    {
                        "capability_index": 0,
                        "question_kind": "continuation",
                        "anchor_evidence_id": "source_0",
                        "anchor_text": "铁匠欲言又止",
                        "proposal": {
                            "title": "可以轻声追问，也可以先离开",
                            "kind": "creative_opportunity",
                            "statements": [
                                {
                                    "text": "铁匠欲言又止。",
                                    "basis": "observed",
                                    "evidence_ids": ["source_0"],
                                }
                            ],
                            "why_now": "主角仍在铁匠身边，可以回应这一反应。",
                            "directions": [
                                {
                                    "direction_id": "light_touch",
                                    "title": "轻量回应",
                                    "condition": "如果想保持局部节奏",
                                    "proposal": "让她留下一句询问，不急于解释铜铃。",
                                    "narrative_commitment": "low",
                                    "may_leave_open": True,
                                }
                            ],
                            "unknowns": ["铜铃也可能只是普通遗物"],
                            "verdict": "propose",
                        },
                    }
                ]
            }
        else:
            assert schema["title"] == "AuditVerdictOutput"
            value = {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_rules", "outline")
                ],
            }
        return LLMCallResponse(
            content=json.dumps(value, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    body = {
        "operation_id": str(uuid4()),
        "context": focus,
        "horizon": {"unit": "scene"},
        "requested_capabilities": ["writing.next_beat.v1"],
    }
    response = await async_client.post(
        f"{url}/evaluate", params={"novel_id": nid}, json=body
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    from modules.assistant.models import AssistantRun

    run = await db.get(AssistantRun, UUID(run_id))
    original_compute_key = run.request_json["compute_key"]
    task = await db.get(AsyncTask, run.task_id)
    await runtime.execute(db, task)
    response = await async_client.post(
        f"{url}/feed",
        params={"novel_id": nid},
        json={"context": {**focus, "editor_state": "dirty", "focus_seq": 2}},
    )
    assert response.status_code == 200, response.text
    candidate = response.json()["items"][0]
    assert candidate["basis_label"].startswith("基于上次保存")
    assert calls == ["ForecastOutput", "AuditVerdictOutput"]
    prepare_body = {
        "operation_id": str(uuid4()),
        "expected_assessment_hash": candidate["assessment_hash"],
        "action_id": "project.prepare_task",
        "context": focus,
    }
    from modules.assistant.models import AssistantActionBatch
    from modules.project.models import ProjectAuthorTask

    task_count = await db.scalar(select(func.count()).select_from(ProjectAuthorTask))
    preview = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/prepare",
        params={"novel_id": nid},
        json=prepare_body,
    )
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    assert (
        preview["status"] == "preview_ready"
        and preview["domain_write_performed"] is False
    )
    assert (
        await db.scalar(select(func.count()).select_from(ProjectAuthorTask)) == task_count
    )
    replay = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/prepare",
        params={"novel_id": nid},
        json=prepare_body,
    )
    assert replay.json()["batch_id"] == preview["batch_id"]
    assert await db.scalar(select(func.count()).select_from(AssistantActionBatch)) == 1
    adopted = await async_client.post(
        f"/api/assistant/batches/{preview['batch_id']}/decide",
        json={
            "novel_id": nid,
            "fingerprint": preview["batch_fingerprint"],
            "confirmed": True,
            "selected": ["selected"],
        },
    )
    assert adopted.status_code == 200, adopted.text
    assert adopted.json()["status"] == "completed"
    assert (
        await db.scalar(select(func.count()).select_from(ProjectAuthorTask))
        == task_count + 1
    )
    assert calls == ["ForecastOutput", "AuditVerdictOutput"]
    decision = {
        "expected_notice_version": candidate["notice_version"],
        "expected_assessment_hash": candidate["assessment_hash"],
        "action": "as_ordinary_detail",
    }
    response = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/decision",
        params={"novel_id": nid},
        json=decision,
    )
    assert response.status_code == 200, response.text
    assert response.json()["domain_state_changed"] is False
    response = await async_client.post(
        f"{url}/candidates/{candidate['candidate_id']}/decision",
        params={"novel_id": nid},
        json=decision,
    )
    assert response.status_code == 409
    notice = await db.scalar(
        select(AssistantNotice).where(AssistantNotice.novel_id == UUID(nid))
    )
    assert notice.disposition == "as_ordinary_detail"
    repeated = await async_client.post(
        f"{url}/evaluate",
        params={"novel_id": nid},
        json={**body, "operation_id": str(uuid4())},
    )
    assert repeated.status_code == 202, repeated.text
    next_run = await db.get(AssistantRun, UUID(repeated.json()["run_id"]))
    choices = next_run.request_json["author_decisions"]
    assert choices[0]["disposition"] == "as_ordinary_detail"
    assert choices[0]["choice"]["question"] == "可以轻声追问，也可以先离开"
    assert next_run.request_json["compute_key"] != original_compute_key
    task = await db.get(AsyncTask, next_run.task_id)
    await runtime.execute(db, task)
    assert calls == ["ForecastOutput", "AuditVerdictOutput"] * 2
    new_row = await db.scalar(
        select(ForecastCandidate).where(
            ForecastCandidate.run_id == UUID(repeated.json()["run_id"])
        )
    )
    row = await db.get(ForecastCandidate, UUID(candidate["candidate_id"]))
    assert new_row.issue_key == row.issue_key
    await db.refresh(notice)
    assert notice.disposition == "as_ordinary_detail"
    from modules.assistant.forecast.contracts import DecisionRequest

    await service.decide(
        db,
        nid,
        new_row.id,
        DecisionRequest(
            expected_notice_version=notice.row_version,
            expected_assessment_hash=new_row.assessment_hash,
            action="reopen",
        ),
    )
    assert row.validation_state == "valid"
    new_row.validation_state = "stale"
    await db.flush()
    response = await async_client.post(
        f"{url}/feed", params={"novel_id": nid}, json={"context": focus}
    )
    assert response.json()["items"] == []
    assert calls == ["ForecastOutput", "AuditVerdictOutput"] * 2

    # Moving the same physical quotation keeps the issue; unrelated replacement
    # at that offset must not inherit a declined direction from a different issue.
    for quote, inherited in [("铁匠欲言又止", True), ("孩子买来新鞋子", False)]:
        content = "夜深了。她把铜铃放进衣袋。" + quote + "。"
        saved = await create_draft_only(db, nid, 1, "改过标题", content)
        start = content.index(quote)
        item = {
            "issue_key": "fresh-issue",
            "capability_id": row.capability_id,
            "payload": {
                "anchor": {
                    **row.payload_json["anchor"],
                    "resource_id": saved.id,
                    "start": start,
                    "end": start + len(quote),
                }
            },
        }
        next_run = await db.get(AssistantRun, UUID(repeated.json()["run_id"]))
        identity = await service.inherit_issue_identity(db, next_run, item, {})
        assert (identity == row.issue_key) is inherited


async def test_dirty_compute_and_spoofed_automatic_trigger_are_rejected(
    async_client, db_session, test_project_id, monkeypatch
):
    settings_on(monkeypatch)
    draft = await create_draft_only(
        db_session, test_project_id, 1, "草稿", "普通的一天。"
    )
    body = {
        "operation_id": str(uuid4()),
        "context": {
            "client_context_id": str(uuid4()),
            "focus_seq": 0,
            "page": "writing",
            "draft_id": draft.id,
            "editor_state": "dirty",
        },
        "horizon": {"unit": "scene"},
    }
    response = await async_client.post(
        "/api/assistant/forecasts/evaluate",
        params={"novel_id": test_project_id},
        json=body,
    )
    assert response.status_code == 422
    body["context"]["editor_state"] = "saved"
    body["trigger"] = "saved_change"
    response = await async_client.post(
        "/api/assistant/forecasts/evaluate",
        params={"novel_id": test_project_id},
        json=body,
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "page", ["today", "project", "account", "imports", "world", "map", "rag", "assistant"]
)
async def test_domain_receipts_are_pure_reads_and_deterministic_calculation(
    db_session, test_project_id, page
):
    from modules.assistant.forecast.context import materialize
    from modules.assistant.forecast.contracts import FocusRequest
    from modules.assistant.forecast.deterministic import calculate
    from modules.assistant.forecast.registry import CAPABILITIES

    before = await db_session.scalar(select(func.count()).select_from(AsyncTask))
    focus = FocusRequest(client_context_id=uuid4(), focus_seq=1, page=page)
    context = await materialize(db_session, test_project_id, focus)
    rows, missing = calculate(context, list(CAPABILITIES))
    assert "account.cost_gate.v1" not in missing
    assert any(row["capability_id"] == "account.cost_gate.v1" for row in rows)
    assert await db_session.scalar(select(func.count()).select_from(AsyncTask)) == before
    assert (await materialize(db_session, test_project_id, focus)).scope == context.scope
