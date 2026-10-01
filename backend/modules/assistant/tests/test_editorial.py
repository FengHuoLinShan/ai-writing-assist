"""Editorial advice stays source-bound and separate from manuscript adoption."""

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.llm.schemas import LLMUsage
from infrastructure.llm.workflow_budget import current_workflow_budget
from infrastructure.tasks.models import AsyncTask
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.assistant import editorial, editorial_queue, proactive
from modules.assistant.editorial_contracts import RecheckOutput, ReviewPass
from modules.assistant.editorial_models import EditorialIssue, EditorialReview
from modules.assistant.models import AssistantRun, AssistantWatch
from modules.writing.models import WritingDraft


@pytest.mark.asyncio
async def test_brief_version_and_ready_marker_are_author_confirmed(
    async_client, db_session
):
    project = (
        await async_client.post("/api/projects", json={"title": "编辑测试"})
    ).json()
    novel_id = project["id"]
    brief_url = f"/api/projects/{novel_id}/editorial-brief"
    assert (await async_client.get(brief_url)).json()["version"] == 0
    body = {"expected_version": 0, "brief": {"voice": "保留第一人称的迟疑"}}
    saved = await async_client.put(brief_url, json=body)
    assert saved.status_code == 200 and saved.json()["version"] == 1
    assert (await async_client.put(brief_url, json=body)).status_code == 409

    draft = (
        await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "她推开门，看到一盏没有点亮的灯。",
            },
        )
    ).json()
    ready_url = f"/api/writing/drafts/{draft['id']}/editorial-ready?novel_id={novel_id}"
    bad = await async_client.post(ready_url, json={"expected_content_hash": "0" * 64})
    assert bad.status_code == 409
    first = await async_client.post(
        ready_url, json={"expected_content_hash": draft["content_hash"]}
    )
    second = await async_client.post(
        ready_url, json={"expected_content_hash": draft["content_hash"]}
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["editorial_ready_at"].removesuffix("Z") == second.json()[
        "editorial_ready_at"
    ].removesuffix("Z")
    assert first.json()["status"] == "draft"
    assert (
        await db_session.scalar(
            select(AssistantWatch).where(AssistantWatch.novel_id == UUID(novel_id))
        )
        is None
    )

    changed = await async_client.put(
        f"/api/writing/drafts/{draft['id']}?novel_id={novel_id}",
        json={"content": "她推开门，灯已经亮了。"},
    )
    assert changed.status_code == 200
    assert changed.json()["editorial_ready_hash"] != changed.json()["content_hash"]
    assert (
        await async_client.post(
            ready_url, json={"expected_content_hash": draft["content_hash"]}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_book_manifest_and_exact_quote_guard(async_client, db_session, monkeypatch):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    project = (
        await async_client.post("/api/projects", json={"title": "长篇测试"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = (
        await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": text,
            },
        )
    ).json()
    await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "content": "第三章：她才找到旧港。",
        },
    )
    operation_id = str(uuid4())
    request = {
        "novel_id": novel_id,
        "operation_id": operation_id,
        "scope": "book",
        "expected_brief_version": 0,
        "dimensions": ["structure"],
    }
    submitted = await async_client.post("/api/assistant/editorial/reviews", json=request)
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()
    assert result["status"] == "queued"
    assert result["missing"] == [{"chapter_index": 2, "reason": "missing"}]
    assert [item["chapter_index"] for item in result["sources"]] == [1, 3]
    replay = await async_client.post("/api/assistant/editorial/reviews", json=request)
    assert replay.status_code == 200 and replay.json()["id"] == result["id"]
    stopped = await async_client.post(
        f"/api/assistant/editorial/reviews/{result['id']}/stop",
        params={"novel_id": novel_id},
    )
    assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
    resumed = await async_client.post(
        f"/api/assistant/editorial/reviews/{result['id']}/resume",
        params={"novel_id": novel_id},
    )
    assert resumed.status_code == 200 and resumed.json()["status"] == "queued"
    assert resumed.json()["task_id"] != result["task_id"]
    assert (
        await async_client.post(
            "/api/assistant/editorial/reviews",
            json={
                **request,
                "scope": "chapter",
                "start_chapter": 1,
            },
        )
    ).status_code == 409

    review = await db_session.get(EditorialReview, UUID(result["id"]))
    context = await editorial._materialize_context(db_session, review, 1)
    assert not context["items"]
    assert context["fingerprint"]
    valid = ReviewPass.model_validate(
        {
            "findings": [
                {
                    "category": "structure",
                    "judgment": "地址的揭示可能太早",
                    "reader_impact": "读者可能提前猜到港口位置",
                    "severity": "high",
                    "evidence": [{"chapter_index": 1, "quote": "地址指向旧港"}],
                    "intent_relation": "作者要求先揭示地点",
                    "intent_quote": "先揭示地点",
                    "directions": [
                        {
                            "approach": "在发现地址前增加一次核对",
                            "affected_chapters": [1, 2],
                            "tradeoff": "前段节奏可能变慢",
                        }
                    ],
                }
            ]
        }
    )
    accepted = await editorial._validated_findings(
        db_session, review, valid, chapter=1, segment=text
    )
    assert accepted[0]["evidence"][0]["start"] == text.index("地址指向旧港")
    assert accepted[0]["authority"] == "editorial_suggestion"
    assert accepted[0]["severity"] == "medium"
    assert "未审章节：2" in accepted[0]["unchecked"]
    assert accepted[0]["intent_relation"] == ""
    assert "作者意图关联未能" in accepted[0]["unchecked"]
    assert (
        await editorial._validated_findings(
            db_session, review, valid, chapter=1, segment="未包含引文的片段"
        )
    ) == []
    assert (
        await editorial._validated_findings(
            db_session, review, valid, allowed_quotes=set()
        )
    ) == []
    await editorial._save_findings(db_session, review, accepted)
    issues = (
        await async_client.get(
            "/api/assistant/editorial/issues", params={"novel_id": novel_id}
        )
    ).json()
    assert len(issues) == 1
    assert issues[0]["finding"]["authority"] == "editorial_suggestion"
    decision = await async_client.put(
        f"/api/assistant/editorial/issues/{issues[0]['id']}",
        json={
            "novel_id": novel_id,
            "expected_version": issues[0]["version"],
            "disposition": "intentional",
            "note": "本轮故意让读者先知道地点",
        },
    )
    assert decision.status_code == 200
    receipt = decision.json()[0]["decisions"][0]
    assert receipt["review_id"] == result["id"]
    assert receipt["brief_version"] == 0
    assert receipt["evidence"][0]["content_hash"] == draft["content_hash"]
    other_project = (
        await async_client.post("/api/projects", json={"title": "另一部作品"})
    ).json()
    assert (
        await async_client.get(
            f"/api/assistant/editorial/reviews/{result['id']}",
            params={"novel_id": other_project["id"]},
        )
    ).status_code == 404
    assert (
        await async_client.put(
            f"/api/assistant/editorial/issues/{issues[0]['id']}",
            json={
                "novel_id": other_project["id"],
                "expected_version": 1,
                "disposition": "later",
            },
        )
    ).status_code == 404
    assert (
        await async_client.put(
            f"/api/assistant/editorial/issues/{issues[0]['id']}",
            json={
                "novel_id": novel_id,
                "expected_version": issues[0]["version"],
                "disposition": "closed",
            },
        )
    ).status_code == 409
    current = await db_session.get(WritingDraft, UUID(draft["id"]))
    assert current.content == text
    assert current.content_hash == hashlib.sha256(text.encode()).hexdigest()
    foreign = uuid4()
    token = bind_principal(
        AccountPrincipal(
            account_id=foreign,
            status="active",
            identity_type="email",
            support_code="editorial-foreign-" + foreign.hex[:8],
        )
    )
    try:
        for path in (
            f"/api/projects/{novel_id}/editorial-brief",
            f"/api/assistant/editorial/reviews/{result['id']}?novel_id={novel_id}",
            f"/api/assistant/editorial/issues?novel_id={novel_id}",
            f"/api/assistant/editorial/policy?novel_id={novel_id}",
        ):
            assert (await async_client.get(path)).status_code == 404
        assert (
            await async_client.post(
                f"/api/writing/drafts/{draft['id']}/editorial-ready?novel_id={novel_id}",
                json={"expected_content_hash": draft["content_hash"]},
            )
        ).status_code == 404
    finally:
        reset_principal(token)


@pytest.mark.asyncio
async def test_worker_keeps_advice_out_of_draft_and_marks_changed_source_stale(
    async_client, db_session, monkeypatch
):
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_editorial_enabled=True,
        assistant_editorial_automatic_enabled=True,
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)
    monkeypatch.setattr(editorial_queue, "get_settings", lambda: settings)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    @asynccontextmanager
    async def client(_db, _novel_id, _snapshot):
        yield type("Client", (), {"model_name": "test"})()

    async def model(_client, request, _schema, **_kwargs):
        payload = json.loads(request.messages[1].content)
        return ReviewPass.model_validate(
            {
                "summary": "本章保留地址线索。",
                "findings": [
                    {
                        "category": "structure",
                        "judgment": "地址线索或许揭示过早",
                        "reader_impact": "读者可能过早猜到目的地",
                        "severity": "high",
                        "evidence": [
                            {
                                "chapter_index": payload["chapter_index"],
                                "quote": "地址指向旧港",
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(editorial, "open_project_snapshot_llm_client", client)
    monkeypatch.setattr(editorial, "run_managed_structured", model)

    async def empty_context(_db, _row, _chapter):
        return {"items": [], "omissions": [], "fingerprint": "empty"}

    monkeypatch.setattr(editorial, "_materialize_context", empty_context)
    project = (
        await async_client.post("/api/projects", json={"title": "执行测试"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = (
        await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": text,
            },
        )
    ).json()

    async def submit():
        response = await async_client.post(
            "/api/assistant/editorial/reviews",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid4()),
                "scope": "chapter",
                "start_chapter": 1,
                "expected_brief_version": 0,
                "dimensions": ["structure"],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    first = await submit()
    task = await db_session.get(AsyncTask, UUID(first["task_id"]))
    db_session.task_checkpoint_enabled = True
    await editorial.execute(db_session, task)
    finished = await editorial.view(db_session, novel_id, UUID(first["id"]))
    assert finished["status"] == "completed"
    assert finished["report"]["top_findings"][0]["authority"] == "editorial_suggestion"
    assert finished["report"]["top_findings"][0]["fingerprint"]
    assert not finished["report"]["adoption_receipt"]
    assert (await db_session.get(WritingDraft, UUID(draft["id"]))).content == text

    second = await submit()
    changed = await async_client.put(
        f"/api/writing/drafts/{draft['id']}?novel_id={novel_id}",
        json={"content": "第一章：信上的地址指向新港。"},
    )
    assert changed.status_code == 200
    await db_session.commit()
    task = await db_session.get(AsyncTask, UUID(second["task_id"]))
    with pytest.raises(Exception, match="来源|工作稿"):
        await editorial.execute(db_session, task)
    stale = await editorial.view(db_session, novel_id, UUID(second["id"]))
    assert stale["status"] == "stale"
    stored = await db_session.get(
        EditorialReview, UUID(second["id"]), populate_existing=True
    )
    assert stored.status == "stale"
    assert not stale["report"]
    issue = (
        await async_client.get(
            "/api/assistant/editorial/issues", params={"novel_id": novel_id}
        )
    ).json()[0]
    requested = await async_client.post(
        f"/api/assistant/editorial/issues/{issue['id']}/recheck",
        json={
            "novel_id": novel_id,
            "operation_id": str(uuid4()),
            "expected_version": issue["version"],
        },
    )
    assert requested.status_code == 200, requested.text

    async def recheck_model(_client, _request, _schema, **_kwargs):
        return RecheckOutput(
            verdict="possibly_improved",
            reason="地址线索现在落在不同地点，需要作者确认效果",
            new_evidence=[{"chapter_index": 1, "quote": "地址指向新港"}],
        )

    monkeypatch.setattr(editorial, "run_managed_structured", recheck_model)
    recheck_task = await db_session.get(AsyncTask, UUID(requested.json()["task_id"]))
    await editorial.execute_recheck(db_session, recheck_task)
    updated = (
        await async_client.get(
            "/api/assistant/editorial/issues", params={"novel_id": novel_id}
        )
    ).json()[0]
    assert updated["rechecks"][-1]["verdict"] == "possibly_improved"
    assert updated["disposition"] == "open"
    assert (
        await db_session.get(WritingDraft, UUID(draft["id"]))
    ).content == changed.json()["content"]
    later_recheck = await async_client.post(
        f"/api/assistant/editorial/issues/{issue['id']}/recheck",
        json={
            "novel_id": novel_id,
            "operation_id": str(uuid4()),
            "expected_version": updated["version"],
        },
    )
    assert later_recheck.status_code == 200
    await db_session.commit()
    assert (
        await async_client.put(
            f"/api/projects/{novel_id}/editorial-brief",
            json={"expected_version": 0, "brief": {"voice": "改用更克制的叙述"}},
        )
    ).status_code == 200
    await db_session.commit()
    later_task = await db_session.get(AsyncTask, UUID(later_recheck.json()["task_id"]))
    with pytest.raises(ConflictError, match="原意见依据"):
        await editorial.execute_recheck(db_session, later_task)
    failed_recheck = (
        await async_client.get(
            "/api/assistant/editorial/issues", params={"novel_id": novel_id}
        )
    ).json()[0]
    assert failed_recheck["rechecks"][-1]["status"] == "failed"
    assert (
        await async_client.post(
            f"/api/assistant/editorial/issues/{issue['id']}/recheck",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid4()),
                "expected_version": updated["version"],
            },
        )
    ).status_code == 409
    await proactive._notice(
        db_session,
        UUID(novel_id),
        key=["editorial-old-source"],
        title="旧版地址线索",
        summary="核对旧版原文",
        sources=updated["finding"]["evidence"],
        result_ref={"type": "editorial_issue", "id": issue["id"]},
    )
    stored_issue = await db_session.get(EditorialIssue, UUID(issue["id"]))
    stored_issue.finding_json = {
        **stored_issue.finding_json,
        "evidence": [
            {
                **stored_issue.finding_json["evidence"][0],
                "content_hash": changed.json()["content_hash"],
                "quote": "地址指向新港",
            }
        ],
    }
    await db_session.flush()
    notices = await proactive.list_notices(db_session, novel_id)
    assert notices["items"][0]["needs_recheck"]
    assert (
        await async_client.put(
            "/api/assistant/editorial/policy",
            json={
                "novel_id": novel_id,
                "expected_generation": 0,
                "policy": {"enabled": True},
            },
        )
    ).status_code == 200
    from modules.assistant.facade import mark_changed

    await mark_changed(db_session, novel_id, "outline_scene", str(uuid4()))
    watch = await db_session.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(novel_id))
    )
    assert any(
        target["kind"] == "structure"
        for target in editorial_queue.pending(watch).values()
    )
    assert (await db_session.get(EditorialReview, UUID(first["id"]))).status == "stale"


@pytest.mark.asyncio
async def test_brief_change_before_execution_leaves_a_terminal_stale_review(
    async_client, db_session, monkeypatch
):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    novel_id = (
        await async_client.post("/api/projects", json={"title": "约定变化"})
    ).json()["id"]
    await async_client.post(
        "/api/writing/drafts/autosave",
        json={"novel_id": novel_id, "chapter_index": 1, "content": "第一章正文。"},
    )
    review = (
        await async_client.post(
            "/api/assistant/editorial/reviews",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid4()),
                "scope": "chapter",
                "start_chapter": 1,
                "expected_brief_version": 0,
                "dimensions": ["structure"],
            },
        )
    ).json()
    assert (
        await async_client.put(
            f"/api/projects/{novel_id}/editorial-brief",
            json={"expected_version": 0, "brief": {"voice": "改用更克制的叙述"}},
        )
    ).status_code == 200
    await db_session.commit()
    task = await db_session.get(AsyncTask, UUID(review["task_id"]))
    db_session.task_checkpoint_enabled = True
    with pytest.raises(ConflictError, match="编辑约定"):
        await editorial.execute(db_session, task)

    stored = await db_session.get(
        EditorialReview, UUID(review["id"]), populate_existing=True
    )
    assert (stored.status, stored.error) == ("stale", "编辑约定已变化")
    assert (await editorial.view(db_session, novel_id, stored.id))["status"] == "stale"
    with pytest.raises(ConflictError, match="不能续跑"):
        await editorial.resume(db_session, novel_id, stored.id)


@pytest.mark.asyncio
async def test_review_whose_task_died_becomes_resumable_on_read(
    async_client, db_session, monkeypatch
):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    novel_id = (
        await async_client.post("/api/projects", json={"title": "任务中断"})
    ).json()["id"]
    await async_client.post(
        "/api/writing/drafts/autosave",
        json={"novel_id": novel_id, "chapter_index": 1, "content": "第一章正文。"},
    )
    review = (
        await async_client.post(
            "/api/assistant/editorial/reviews",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid4()),
                "scope": "chapter",
                "start_chapter": 1,
                "expected_brief_version": 0,
                "dimensions": ["structure"],
            },
        )
    ).json()
    stored = await db_session.get(EditorialReview, UUID(review["id"]))
    stored.status = "running"
    task = await db_session.get(AsyncTask, UUID(review["task_id"]))
    task.status = "failed"
    await db_session.commit()

    listed = (
        await async_client.get(
            "/api/assistant/editorial/reviews", params={"novel_id": novel_id}
        )
    ).json()
    assert listed[0]["status"] == "failed"
    resumed = await editorial.resume(db_session, novel_id, UUID(review["id"]))
    assert resumed["status"] == "queued"


