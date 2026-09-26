from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from core.config import get_settings
from core.errors import ConflictError
from modules.writing.comment_run import _ranges
from modules.writing.comments import create_comment
from modules.writing.schemas import (
    WritingCommentCreate,
    WritingDraftCreate,
    WritingDraftUpdate,
    WritingTargetedRevisionOutput,
)
from modules.writing.semantic_review import validate_candidate_upstream
from modules.writing.services import WritingDraftService
from modules.writing.source_hashing import hash_text


def test_overlapping_comments_merge_without_touching_other_text() -> None:
    content = "甲😀乙丙丁"
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            start_offset=1,
            end_offset=3,
            excerpt="😀乙",
            range_hash=hash_text("😀乙"),
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            start_offset=2,
            end_offset=4,
            excerpt="乙丙",
            range_hash=hash_text("乙丙"),
        ),
    ]
    ranges = _ranges(rows, content)
    assert len(ranges) == 1
    assert ranges[0]["source_text"] == "😀乙丙"
    assert len(ranges[0]["comment_ids"]) == 2
    with pytest.raises(ConflictError, match="无法精确定位"):
        _ranges([SimpleNamespace(**{**vars(rows[0]), "excerpt": "乙😀"})], content)


@pytest.mark.asyncio
async def test_comment_http_scope_staleness_and_idempotent_task(
    async_client, account_llm_connection
) -> None:
    first = (await async_client.post("/api/projects", json={"title": "批注甲"})).json()[
        "id"
    ]
    second = (await async_client.post("/api/projects", json={"title": "批注乙"})).json()[
        "id"
    ]
    draft = (
        await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": first,
                "chapter_index": 1,
                "title": "测试",
                "content": "甲😀乙丙",
            },
        )
    ).json()["draft"]
    path = f"/api/writing/drafts/{draft['id']}/comments"
    payload = {
        "novel_id": first,
        "source_hash": draft["content_hash"],
        "start_offset": 1,
        "end_offset": 3,
        "excerpt": "😀乙",
        "body": "保留表情，调整语气。",
    }
    created = await async_client.post(path, json=payload)
    assert created.status_code == 201, created.text
    comment = created.json()
    assert comment["start_offset"] == 1
    assert (await async_client.get(path, params={"novel_id": second})).status_code == 404
    assert (
        await async_client.post(path, json={**payload, "excerpt": "乙丙"})
    ).status_code == 409

    run = {
        "novel_id": first,
        "draft_id": draft["id"],
        "comment_ids": [comment["id"]],
        "operation_id": str(uuid.uuid4()),
    }
    queued = await async_client.post("/api/writing/comment-runs", json=run)
    assert queued.status_code == 201, queued.text
    replay = await async_client.post("/api/writing/comment-runs", json=run)
    assert replay.status_code == 201, replay.text
    assert replay.json()["task_id"] == queued.json()["task_id"]

    saved = await async_client.put(
        f"/api/writing/drafts/{draft['id']}",
        params={"novel_id": first},
        json={
            "content": "前言。甲😀乙丙",
            "expected_version": draft["version_number"],
            "expected_updated_at": draft["updated_at"],
        },
    )
    assert saved.status_code == 200, saved.text
    current_path = f"/api/writing/drafts/{saved.json()['id']}/comments"
    listed = await async_client.get(current_path, params={"novel_id": first})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["status"] == "stale"
    replay_after_edit = await async_client.post("/api/writing/comment-runs", json=run)
    assert replay_after_edit.status_code == 201, replay_after_edit.text
    assert replay_after_edit.json()["task_id"] == queued.json()["task_id"]
    assert (
        await async_client.post(
            "/api/writing/comment-runs", json={**run, "operation_id": str(uuid.uuid4())}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_comment_candidate_requires_fresh_base_and_independent_pass(
    db_session, test_project_id, monkeypatch
) -> None:
    from infrastructure.stable_hash import stable_hash
    from modules.evidence import facade as evidence_facade

    world = {"items": [], "omissions": []}

    async def fake_world(_db, **_kwargs):
        return world

    monkeypatch.setattr(evidence_facade, "compile_review_world_evidence", fake_world)
    base = await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id, chapter_index=1, title="章", content="原文"
        ),
    )
    candidate = SimpleNamespace(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        content_hash=hash_text("新文"),
        provenance_json={
            "source": "writing_comment_revision",
            "base_draft_id": base.id,
            "base_content_hash": base.content_hash,
            "review_required": True,
        },
    )
    with pytest.raises(ConflictError, match="独立审稿"):
        await validate_candidate_upstream(db_session, candidate)
    candidate.provenance_json["independent_review"] = {
        "draft_hash": candidate.content_hash,
        "verdict": "pass",
        "blocking_count": 0,
        "review_scope": {"cutoff_chapter": 1, "scene_id": None, "excluded_targets": []},
        "context_fingerprint": stable_hash(world),
    }
    await validate_candidate_upstream(db_session, candidate)
    world["items"].append({"source_hash": "changed"})
    with pytest.raises(ConflictError, match="世界资料已变化"):
        await validate_candidate_upstream(db_session, candidate)
    review = candidate.provenance_json["independent_review"]
    review["context_fingerprint"] = stable_hash(world)
    with pytest.raises(ConflictError, match="未完成世界约束审查"):
        await validate_candidate_upstream(db_session, candidate)
    world["items"].clear()
    review["context_fingerprint"] = stable_hash(world)
    await WritingDraftService().update_draft(
        db_session,
        base.id,
        WritingDraftUpdate(content="改后原文"),
        test_project_id,
    )
    with pytest.raises(ConflictError, match="正文已变化"):
        await validate_candidate_upstream(db_session, candidate)


