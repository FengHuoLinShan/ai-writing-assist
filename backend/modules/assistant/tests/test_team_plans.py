"""Concrete plan selection precedes the existing author-confirmed batch."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import func, select

from core.config import get_settings
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.evidence_tools import fingerprint
from modules.assistant.models import AssistantActionBatch, AssistantRun
from modules.assistant.operations import prepare_actions
from modules.assistant.schemas import ProposedAction, WorkContext
from modules.writing.facade import create_draft_only, get_latest_draft_for_chapter


@pytest.mark.parametrize(
    "review_after,disabled",
    [
        (False, None),
        (True, None),
        (True, "assistant_cross_revision_enabled"),
        (True, "assistant_enabled"),
    ],
)
async def test_select_one_plan_compare_and_confirm_without_duplicate_writes(
    async_client,
    db_session,
    test_project_id,
    account_llm_connection,
    monkeypatch,
    review_after,
    disabled,
):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_cross_revision_enabled=True
    )
    monkeypatch.setattr("modules.assistant.service.get_settings", lambda: settings)
    draft = await create_draft_only(
        db_session, test_project_id, 1, content="门从外侧打开。"
    )
    await db_session.commit()
    session = (
        await async_client.post(
            "/api/assistant/sessions", json={"novel_id": test_project_id}
        )
    ).json()["id"]
    response = await async_client.post(
        f"/api/assistant/sessions/{session}/team-runs",
        json={
            "novel_id": test_project_id,
            "operation_id": str(uuid.uuid4()),
            "blueprint": "cross_revision",
            "message": "将开门方向改为内侧，保留人物获救",
            "context": {"page": "writing", "draft_id": draft.id, "chapter_index": 1},
        },
    )
    assert response.status_code == 202, response.text
    run = await db_session.get(AssistantRun, uuid.UUID(response.json()["id"]))
    work = WorkContext.model_validate(run.request_json["context"])
    prepared = await prepare_actions(
        db_session,
        test_project_id,
        [
            ProposedAction(
                key="rewrite",
                capability="writing.revise",
                title="调整开门方向",
                arguments={
                    "draft_id": draft.id,
                    "source_hash": draft.content_hash,
                    "replacements": [
                        {
                            "start": 0,
                            "end": 7,
                            "original": "门从外侧打开。",
                            "replacement": "门从内侧打开。",
                        }
                    ],
                },
            )
        ],
        context=AssistantOperationContext(str(run.id), str(current_account_id()), work),
    )
    plan = {
        "key": "minimal",
        "title": "最小修订",
        "preserves": ["人物获救"],
        "tradeoffs": [],
        "remaining_questions": [],
        "actions": prepared,
    }
    digest = fingerprint(plan)
    run.status = "completed"
    run.result_json = {
        "answer": "请选择",
        "plans": [{**plan, "fingerprint": digest}],
        "knowledge_review": {"status": "passed"},
    }
    await db_session.commit()
    selection = {
        "novel_id": test_project_id,
        "plan_key": "minimal",
        "expected_hash": digest,
    }
    url = f"/api/assistant/runs/{run.id}/select-plan"
    if disabled:
        settings = replace(settings, **{disabled: False})
        blocked = await async_client.post(url, json=selection)
        assert blocked.status_code == 409, blocked.text
        assert not await db_session.scalar(
            select(AssistantActionBatch).where(AssistantActionBatch.run_id == run.id)
        )
        settings = replace(settings, **{disabled: True})
    chosen = await async_client.post(url, json=selection)
    assert chosen.status_code == 200, chosen.text
    assert (
        await get_latest_draft_for_chapter(db_session, test_project_id, 1)
    ).content == "门从外侧打开。"
    replay = await async_client.post(url, json=selection)
    batch = chosen.json()["result"]["batch"]
    assert replay.json()["result"]["batch"]["id"] == batch["id"]
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AssistantActionBatch)
            .where(AssistantActionBatch.run_id == run.id)
        )
        == 1
    )
    decision = {
        "novel_id": test_project_id,
        "fingerprint": batch["fingerprint"],
        "selected": ["rewrite"],
        "confirmed": True,
        "review_after": review_after,
    }
    if disabled:
        settings = replace(settings, **{disabled: False})
    applied = await async_client.post(
        f"/api/assistant/batches/{batch['id']}/decide", json=decision
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "completed"
    if review_after and disabled:
        assert applied.json()["regression"]["status"] == "not_checked"
        assert not applied.json()["regression"]["references"]
        assert "已关闭" in applied.json()["regression"]["omissions"][0]
        assert (
            await db_session.scalar(select(func.count()).select_from(AssistantRun)) == 1
        )
    elif review_after:
        assert applied.json()["regression"]["references"]
        assert applied.json()["regression"]["status"] == "queued"
    latest = await get_latest_draft_for_chapter(db_session, test_project_id, 1)
    assert latest.content == "门从内侧打开。"
    await async_client.post(f"/api/assistant/batches/{batch['id']}/decide", json=decision)
    assert (
        await get_latest_draft_for_chapter(db_session, test_project_id, 1)
    ).id == latest.id