@pytest.mark.asyncio
async def test_background_requires_project_grant_and_new_ready_version(
    async_client, db_session, monkeypatch
):
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_editorial_enabled=True,
        assistant_editorial_automatic_enabled=True,
    )
    for module in (editorial, editorial_queue, proactive):
        monkeypatch.setattr(module, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    project = (
        await async_client.post("/api/projects", json={"title": "主动编辑测试"})
    ).json()
    novel_id = project["id"]
    draft = (
        await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "content": "她推开门，看到一盏灯。",
            },
        )
    ).json()
    assert (
        await db_session.scalar(
            select(AssistantWatch).where(AssistantWatch.novel_id == UUID(novel_id))
        )
        is None
    )
    configured = await async_client.put(
        "/api/assistant/editorial/policy",
        json={
            "novel_id": novel_id,
            "expected_generation": 0,
            "policy": {"enabled": True},
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["enabled"]
    assert configured.json()["generation"] == 1
    assert (
        await async_client.put(
            "/api/assistant/editorial/policy",
            json={
                "novel_id": novel_id,
                "expected_generation": 0,
                "policy": {"enabled": False},
            },
        )
    ).status_code == 409
    ready_url = f"/api/writing/drafts/{draft['id']}/editorial-ready?novel_id={novel_id}"
    ready = await async_client.post(
        ready_url, json={"expected_content_hash": draft["content_hash"]}
    )
    assert ready.status_code == 200
    await async_client.post(
        ready_url, json={"expected_content_hash": draft["content_hash"]}
    )
    watch = await db_session.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(novel_id))
    )
    assert len(editorial_queue.pending(watch)) == 1
    monkeypatch.setattr(
        proactive, "_now", lambda: datetime.now(UTC) + timedelta(seconds=61)
    )
    assert await proactive.schedule_due(db_session) == 1
    await db_session.commit()
    review = await db_session.scalar(
        select(EditorialReview).where(EditorialReview.novel_id == UUID(novel_id))
    )
    marker = await db_session.get(AssistantRun, review.id)
    assert review.scope_json["background"] and marker.status == "pending"
    assert watch.active_run_id == review.id
    fingerprint = "b" * 64
    review.status = "completed"
    review.report_json = {"top_findings": [{"fingerprint": fingerprint}]}
    db_session.add(
        EditorialIssue(
            novel_id=UUID(novel_id),
            review_id=review.id,
            fingerprint=fingerprint,
            disposition="open",
            finding_json={
                "category": "structure",
                "judgment": "灯光线索值得尽快核对",
                "severity": "high",
                "unchecked": "",
                "evidence": [
                    {
                        "chapter_index": 1,
                        "draft_id": draft["id"],
                        "content_hash": draft["content_hash"],
                        "quote": "看到一盏灯",
                        "start": 6,
                        "end": 12,
                    }
                ],
            },
            decision_json=[],
            history_json=[],
            recheck_json=[],
        )
    )
    await db_session.flush()
    await editorial_queue.finish(db_session, review)
    await editorial_queue.finish(db_session, review)
    notices = await proactive.list_notices(db_session, novel_id)
    assert len(notices["items"]) == 1
    assert not notices["items"][0]["needs_recheck"]
    disabled = await async_client.put(
        "/api/assistant/editorial/policy",
        json={
            "novel_id": novel_id,
            "expected_generation": configured.json()["generation"],
            "policy": {"enabled": False},
        },
    )
    assert disabled.status_code == 200 and not disabled.json()["enabled"]
    with pytest.raises(ConflictError, match="撤销"):
        await editorial_queue.guard(db_session, review)