@pytest.mark.asyncio
async def test_ai_review_only_selects_located_important_findings(
    db_session, test_project_id, monkeypatch
) -> None:
    from modules.writing import comment_run
    from modules.writing.repositories import WritingDraftRepository

    draft = await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=1,
            title="章",
            content="甲😀乙丙",
        ),
    )
    saved_draft = await WritingDraftRepository().get(db_session, uuid.UUID(draft.id))

    async def fake_review(_self, _db, **_kwargs):
        return {
            "findings": [
                {
                    "finding_id": key,
                    "severity": severity,
                    "message": key,
                    "location": {"draft_id": draft.id, "excerpt": excerpt},
                }
                for key, severity, excerpt in [
                    ("important", "major", "😀乙"),
                    ("suggestion", "minor", "丙"),
                    ("ambiguous", "blocker", "不存在"),
                ]
            ]
        }

    monkeypatch.setattr(
        comment_run.WritingSemanticWorkflowService, "review_for_task", fake_review
    )
    review, selected, ids, unlocated = await comment_run._review_comments(
        db_session, str(uuid.uuid4()), test_project_id, saved_draft, {}
    )
    assert len(review["findings"]) == len(ids) == 3
    assert [row.body for row in selected] == ["important"]
    assert len(unlocated) == 1


@pytest.mark.asyncio
async def test_asset_proposals_use_separate_confirmation_run(
    db_session, test_project_id, account_llm_connection, monkeypatch
) -> None:
    from modules.assistant.facade import submit_comment_proposals
    from modules.assistant.models import AssistantRun

    monkeypatch.setattr(
        "modules.assistant.service.get_settings",
        lambda: replace(get_settings(), assistant_enabled=True),
    )
    draft = await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id, chapter_index=1, title="章", content="正文"
        ),
    )
    proposal = await submit_comment_proposals(
        db_session,
        novel_id=test_project_id,
        draft_id=draft.id,
        chapter_index=1,
        source_hash=draft.content_hash,
        comments=["核对世界规则"],
        operation_id=str(uuid.uuid4()),
    )
    run = await db_session.get(AssistantRun, uuid.UUID(proposal["run_id"]))
    assert run.status == "pending"
    assert run.request_json["operations"]
    assert all(
        name.startswith(("world.", "story.")) for name in run.request_json["operations"]
    )
    assert run.request_json["allow_web"] is False


