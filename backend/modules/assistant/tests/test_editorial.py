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