@pytest.mark.asyncio
async def test_long_chapter_reports_partial_then_resumes_unread_tail(
    async_client, db_session, monkeypatch
):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    @asynccontextmanager
    async def client(_db, _novel_id, _snapshot):
        yield type("Client", (), {"model_name": "test"})()

    calls = []

    async def model(_client, request, _schema, **_kwargs):
        payload = json.loads(request.messages[1].content)
        calls.append(payload["offset"])
        budget = current_workflow_budget().budget
        budget.reserve(requests=1)
        budget.add_usage(
            LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
        )
        return ReviewPass(summary="本片段已检查")

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(editorial, "open_project_snapshot_llm_client", client)
    monkeypatch.setattr(editorial, "run_managed_structured", model)
    project = (
        await async_client.post("/api/projects", json={"title": "长章续读"})
    ).json()
    novel_id = project["id"]
    text = "长" * (editorial._CHUNK * 4 + 10)
    draft = (
        await async_client.post(
            "/api/writing/drafts/autosave",
            json={"novel_id": novel_id, "chapter_index": 1, "content": text},
        )
    ).json()
    submitted = (
        await async_client.post(
            "/api/assistant/editorial/reviews",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid4()),
                "scope": "chapter",
                "start_chapter": 1,
                "expected_brief_version": 0,
                "dimensions": ["copy"],
            },
        )
    ).json()
    db_session.task_checkpoint_enabled = True
    task = await db_session.get(AsyncTask, UUID(submitted["task_id"]))
    await editorial.execute(db_session, task)
    partial = await editorial.view(db_session, novel_id, UUID(submitted["id"]))
    assert partial["status"] == "partial"
    assert partial["unchecked_chapters"] == [1]
    assert not partial["report"]["coverage_complete"]
    assert calls == [0, 12000, 24000, 36000]

    review = await db_session.get(EditorialReview, UUID(submitted["id"]))
    review.progress_json = {**review.progress_json, "usage_unknown": True}
    await db_session.flush()
    with pytest.raises(ConflictError, match="用量"):
        await editorial.resume(db_session, novel_id, review.id)
    review.progress_json = {**review.progress_json, "usage_unknown": False}
    await db_session.flush()
    resumed = await editorial.resume(db_session, novel_id, UUID(submitted["id"]))
    task = await db_session.get(AsyncTask, UUID(resumed["task_id"]))
    await editorial.execute(db_session, task)
    completed = await editorial.view(db_session, novel_id, UUID(submitted["id"]))
    assert completed["status"] == "completed"
    assert completed["checked_chapters"] == [1]
    assert completed["report"]["coverage_complete"]
    assert calls == [0, 12000, 24000, 36000, 48000]
    assert (await db_session.get(WritingDraft, UUID(draft["id"]))).content == text