@pytest.mark.asyncio
async def test_comment_task_preserves_base_and_prepares_separate_proposal(
    db_session, test_project_id, monkeypatch
) -> None:
    from infrastructure.tasks import facade as task_facade
    from modules.assistant import facade as assistant_facade
    from modules.writing import comment_run
    from modules.writing.models import WritingComment
    from modules.writing.repositories import WritingDraftRepository

    base = await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id, chapter_index=1, title="章", content="甲😀乙丙"
        ),
    )
    comment = await create_comment(
        db_session,
        uuid.UUID(base.id),
        WritingCommentCreate(
            novel_id=test_project_id,
            source_hash=base.content_hash,
            start_offset=1,
            end_offset=3,
            excerpt="😀乙",
            body="把语气写得更坚定",
        ),
    )

    @asynccontextmanager
    async def fake_client(*_args, **_kwargs):
        yield object()

    async def fake_checkpoint(*_args, **_kwargs):
        return None

    async def fake_structured(_client, _request, _schema, **_kwargs):
        return WritingTargetedRevisionOutput.model_validate(
            {"patches": [{"patch_id": "patch-1", "replacement": "😀果断的乙"}]}
        )

    async def fake_governed(_client, *, hooks, **_kwargs):
        output = await hooks.generate(None, ())
        return SimpleNamespace(
            passed=True, output=output, audit=object(), generator_keys=()
        )

    async def fake_review(self, db, *, draft_ids, **_kwargs):
        assert _kwargs["manual_world_scope"].cutoff_chapter == 1
        target = await WritingDraftRepository().get(db, uuid.UUID(draft_ids[0]))
        target.provenance_json = {
            **target.provenance_json,
            "independent_review": {
                "draft_hash": target.content_hash,
                "verdict": "pass",
                "blocking_count": 0,
            },
        }
        await db.flush()
        return {"verdict": "pass", "findings": []}

    proposals = []

    async def fake_proposals(_db, **kwargs):
        proposals.append(kwargs)
        return {"run_id": "proposal-run", "session_id": "proposal-session"}

    monkeypatch.setattr(comment_run, "open_project_snapshot_llm_client", fake_client)
    monkeypatch.setattr(comment_run, "run_managed_structured", fake_structured)
    monkeypatch.setattr(comment_run, "run_governed_generation", fake_governed)
    monkeypatch.setattr(
        comment_run, "knowledge_review_payload", lambda **_kwargs: {"status": "passed"}
    )
    monkeypatch.setattr(task_facade, "checkpoint_handler_session", fake_checkpoint)
    monkeypatch.setattr(
        comment_run.WritingSemanticWorkflowService, "review_for_task", fake_review
    )
    monkeypatch.setattr(assistant_facade, "submit_comment_proposals", fake_proposals)
    task_id = uuid.uuid4()
    task = SimpleNamespace(
        id=task_id,
        meta={
            "novel_id": test_project_id,
            "draft_id": base.id,
            "source_hash": base.content_hash,
            "comment_ids": [comment["id"]],
            "include_ai_review": False,
        },
        update_progress=lambda _value: None,
    )
    result = await comment_run.run_comment_task(
        db_session, task, {"profile": {"model": "test-model"}}
    )
    candidate = await WritingDraftRepository().get(
        db_session, uuid.UUID(result["candidate_draft_id"])
    )
    original = await WritingDraftRepository().get(db_session, uuid.UUID(base.id))
    assert original.content == "甲😀乙丙"
    assert candidate.content == "甲😀果断的乙丙"
    assert candidate.status == "candidate"
    assert candidate.provenance_json["independent_review"]["verdict"] == "pass"
    assert result["asset_proposal_run_id"]["run_id"] == "proposal-run"
    assert proposals[0]["draft_id"] == base.id
    saved_comment = await db_session.get(WritingComment, uuid.UUID(comment["id"]))
    assert saved_comment.last_run_task_id == task_id
