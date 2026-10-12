"""BR-4 流程 3 桥接：审读意见 → Writing 批注修订。

覆盖定位成功、引文失效（逐条跳过）、冻结 hash 漂移（整体失败关闭）、
意见版本冲突，以及采用后按既有机制请求改后复核（幂等、依据失效跳过）。
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select

from core.config import get_settings
from infrastructure.tasks.models import AsyncTask
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.assistant import editorial, editorial_bridge
from modules.assistant.editorial_models import EditorialIssue, EditorialReview
from modules.writing.models import WritingComment
from modules.writing.schemas import WritingDraftCreate, WritingDraftUpdate
from modules.writing.services import WritingDraftService


def _enable_editorial(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(
        get_settings(), assistant_enabled=True, assistant_editorial_enabled=True
    )
    monkeypatch.setattr(editorial, "get_settings", lambda: settings)


async def _create_draft(db_session, novel_id: str, content: str):
    return await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第1章",
            content=content,
        ),
    )


async def _seed_review(db_session, novel_id: str, *, status: str = "completed"):
    row = EditorialReview(
        novel_id=uuid.UUID(novel_id),
        owner_id=uuid.UUID(str(LOCAL_OWNER_ID)),
        operation_id=uuid.uuid4(),
        status=status,
        scope_json={"scope": "chapter", "start_chapter": 1},
        brief_json={"version": 0, "brief": {}},
        source_json=[],
        progress_json={},
        report_json={},
        llm_snapshot_json={},
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def _seed_issue(
    db_session,
    review: EditorialReview,
    *,
    evidence: list[dict],
    fingerprint: str | None = None,
) -> EditorialIssue:
    row = EditorialIssue(
        novel_id=review.novel_id,
        review_id=review.id,
        fingerprint=fingerprint or uuid.uuid4().hex,
        row_version=0,
        disposition="open",
        finding_json={
            "category": "line",
            "judgment": "地址线索或许揭示过早",
            "reader_impact": "读者可能过早猜到目的地",
            "severity": "medium",
            "evidence": evidence,
            "context_evidence": [],
            "unchecked": "",
            "directions": [],
        },
        history_json=[],
        decision_json=[],
        recheck_json=[],
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _evidence(draft, text: str, quote: str) -> dict:
    start = text.find(quote)
    return {
        "chapter_index": 1,
        "draft_id": draft.id,
        "version_number": draft.version_number,
        "content_hash": draft.content_hash,
        "quote": quote,
        "start": start,
        "end": start + len(quote),
    }


async def test_bridge_requires_explicit_evidence_and_overlap_confirmation(
    async_client, db_session, account_llm_connection, monkeypatch
):
    _enable_editorial(monkeypatch)
    nid = (
        await async_client.post("/api/projects", json={"title": "多证据取舍合成作品"})
    ).json()["id"]
    text = "信上的地址指向旧港。"
    draft = await _create_draft(db_session, nid, text)
    review = await _seed_review(db_session, nid)
    issue = await _seed_issue(
        db_session,
        review,
        evidence=[
            _evidence(draft, text, "地址指向旧港"),
            _evidence(draft, text, "指向旧港"),
        ],
    )
    body = {
        "novel_id": nid,
        "operation_id": str(uuid.uuid4()),
        "items": [
            {
                "issue_id": str(issue.id),
                "expected_version": 0,
                "instruction": "改写选定位置",
            }
        ],
    }
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=body
    )
    assert response.status_code == 400 and "明确选择" in response.text
    body["items"][0]["evidence_indices"] = [0, 1]
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=body
    )
    assert (
        response.status_code == 409 and "OVERLAP_CONFIRMATION_REQUIRED" in response.text
    )
    assert await _comment_rows(db_session, nid) == []
    body["overlap_confirmed"] = True
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=body
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1
    assert len(await _comment_rows(db_session, nid)) == 2
    task = await db_session.get(
        AsyncTask, uuid.UUID(response.json()["items"][0]["task_id"])
    )
    assert len(task.meta["comment_ids"]) == 2


@pytest.mark.parametrize("selected_indices", [[1], [0, 1]])
async def test_bridge_selected_chapters_are_split_and_manual_ranges_keep_frozen_hash(
    async_client, db_session, account_llm_connection, monkeypatch, selected_indices
):
    import hashlib

    from modules.writing.schemas import WritingDraftCreate
    from modules.writing.services import WritingDraftService

    _enable_editorial(monkeypatch)
    nid = (
        await async_client.post("/api/projects", json={"title": "跨章选择合成作品"})
    ).json()["id"]
    first = await _create_draft(db_session, nid, "第一章信件")
    second = await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=nid, chapter_index=2, title="二", content="第二章信件"
        ),
    )
    review = await _seed_review(db_session, nid)
    other = {**_evidence(second, "第二章信件", "信件"), "chapter_index": 2}
    issue = await _seed_issue(
        db_session, review, evidence=[_evidence(first, "第一章信件", "信件"), other]
    )
    body = {
        "novel_id": nid,
        "operation_id": str(uuid.uuid4()),
        "items": [
            {
                "issue_id": str(issue.id),
                "expected_version": 0,
                "instruction": "只改第二章",
                "evidence_indices": selected_indices,
                "ranges": [
                    {
                        "evidence_index": 1,
                        "start": 3,
                        "end": 5,
                        "quote": "信件",
                        "range_hash": "0" * 64,
                    }
                ],
            }
        ],
    }
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=body
    )
    assert response.status_code == 409
    body["items"][0]["ranges"][0]["range_hash"] = hashlib.sha256(
        "信件".encode()
    ).hexdigest()
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=body
    )
    assert response.status_code == 200, response.text
    expected_chapters = [index + 1 for index in selected_indices]
    assert [
        item["chapter_index"] for item in response.json()["items"]
    ] == expected_chapters
    assert len({item["task_id"] for item in response.json()["items"]}) == len(
        expected_chapters
    )
    comments = await _comment_rows(db_session, nid)
    assert sorted(comment.chapter_index for comment in comments) == expected_chapters


async def _issue_rows(db_session, novel_id: str) -> list[EditorialIssue]:
    return list(
        (
            await db_session.execute(
                select(EditorialIssue).where(
                    EditorialIssue.novel_id == uuid.UUID(novel_id)
                )
            )
        )
        .scalars()
        .all()
    )


async def _comment_rows(db_session, novel_id: str) -> list[WritingComment]:
    return list(
        (
            await db_session.execute(
                select(WritingComment).where(
                    WritingComment.novel_id == uuid.UUID(novel_id)
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_bridge_locates_issue_records_decision_and_replays(
    async_client, db_session, account_llm_connection, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接定位"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = await _create_draft(db_session, novel_id, text)
    review = await _seed_review(db_session, novel_id)
    issue = await _seed_issue(
        db_session, review, evidence=[_evidence(draft, text, "地址指向旧港")]
    )

    payload = {
        "novel_id": novel_id,
        "operation_id": str(uuid.uuid4()),
        "items": [
            {
                "issue_id": str(issue.id),
                "expected_version": issue.row_version,
                "instruction": "把线索改得更隐晦",
            }
        ],
    }
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=payload
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["items"][0]["status"] == "queued"
    assert result["items"][0]["task_id"]
    assert result["items"][0]["chapter_index"] == 1

    comments = await _comment_rows(db_session, novel_id)
    assert len(comments) == 1
    assert comments[0].excerpt == "地址指向旧港"
    assert "地址线索或许揭示过早" in comments[0].body
    assert "作者处置：把线索改得更隐晦" in comments[0].body

    stored = (await _issue_rows(db_session, novel_id))[0]
    assert stored.disposition == "prepare"
    assert stored.row_version == 1
    assert stored.decision_json[-1]["note"] == "已发起批注修订：把线索改得更隐晦"
    assert stored.decision_json[-1]["disposition"] == "prepare"

    # 同一请求标识重放：返回原任务，不重复创建批注或决定
    replay = await async_client.post(
        "/api/assistant/editorial/issues/revise", json=payload
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["items"][0]["task_id"] == result["items"][0]["task_id"]
    assert len(await _comment_rows(db_session, novel_id)) == 1
    stored = (await _issue_rows(db_session, novel_id))[0]
    assert stored.row_version == 1


@pytest.mark.asyncio
async def test_bridge_reports_unlocatable_issue_without_blocking_others(
    async_client, db_session, account_llm_connection, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接引文失效"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = await _create_draft(db_session, novel_id, text)
    review = await _seed_review(db_session, novel_id)
    locatable = await _seed_issue(
        db_session,
        review,
        evidence=[_evidence(draft, text, "地址指向旧港")],
        fingerprint="locatable",
    )
    # hash 仍与当前稿一致，但引文不在稿内：该条不可定位
    broken = await _seed_issue(
        db_session,
        review,
        evidence=[_evidence(draft, text, "地址指向新港")],
        fingerprint="broken",
    )
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise",
        json={
            "novel_id": novel_id,
            "operation_id": str(uuid.uuid4()),
            "items": [
                {
                    "issue_id": str(locatable.id),
                    "expected_version": locatable.row_version,
                    "instruction": "改写线索",
                },
                {
                    "issue_id": str(broken.id),
                    "expected_version": broken.row_version,
                    "instruction": "改写线索",
                },
            ],
        },
    )
    assert response.status_code == 200, response.text
    items = {item["issue_id"]: item for item in response.json()["items"]}
    assert items[str(locatable.id)]["status"] == "queued"
    broken_result = items[str(broken.id)]
    assert broken_result["status"] == "unlocatable"
    assert "无法定位" in broken_result["reason"]
    assert broken_result["chapter_index"] == 1

    stored = {str(row.id): row for row in await _issue_rows(db_session, novel_id)}
    assert stored[str(locatable.id)].disposition == "prepare"
    assert stored[str(broken.id)].disposition == "open"
    assert len(await _comment_rows(db_session, novel_id)) == 1


@pytest.mark.asyncio
async def test_bridge_fails_closed_on_frozen_hash_drift(
    async_client, db_session, account_llm_connection, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接hash漂移"})
    ).json()
    novel_id = project["id"]
    frozen_text = "第一章：信上的地址指向旧港。"
    draft = await _create_draft(db_session, novel_id, frozen_text)
    review = await _seed_review(db_session, novel_id)
    first = await _seed_issue(
        db_session,
        review,
        evidence=[_evidence(draft, frozen_text, "地址指向旧港")],
        fingerprint="drift-a",
    )
    second = await _seed_issue(
        db_session,
        review,
        evidence=[_evidence(draft, frozen_text, "信上的地址")],
        fingerprint="drift-b",
    )
    base = await WritingDraftService().get_draft_contract(db_session, novel_id, draft.id)
    await WritingDraftService().update_draft(
        db_session,
        base.id,
        WritingDraftUpdate(content="第一章：信上的地址指向新港。"),
        novel_id,
    )
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise",
        json={
            "novel_id": novel_id,
            "operation_id": str(uuid.uuid4()),
            "items": [
                {
                    "issue_id": str(first.id),
                    "expected_version": first.row_version,
                    "instruction": "改写线索",
                },
                {
                    "issue_id": str(second.id),
                    "expected_version": second.row_version,
                    "instruction": "改写线索",
                },
            ],
        },
    )
    assert response.status_code == 409, response.text
    assert "重新审读" in response.json()["detail"]
    assert await _comment_rows(db_session, novel_id) == []
    stored = {str(row.id): row for row in await _issue_rows(db_session, novel_id)}
    assert stored[str(first.id)].disposition == "open"
    assert stored[str(second.id)].disposition == "open"


@pytest.mark.asyncio
async def test_bridge_rejects_stale_issue_version(
    async_client, db_session, account_llm_connection, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接版本冲突"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = await _create_draft(db_session, novel_id, text)
    review = await _seed_review(db_session, novel_id)
    issue = await _seed_issue(
        db_session, review, evidence=[_evidence(draft, text, "地址指向旧港")]
    )
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise",
        json={
            "novel_id": novel_id,
            "operation_id": str(uuid.uuid4()),
            "items": [
                {
                    "issue_id": str(issue.id),
                    "expected_version": issue.row_version + 1,
                    "instruction": "改写线索",
                }
            ],
        },
    )
    assert response.status_code == 409, response.text
    assert await _comment_rows(db_session, novel_id) == []


@pytest.mark.asyncio
async def test_bridge_requires_editorial_enabled(async_client, db_session) -> None:
    project = (
        await async_client.post("/api/projects", json={"title": "桥接未开启"})
    ).json()
    response = await async_client.post(
        "/api/assistant/editorial/issues/revise",
        json={
            "novel_id": project["id"],
            "operation_id": str(uuid.uuid4()),
            "items": [
                {
                    "issue_id": str(uuid.uuid4()),
                    "expected_version": 0,
                    "instruction": "改写线索",
                }
            ],
        },
    )
    assert response.status_code in {403, 503}, response.text


@pytest.mark.asyncio
async def test_post_adoption_recheck_is_requested_once_per_adopted_draft(
    async_client, db_session, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接改后复核"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = await _create_draft(db_session, novel_id, text)
    review = await _seed_review(db_session, novel_id)
    issue = await _seed_issue(
        db_session, review, evidence=[_evidence(draft, text, "地址指向旧港")]
    )
    # 采用产生新工作稿：关联正文有新版本，满足复核前提
    base = await WritingDraftService().get_draft_contract(db_session, novel_id, draft.id)
    await WritingDraftService().update_draft(
        db_session,
        base.id,
        WritingDraftUpdate(content="第一章：信上的地址隐晦地指向旧港。"),
        novel_id,
    )
    adopted_draft_id = str(uuid.uuid4())
    first = await editorial_bridge.trigger_post_adoption_rechecks(
        db_session,
        novel_id=novel_id,
        issue_ids=[str(issue.id)],
        adopted_draft_id=adopted_draft_id,
    )
    assert first[0]["issue_id"] == str(issue.id)
    assert first[0]["status"] == "queued"
    assert first[0]["task_id"]

    # 同一采用稿的重复触发：确定性请求标识命中同一轮复核，不重复排队
    replay = await editorial_bridge.trigger_post_adoption_rechecks(
        db_session,
        novel_id=novel_id,
        issue_ids=[str(issue.id)],
        adopted_draft_id=adopted_draft_id,
    )
    assert replay[0]["task_id"] == first[0]["task_id"]
    stored = (await _issue_rows(db_session, novel_id))[0]
    assert len(stored.recheck_json) == 1
    assert stored.recheck_json[-1]["status"] == "queued"


@pytest.mark.asyncio
async def test_post_adoption_recheck_skips_when_basis_stale(
    async_client, db_session, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接复核跳过"})
    ).json()
    novel_id = project["id"]
    text = "第一章：信上的地址指向旧港。"
    draft = await _create_draft(db_session, novel_id, text)
    review = await _seed_review(db_session, novel_id, status="stale")
    issue = await _seed_issue(
        db_session, review, evidence=[_evidence(draft, text, "地址指向旧港")]
    )
    base = await WritingDraftService().get_draft_contract(db_session, novel_id, draft.id)
    await WritingDraftService().update_draft(
        db_session,
        base.id,
        WritingDraftUpdate(content="第一章：信上的地址指向新港。"),
        novel_id,
    )
    results = await editorial_bridge.trigger_post_adoption_rechecks(
        db_session,
        novel_id=novel_id,
        issue_ids=[str(issue.id)],
        adopted_draft_id=str(uuid.uuid4()),
    )
    assert results[0]["status"] == "skipped"
    assert "重新审读" in results[0]["reason"]
    stored = (await _issue_rows(db_session, novel_id))[0]
    assert stored.recheck_json == []


@pytest.mark.asyncio
async def test_post_adoption_recheck_skips_unknown_issue(
    async_client, db_session, monkeypatch
) -> None:
    _enable_editorial(monkeypatch)
    project = (
        await async_client.post("/api/projects", json={"title": "桥接复核缺意见"})
    ).json()
    novel_id = project["id"]
    results = await editorial_bridge.trigger_post_adoption_rechecks(
        db_session,
        novel_id=novel_id,
        issue_ids=[str(uuid.uuid4())],
        adopted_draft_id=str(uuid.uuid4()),
    )
    assert results[0]["status"] == "skipped"
    assert "不可访问" in results[0]["reason"]