# ============================================================
# B2: 意见处置稳定身份（结构化键 + 跨复审继承）
# ============================================================


def test_editorial_fingerprint_ignores_quote_wording() -> None:
    """同一对象同一章节的意见,改写引文措辞身份不变;换对象则身份变。"""
    from modules.assistant.editorial import _fingerprint

    base = {
        "category": "structure",
        "evidence": [{"chapter_index": 3, "quote": "他推门而入,看见满地灰烬"}],
        "context_evidence": [
            {"source_kind": "world", "source_id": "world-1", "quote": "旧港设定"}
        ],
    }
    reworded = {
        "category": "structure",
        "evidence": [{"chapter_index": 3, "quote": "完全不同的措辞,模型换了首条证据"}],
        "context_evidence": [
            {"source_kind": "world", "source_id": "world-1", "quote": "别的引用"}
        ],
    }
    other_object = {
        "category": "structure",
        "evidence": [{"chapter_index": 3, "quote": "他推门而入,看见满地灰烬"}],
        "context_evidence": [
            {"source_kind": "world", "source_id": "world-2", "quote": "旧港设定"}
        ],
    }
    other_chapter = {
        "category": "structure",
        "evidence": [{"chapter_index": 4, "quote": "他推门而入,看见满地灰烬"}],
        "context_evidence": [
            {"source_kind": "world", "source_id": "world-1", "quote": "旧港设定"}
        ],
    }
    assert _fingerprint(base) == _fingerprint(reworded)
    assert _fingerprint(base) != _fingerprint(other_object)
    assert _fingerprint(base) != _fingerprint(other_chapter)


