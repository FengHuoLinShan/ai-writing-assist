"""Offline regression checks for editorial diagnosis and A/B execution hooks."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from core.config import get_settings
from core.errors import ConflictError
from infrastructure.llm.schemas import LLMUsage
from infrastructure.llm.workflow_budget import current_workflow_budget
from infrastructure.tasks.models import AsyncTask
from modules.assistant import editorial
from modules.assistant.editorial_contracts import ReviewPass
from modules.assistant.editorial_models import EditorialReview
from modules.assistant.tasks import handle_assistant_editorial_review
from modules.writing.models import WritingDraft


@pytest.fixture
async def review_case(async_client, db_session, monkeypatch):
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)

    async def snapshot(_db, _novel_id):
        return {"test_snapshot": True}

    model_client = SimpleNamespace(model_name="offline-editorial")
    opened = []

    @asynccontextmanager
    async def client(db, novel_id, frozen_snapshot, **options):
        assert db is db_session
        assert frozen_snapshot == {"test_snapshot": True}
        opened.append((novel_id, options))
        yield options.get("injected_client", model_client)

    monkeypatch.setattr(editorial, "build_project_llm_execution_snapshot", snapshot)
    monkeypatch.setattr(editorial, "open_project_snapshot_llm_client", client)
    project = await async_client.post("/api/projects", json={"title": "离线审读补测"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    drafts = []
    for chapter in (1, 2, 3):
        response = await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": chapter,
                "content": f"第{chapter}章：信上的地址指向旧港。",
            },
        )
        assert response.status_code == 201, response.text
        drafts.append(response.json())

    async def submit(scope="chapter", dimensions=None, end_chapter=2):
        response = await async_client.post(
            "/api/assistant/editorial/reviews",
            json={
                "novel_id": novel_id,
                "operation_id": str(uuid4()),
                "scope": scope,
                "start_chapter": 1,
                "end_chapter": end_chapter if scope == "range" else None,
                "expected_brief_version": 0,
                "dimensions": dimensions or ["copy"],
            },
        )
        assert response.status_code == 200, response.text
        review = response.json()
        task = await db_session.get(AsyncTask, UUID(review["task_id"]))
        db_session.task_checkpoint_enabled = True
        return task, await db_session.get(EditorialReview, UUID(review["id"]))

    return SimpleNamespace(
        novel_id=novel_id,
        drafts=drafts,
        submit=submit,
        model_client=model_client,
        opened=opened,
    )


@pytest.mark.parametrize("system_prompt", [None, "冻结的基线提示词。"])
@pytest.mark.parametrize(
    ("scope", "end_chapter"), [("chapter", 1), ("range", 2), ("range", 3)]
)
async def test_worker_hooks_keep_prompt_and_budget_through_each_pass(
    review_case, db_session, monkeypatch, system_prompt, scope, end_chapter
):
    dimensions = ["reader", "copy"] if scope == "chapter" else ["copy"]
    task, row = await review_case.submit(scope, dimensions, end_chapter)
    events, requests, results = [], [], []
    injected_client = SimpleNamespace(model_name="offline-injected")

    async def before(db, review, client, budget, instructions, payload):
        assert db is db_session and review.id == row.id
        expected_client = review_case.opened[-1][1].get(
            "injected_client", review_case.model_client
        )
        assert client is expected_client
        state = object()
        events.append(("before", state))
        requests.append((instructions, payload))
        assert budget.requests == len(requests) - 1
        return state

    async def model(client, request, schema, **options):
        expected_client = review_case.opened[-1][1].get(
            "injected_client", review_case.model_client
        )
        assert client is expected_client and schema is ReviewPass
        assert options["max_fix_attempts"] == 0
        assert options["transport_retries"] is False
        assert request.messages[0].content == requests[-1][0]
        assert json.loads(request.messages[1].content) == requests[-1][1]
        events.append(("model", events[-1][1]))
        workflow = current_workflow_budget()
        await workflow.before_request()
        await workflow.completed(
            LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        result = ReviewPass(summary="已核对当前可见片段。", reader_state="知道地址。")
        results.append(result)
        return result

    async def after(state, budget, result, error):
        assert current_workflow_budget() is None
        assert result is results[-1] and error is None
        assert budget.pending_usage == 0 and budget.usage_complete
        events.append(("after", state))

    monkeypatch.setattr(editorial, "run_managed_structured", model)
    db_session.info["editorial_prompt_ab_options"] = {
        "_system_prompt": system_prompt,
        "_before_request": before,
        "_after_request": after,
        "_injected_client": injected_client,
    }
    outcome = await handle_assistant_editorial_review(db_session, task)
    assert outcome == {"review_id": str(row.id), "status": "completed"}
    assert review_case.opened == [
        (review_case.novel_id, {"injected_client": injected_client})
    ]
    prompt = editorial._SYSTEM if system_prompt is None else system_prompt
    if scope == "chapter":
        assert len(requests) == 2
        assert requests[0][0].startswith(prompt)
        assert "顺序初读者" in requests[0][0]
        assert "brief" not in requests[0][1]
        assert requests[1][0] == prompt and "brief" in requests[1][1]
    else:
        assert len(requests) == end_chapter + 1
        assert [instructions for instructions, _ in requests[:end_chapter]] == [
            prompt
        ] * end_chapter
        assert requests[-1][0].startswith(prompt)
        assert [node["chapters"] for node in requests[-1][1]["nodes"]] == [
            [chapter] for chapter in range(1, end_chapter + 1)
        ]
    assert [kind for kind, _ in events] == ["before", "model", "after"] * len(requests)
    for index in range(0, len(events), 3):
        assert events[index][1] is events[index + 1][1] is events[index + 2][1]
    stored = await db_session.get(EditorialReview, row.id, populate_existing=True)
    budget = stored.progress_json["budget"]
    assert budget["requests"] == len(requests)
    assert budget["prompt_tokens"] == 10 * len(requests)
    assert budget["completion_tokens"] == 5 * len(requests)
    assert stored.report_json["coverage_complete"]
    for draft in review_case.drafts:
        assert (await db_session.get(WritingDraft, UUID(draft["id"]))).content == draft[
            "content"
        ]


async def test_cross_chapter_evidence_survives_resume_without_extra_requests(
    review_case, db_session, monkeypatch
):
    task, row = await review_case.submit("range", ["reader", "copy"], end_chapter=3)
    requests = []
    first_quote = review_case.drafts[0]["content"]

    async def model(_client, request, schema, **_kwargs):
        payload = json.loads(request.messages[1].content)
        requests.append(payload)
        workflow = current_workflow_budget()
        await workflow.before_request()
        await workflow.completed(
            LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        if "nodes" in payload:
            return ReviewPass(summary="已汇总各章的意见。")
        if "dimensions" not in payload:
            return ReviewPass(summary="顺序阅读完成。", reader_state="记得前文。")
        chapter = payload["chapter_index"]
        findings = []
        if chapter == 3:
            findings = [
                {
                    "category": "copy",
                    "judgment": "第三章的地址与前章记录需要核对",
                    "reader_impact": "读者会同时记得前文地点和本章信息",
                    "severity": "high",
                    "why_now": "当前章节重新使用了前文地址",
                    "evidence": [
                        {"chapter_index": 1, "quote": first_quote},
                        {"chapter_index": 3, "quote": payload["text"]},
                    ],
                    "directions": [
                        {
                            "approach": "先核对地点变化是否需要在正文说明",
                            "affected_chapters": [1, 3],
                            "tradeoff": "可能增加一处解释",
                        }
                    ],
                }
            ]
        carried = (
            [{"chapter_index": 1, "quote": first_quote}] if chapter == 1 else []
        )
        return ReviewPass(
            summary=f"第{chapter}章已读。", findings=findings, carry_forward=carried
        )

    monkeypatch.setattr(editorial, "run_managed_structured", model)
    assert await editorial.execute(db_session, task) == {
        "review_id": str(row.id),
        "status": "partial",
    }
    stored = await db_session.get(EditorialReview, row.id, populate_existing=True)
    assert stored.progress_json["prior_evidence"][0]["quote"] == first_quote
    assert len(requests) == 4

    resumed = await editorial.resume(db_session, review_case.novel_id, row.id)
    resumed_task = await db_session.get(AsyncTask, UUID(resumed["task_id"]))
    assert await editorial.execute(db_session, resumed_task) == {
        "review_id": str(row.id),
        "status": "completed",
    }
    assert len(requests) == 7
    third_chapter_request = next(
        payload
        for payload in requests
        if payload.get("chapter_index") == 3 and "dimensions" in payload
    )
    assert third_chapter_request["prior_evidence"] == [
        {"chapter_index": 1, "quote": first_quote}
    ]
    assert third_chapter_request["prior_evidence_omitted_count"] == 0
    report = (await editorial.view(db_session, review_case.novel_id, row.id))["report"]
    cross_chapter_finding = report["all_findings"][0]
    assert [item["chapter_index"] for item in cross_chapter_finding["evidence"]] == [
        1,
        3,
    ]


async def test_later_segment_uses_verified_evidence_from_same_chapter(
    review_case, async_client, db_session, monkeypatch
):
    first_quote, later_quote = "钥匙已在旧港销毁。", "他又用那把钥匙开了门。"
    content = first_quote + "甲" * (editorial._CHUNK - len(first_quote)) + later_quote
    response = await async_client.put(
        f"/api/writing/drafts/{review_case.drafts[0]['id']}?novel_id={review_case.novel_id}",
        json={"content": content},
    )
    assert response.status_code == 200, response.text
    task, row = await review_case.submit()
    requests = []

    async def model(_client, request, _schema, **_kwargs):
        payload = json.loads(request.messages[1].content)
        requests.append(payload)
        workflow = current_workflow_budget()
        await workflow.before_request()
        await workflow.completed(
            LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        if "nodes" in payload:
            return ReviewPass(summary="已汇总同章两段依据。")
        if payload["offset"] == 0:
            return ReviewPass(
                summary="钥匙已销毁。",
                carry_forward=[{"chapter_index": 1, "quote": first_quote}],
            )
        assert payload["offset"] == editorial._CHUNK
        assert payload["prior_evidence"] == [
            {"chapter_index": 1, "quote": first_quote}
        ]
        return ReviewPass(
            summary="后段与前段状态冲突。",
            findings=[
                {
                    "category": "copy",
                    "judgment": "已销毁的钥匙又被使用",
                    "reader_impact": "读者无法理解钥匙为何仍可使用",
                    "severity": "medium",
                    "evidence": [
                        {"chapter_index": 1, "quote": first_quote},
                        {"chapter_index": 1, "quote": later_quote},
                    ],
                }
            ],
        )

    monkeypatch.setattr(editorial, "run_managed_structured", model)
    assert (await editorial.execute(db_session, task))["status"] == "completed"
    report = (await editorial.view(db_session, review_case.novel_id, row.id))["report"]
    assert len(report["all_findings"]) == 1
    evidence = report["all_findings"][0]["evidence"]
    assert [item["quote"] for item in evidence] == [first_quote, later_quote]
    assert [payload["offset"] for payload in requests] == [0, editorial._CHUNK]


async def test_disabled_ab_ledger_ignores_carry_forward_without_extra_request(
    review_case, db_session, monkeypatch
):
    task, row = await review_case.submit("chapter", ["copy"], end_chapter=1)
    requests = []

    async def model(_client, request, schema, **_kwargs):
        assert schema is ReviewPass
        payload = json.loads(request.messages[1].content)
        requests.append(payload)
        workflow = current_workflow_budget()
        await workflow.before_request()
        await workflow.completed(
            LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        )
        return ReviewPass(
            summary="当前章节已读。",
            carry_forward=[
                {"chapter_index": 1, "quote": review_case.drafts[0]["content"]}
            ],
        )

    monkeypatch.setattr(editorial, "run_managed_structured", model)
    db_session.info["editorial_prompt_ab_options"] = {
        "_carry_forward_enabled": False,
    }
    assert await handle_assistant_editorial_review(db_session, task) == {
        "review_id": str(row.id),
        "status": "completed",
    }
    stored = await db_session.get(EditorialReview, row.id, populate_existing=True)
    assert len(requests) == 1
    assert "prior_evidence" not in requests[0]
    assert "prior_evidence" not in stored.progress_json


async def test_prior_citations_require_ledger_membership_and_review_scope(
    review_case, db_session
):
    _, row = await review_case.submit("range", ["copy"], end_chapter=2)
    first = review_case.drafts[0]["content"]
    second = review_case.drafts[1]["content"]
    carry = ReviewPass(
        summary="前文有一条可回看的原文。",
        carry_forward=[{"chapter_index": 1, "quote": "第1章："}],
    )
    validated = await editorial._validated_carry_forward(
        db_session, row, carry, chapter=1, segment=first
    )
    progress = dict(row.progress_json)
    editorial._append_prior_evidence(progress, validated)
    row.progress_json = progress

    def finding(old_chapter, old_quote):
        return {
            "category": "copy",
            "judgment": "两处记录需要核对",
            "reader_impact": "读者会把两段文字一起记住",
            "severity": "high",
            "why_now": "本章提供了新的对照依据",
            "evidence": [
                {"chapter_index": old_chapter, "quote": old_quote},
                {"chapter_index": 2, "quote": second},
            ],
            "directions": [
                {
                    "approach": "核对两章是否缺少原因交代",
                    "affected_chapters": [old_chapter, 2],
                    "tradeoff": "可能需要补一处说明",
                }
            ],
        }

    forged = ReviewPass(
        summary="本章与前文有差异。",
        findings=[finding(1, "地址指向旧港")],
    )
    out_of_scope = ReviewPass(
        summary="本章与第三章有差异。",
        findings=[finding(3, review_case.drafts[2]["content"])],
    )
    for output in (forged, out_of_scope):
        assert (
            await editorial._validated_findings(
                db_session,
                row,
                output,
                chapter=2,
                segment=second,
                allow_prior_evidence=True,
                require_current_evidence=True,
            )
            == []
        )


def test_prior_evidence_ledger_caps_entries_and_characters_with_omission_count():
    short_progress = {}
    editorial._append_prior_evidence(
        short_progress,
        [
            {"chapter_index": index, "quote": f"摘录{index:02}"}
            for index in range(1, 36)
        ],
    )
    assert len(short_progress["prior_evidence"]) == 32
    assert short_progress["prior_evidence"][0]["chapter_index"] == 4
    assert short_progress["prior_evidence_omitted_count"] == 3

    progress = {}
    editorial._append_prior_evidence(
        progress,
        [
            {"chapter_index": index, "quote": f"{index:02}" + "x" * 198}
            for index in range(1, 35)
        ],
    )
    assert len(progress["prior_evidence"]) == 30
    assert sum(len(item["quote"]) for item in progress["prior_evidence"]) == 6000
    assert progress["prior_evidence"][0]["chapter_index"] == 5
    assert progress["prior_evidence_omitted_count"] == 4

    editorial._append_prior_evidence(
        progress,
        [
            {"chapter_index": index, "quote": f"短引文{index}"}
            for index in range(35, 40)
        ],
    )
    assert len(progress["prior_evidence"]) <= editorial._PRIOR_EVIDENCE_MAX_ITEMS
    assert progress["prior_evidence_omitted_count"] == 7


@pytest.mark.parametrize("failure_at", ["before", "model", "unknown_usage", "after"])
async def test_request_failure_keeps_receipt_and_never_retries(
    review_case, db_session, monkeypatch, failure_at
):
    task, row = await review_case.submit()
    review_id = row.id
    error = RuntimeError("离线请求模拟故障")
    state, result = object(), ReviewPass(summary="当前片段已核对。")
    events = []

    async def before(*_args):
        events.append("before")
        if failure_at == "before":
            raise error
        return state

    async def model(*_args, **_kwargs):
        events.append("model")
        workflow = current_workflow_budget()
        await workflow.before_request()
        if failure_at != "unknown_usage":
            await workflow.completed(
                LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            )
        if failure_at in {"model", "unknown_usage"}:
            raise error
        return result

    async def after(request_state, budget, output, exc):
        events.append("after")
        assert request_state is state
        if failure_at in {"model", "unknown_usage"}:
            assert output is None and exc is error
        else:
            assert output is result and exc is None
            raise error

    monkeypatch.setattr(editorial, "run_managed_structured", model)
    with pytest.raises(RuntimeError) as raised:
        await editorial.execute(
            db_session, task, _before_request=before, _after_request=after
        )
    assert raised.value is error
    assert events == (
        ["before"] if failure_at == "before" else ["before", "model", "after"]
    )
    stored = await db_session.get(EditorialReview, review_id, populate_existing=True)
    assert stored.status == "failed" and not stored.report_json
    assert stored.progress_json["budget"]["requests"] == (failure_at != "before")
    assert stored.progress_json["usage_unknown"] is (failure_at == "unknown_usage")
    assert current_workflow_budget() is None
    if failure_at == "unknown_usage":
        with pytest.raises(ConflictError, match="用量"):
            await editorial.resume(db_session, review_case.novel_id, review_id)


async def test_source_change_rejects_request_before_hooks(
    review_case, async_client, db_session, monkeypatch
):
    task, row = await review_case.submit()
    review_id = row.id
    draft = review_case.drafts[0]
    changed = await async_client.put(
        f"/api/writing/drafts/{draft['id']}?novel_id={review_case.novel_id}",
        json={"content": "信上的地址已经改成新港。"},
    )
    assert changed.status_code == 200, changed.text
    await db_session.commit()

    async def unexpected(*_args, **_kwargs):
        pytest.fail("Changed sources must be rejected before any request or hook")

    monkeypatch.setattr(editorial, "run_managed_structured", unexpected)
    with pytest.raises(ConflictError, match="来源"):
        await editorial.execute(
            db_session, task, _before_request=unexpected, _after_request=unexpected
        )
    stored = await db_session.get(EditorialReview, review_id, populate_existing=True)
    assert stored.status == "stale" and not review_case.opened


async def test_cancelled_request_reaches_receipt_hook_without_replay(
    review_case, db_session, monkeypatch
):
    task, row = await review_case.submit()
    review_id = row.id
    cancellation = asyncio.CancelledError()
    receipts = []

    async def model(*_args, **_kwargs):
        await current_workflow_budget().before_request()
        raise cancellation

    async def after(state, budget, result, error):
        receipts.append((state, budget.pending_usage, result, error))

    monkeypatch.setattr(editorial, "run_managed_structured", model)
    with pytest.raises(asyncio.CancelledError) as raised:
        await editorial.execute(db_session, task, _after_request=after)
    assert raised.value is cancellation
    assert receipts == [(None, 1, None, cancellation)]
    assert current_workflow_budget() is None
    stored = await db_session.get(EditorialReview, review_id, populate_existing=True)
    assert stored.progress_json["budget"]["requests"] == 1
    assert stored.progress_json["budget"]["pending_usage"] == 1
    assert not stored.report_json
    with pytest.raises(ConflictError, match="用量"):
        await editorial.execute(db_session, task, _after_request=after)
    assert len(receipts) == len(review_case.opened) == 1
    stored = await db_session.get(EditorialReview, review_id, populate_existing=True)
    assert stored.status == "failed" and stored.progress_json["usage_unknown"]
    assert stored.progress_json["budget"]["requests"] == 1


@pytest.mark.parametrize(
    ("why_now", "chapters", "unchecked", "expected"),
    [
        ("现在会影响地址线索的理解", [1], "", ""),
        ("现在会影响地址线索的理解", None, "", "尚未提供至少一条有据的调整方向"),
        ("", [1], "", "处理优先级依据尚不充分"),
        ("现在会影响地址线索的理解", [2], "", "调整方向涉及未审章节：2"),
        ("现在会影响地址线索的理解", [1], "旧线索尚未核对", "旧线索尚未核对"),
    ],
    ids=["single-direction", "no-direction", "no-priority", "outside-scope", "unchecked"],
)
async def test_single_direction_preserves_severity_only_with_complete_evidence(
    review_case, db_session, why_now, chapters, unchecked, expected
):
    _, row = await review_case.submit()
    directions = (
        [
            {
                "approach": "在地址揭示前增加一次核对",
                "affected_chapters": chapters,
                "tradeoff": "稍微放缓阅读节奏",
            }
        ]
        if chapters is not None
        else []
    )
    output = ReviewPass.model_validate(
        {
            "summary": "地址线索需要核对。",
            "findings": [
                {
                    "category": "copy",
                    "judgment": "地址线索的依据需要核对",
                    "reader_impact": "读者可能将猜测误认为已确认事实",
                    "severity": "high",
                    "why_now": why_now,
                    "unchecked": unchecked,
                    "evidence": [{"chapter_index": 1, "quote": "地址指向旧港"}],
                    "directions": directions,
                }
            ],
        }
    )
    findings = await editorial._validated_findings(db_session, row, output, chapter=1)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["unchecked"] == expected
    assert finding["severity"] == ("medium" if expected else "high")
    assert finding["directions"] == directions
    assert finding["evidence"][0]["content_hash"] == review_case.drafts[0]["content_hash"]
    assert finding["authority"] == "editorial_suggestion"
