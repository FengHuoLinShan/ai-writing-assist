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