def test_editorial_legacy_fingerprint_alias_matches_old_rows() -> None:
    from modules.assistant.editorial import _fingerprint, _legacy_fingerprint

    finding = {
        "category": "copy",
        "evidence": [{"chapter_index": 2, "quote": "错别字片段"}],
        "context_evidence": [],
    }
    legacy = _legacy_fingerprint(finding)
    assert legacy != _fingerprint(finding)
    # 旧算法对措辞敏感(这是缺陷),新算法不受影响
    assert (
        _legacy_fingerprint(
            {**finding, "evidence": [{"chapter_index": 2, "quote": "改写后的措辞"}]}
        )
        != legacy
    )


def test_editorial_fingerprint_without_objects_anchors_on_quote() -> None:
    """无对象引用时身份退化为引文锚点:同章同类目不同意见不碰撞。"""
    from modules.assistant.editorial import _fingerprint

    typo_a = {
        "category": "copy",
        "evidence": [{"chapter_index": 2, "quote": "他做在椅子上面"}],
        "context_evidence": [],
    }
    typo_b = {
        "category": "copy",
        "evidence": [{"chapter_index": 2, "quote": "风向标指向了南边"}],
        "context_evidence": [],
    }
    whitespace_reworded = {
        "category": "copy",
        "evidence": [{"chapter_index": 2, "quote": "他 做在\n椅子上面"}],
        "context_evidence": [],
    }
    assert _fingerprint(typo_a) != _fingerprint(typo_b)
    assert _fingerprint(typo_a) == _fingerprint(whitespace_reworded)


@pytest.mark.asyncio
async def test_save_findings_inherits_disposition_across_reworded_evidence(
    async_client, db_session
):
    """复审中措辞改写后同键意见沿用旧行与处置,并带继承标记。"""
    project = (
        await async_client.post("/api/projects", json={"title": "继承处置作品"})
    ).json()
    novel_id = project["id"]
    first_review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(first_review)
    await db_session.flush()

    finding_v1 = {
        "category": "scene",
        "judgment": "第一版判断",
        "severity": "medium",
        "evidence": [{"chapter_index": 2, "quote": "她沿着堤岸走了很久"}],
        "context_evidence": [
            {"source_kind": "world", "source_id": "obj-1", "quote": "堤岸设定"}
        ],
    }
    await editorial._save_findings(db_session, first_review, [finding_v1])
    issue = (
        await db_session.execute(
            select(EditorialIssue).where(EditorialIssue.novel_id == UUID(novel_id))
        )
    ).scalar_one()
    issue.disposition = "intentional"
    await db_session.flush()

    second_review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(second_review)
    await db_session.flush()
    finding_v2 = {
        **finding_v1,
        "judgment": "复审后的新判断",
        "evidence": [{"chapter_index": 2, "quote": "模型完全改写了的引文措辞"}],
    }
    await editorial._save_findings(db_session, second_review, [finding_v2])

    refreshed = (
        await db_session.execute(
            select(EditorialIssue).where(EditorialIssue.novel_id == UUID(novel_id))
        )
    ).scalar_one()
    assert refreshed.review_id == second_review.id
    assert refreshed.disposition == "intentional"
    assert refreshed.finding_json["judgment"] == "复审后的新判断"
    assert refreshed.finding_json["disposition_inherited"] is True
    assert refreshed.finding_json["inherited_disposition"] == "intentional"
    assert len(refreshed.history_json) == 1


@pytest.mark.asyncio
async def test_legacy_alias_migrates_row_fingerprint_and_keeps_disposition(
    async_client, db_session
):
    """legacy 别名命中且对象集合一致时,行指纹升级为新 key 并继承处置。"""
    project = (
        await async_client.post("/api/projects", json={"title": "别名迁移作品"})
    ).json()
    novel_id = project["id"]
    first_review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(first_review)
    await db_session.flush()
    finding_v1 = {
        "category": "copy",
        "judgment": "第一版",
        "severity": "low",
        "evidence": [{"chapter_index": 2, "quote": "旧措辞引文"}],
        "context_evidence": [],
    }
    # 手工构造旧版本算法写入的历史行
    db_session.add(
        EditorialIssue(
            novel_id=UUID(novel_id),
            review_id=first_review.id,
            fingerprint=editorial._legacy_fingerprint(finding_v1),
            finding_json=finding_v1,
        )
    )
    assert editorial._fingerprint(finding_v1) != editorial._legacy_fingerprint(finding_v1)
    await db_session.flush()
    legacy_row = (
        await db_session.execute(
            select(EditorialIssue).where(EditorialIssue.novel_id == UUID(novel_id))
        )
    ).scalar_one()
    legacy_fingerprint = legacy_row.fingerprint
    assert legacy_fingerprint == editorial._legacy_fingerprint(finding_v1)
    legacy_row.disposition = "later"
    await db_session.flush()

    second_review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(second_review)
    await db_session.flush()
    # 复审:对象集合与旧行一致(都为空),旧 key 相同、新 key 不同
    finding_v2 = {
        **finding_v1,
        "judgment": "复审后的判断",
    }
    assert editorial._legacy_fingerprint(finding_v2) == legacy_fingerprint
    assert editorial._fingerprint(finding_v2) != legacy_fingerprint
    await editorial._save_findings(db_session, second_review, [finding_v2])

    migrated = (
        await db_session.execute(
            select(EditorialIssue).where(EditorialIssue.novel_id == UUID(novel_id))
        )
    ).scalar_one()
    assert migrated.id == legacy_row.id
    assert migrated.fingerprint == editorial._fingerprint(finding_v2)
    assert migrated.fingerprint != legacy_fingerprint
    assert migrated.disposition == "later"
    assert migrated.finding_json["disposition_inherited"] is True


@pytest.mark.asyncio
async def test_legacy_alias_does_not_inherit_when_object_set_differs(
    async_client, db_session
):
    """复审意见新增对象引用时与旧行不是同一条意见:不迁移、不继承处置。"""
    project = (
        await async_client.post("/api/projects", json={"title": "别名不迁移作品"})
    ).json()
    novel_id = project["id"]
    first_review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(first_review)
    await db_session.flush()
    finding_v1 = {
        "category": "copy",
        "judgment": "第一版",
        "severity": "low",
        "evidence": [{"chapter_index": 2, "quote": "旧措辞引文"}],
        "context_evidence": [],
    }
    legacy_row = EditorialIssue(
        novel_id=UUID(novel_id),
        review_id=first_review.id,
        fingerprint=editorial._legacy_fingerprint(finding_v1),
        finding_json=finding_v1,
    )
    db_session.add(legacy_row)
    await db_session.flush()
    legacy_row.disposition = "later"
    await db_session.flush()

    second_review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(second_review)
    await db_session.flush()
    # 复审:旧 key 相同,但意见新增了对象引用
    finding_v2 = {
        **finding_v1,
        "judgment": "复审后的判断",
        "context_evidence": [
            {"source_kind": "world", "source_id": "obj-9", "quote": "新对象引用"}
        ],
    }
    assert editorial._legacy_fingerprint(finding_v2) == legacy_row.fingerprint
    await editorial._save_findings(db_session, second_review, [finding_v2])

    rows = (
        (
            await db_session.execute(
                select(EditorialIssue).where(EditorialIssue.novel_id == UUID(novel_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    by_id = {row.id: row for row in rows}
    # 旧行原样保留:指纹未升级、处置不动
    untouched = by_id[legacy_row.id]
    assert untouched.fingerprint == editorial._legacy_fingerprint(finding_v1)
    assert untouched.disposition == "later"
    assert untouched.review_id == first_review.id
    # 新意见按新 key 建行,不继承旧处置
    created = next(row for row in rows if row.id != legacy_row.id)
    assert created.fingerprint == editorial._fingerprint(finding_v2)
    assert created.disposition == "open"
    assert created.finding_json["disposition_inherited"] is False


@pytest.mark.asyncio
async def test_save_findings_keeps_both_objectless_findings_in_same_chapter(
    async_client, db_session
):
    """同章同类目无对象的两条意见必须各建一行,不允许身份碰撞吞掉一条。"""
    project = (
        await async_client.post("/api/projects", json={"title": "碰撞回归作品"})
    ).json()
    novel_id = project["id"]
    review = EditorialReview(
        novel_id=UUID(novel_id),
        owner_id=UUID("00000000-0000-0000-0000-000000000001"),
        operation_id=uuid4(),
        status="done",
    )
    db_session.add(review)
    await db_session.flush()
    findings = [
        {
            "category": "copy",
            "judgment": "错别字之一",
            "severity": "low",
            "evidence": [{"chapter_index": 2, "quote": "他做在椅子上面"}],
            "context_evidence": [],
        },
        {
            "category": "copy",
            "judgment": "错别字之二",
            "severity": "low",
            "evidence": [{"chapter_index": 2, "quote": "风向标指向了南边"}],
            "context_evidence": [],
        },
    ]
    assert editorial._fingerprint(findings[0]) != editorial._fingerprint(findings[1])
    await editorial._save_findings(db_session, review, findings)

    rows = (
        (
            await db_session.execute(
                select(EditorialIssue).where(EditorialIssue.novel_id == UUID(novel_id))
            )
        )
        .scalars()
        .all()
    )
    assert sorted(row.finding_json["judgment"] for row in rows) == [
        "错别字之一",
        "错别字之二",
    ]


@pytest.mark.asyncio
async def test_save_findings_keeps_colliding_object_findings_and_keeps_disposition(
    async_client, db_session
):
    """同章同对象的两条不同意见各建一行；撞键前后同一条意见都继承处置。"""
    project = (
        await async_client.post("/api/projects", json={"title": "对象碰撞作品"})
    ).json()
    novel_id = project["id"]

    async def new_review():
        review = EditorialReview(
            novel_id=UUID(novel_id),
            owner_id=UUID("00000000-0000-0000-0000-000000000001"),
            operation_id=uuid4(),
            status="done",
        )
        db_session.add(review)
        await db_session.flush()
        return review

    async def rows():
        return (
            (
                await db_session.execute(
                    select(EditorialIssue).where(
                        EditorialIssue.novel_id == UUID(novel_id)
                    )
                )
            )
            .scalars()
            .all()
        )

    scene_ref = [{"source_kind": "structure", "source_id": "scene-1", "quote": "计划"}]
    pacing = {
        "category": "scene",
        "judgment": "节奏拖沓",
        "severity": "medium",
        "evidence": [{"chapter_index": 3, "quote": "他们在门口站了很久"}],
        "context_evidence": scene_ref,
    }
    motive = {
        "category": "scene",
        "judgment": "动机不足",
        "severity": "medium",
        "evidence": [{"chapter_index": 3, "quote": "她忽然决定离开"}],
        "context_evidence": scene_ref,
    }
    assert editorial._fingerprint(pacing) == editorial._fingerprint(motive)

    await editorial._save_findings(db_session, await new_review(), [dict(pacing)])
    (original,) = await rows()
    original.disposition = "intentional"
    await db_session.flush()

    await editorial._save_findings(
        db_session, await new_review(), [dict(pacing), dict(motive)]
    )
    collided = {row.finding_json["judgment"]: row for row in await rows()}
    assert set(collided) == {"节奏拖沓", "动机不足"}
    assert collided["节奏拖沓"].id == original.id
    assert collided["节奏拖沓"].disposition == "intentional"
    assert collided["节奏拖沓"].fingerprint != editorial._fingerprint(pacing)
    assert collided["动机不足"].disposition == "open"

    await editorial._save_findings(db_session, await new_review(), [dict(pacing)])
    back = {row.finding_json["judgment"]: row for row in await rows()}
    assert back["节奏拖沓"].id == original.id
    assert back["节奏拖沓"].fingerprint == editorial._fingerprint(pacing)
    assert back["节奏拖沓"].disposition == "intentional"
    assert back["节奏拖沓"].finding_json["disposition_inherited"] is True
