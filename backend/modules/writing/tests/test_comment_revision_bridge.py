"""BR-4 流程 3：Writing facade 批注修订稳定入口的契约测试。

桥接输入为（选区定位 + 意见文本 + 作者处置）：冻结 hash 漂移整体失败
关闭；引文无法唯一定位逐条跳过；同一请求标识幂等；候选 provenance
记录来源意见；采用后经 DI 键触发审读改后复核且失败只降级。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from core.container import container_scope
from core.errors import ConflictError, ValidationError
from modules.writing import comment_run
from modules.writing.contracts import CommentRevisionSelectionContract
from modules.writing.facade import submit_comment_revision
from modules.writing.models import WritingComment
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftUpdate,
    WritingTargetedRevisionOutput,
)
from modules.writing.services import WritingDraftService
from modules.writing.source_hashing import hash_text


def _selection(
    frozen_text: str,
    *,
    ref: str,
    quote: str,
    chapter_index: int = 1,
    content_hash: str | None = None,
    instruction: str = "按意见方向改写这句话",
) -> CommentRevisionSelectionContract:
    return CommentRevisionSelectionContract(
        chapter_index=chapter_index,
        quote=quote,
        frozen_content_hash=content_hash or hash_text(frozen_text),
        body="地址线索或许揭示过早\n读者可能的感受：读者可能过早猜到目的地",
        instruction=instruction,
        ref=ref,
    )


async def _create_draft(db_session, novel_id: str, content: str, chapter_index=1):
    return await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=chapter_index,
            title=f"第{chapter_index}章",
            content=content,
        ),
    )


async def _bridge_comments(db_session, novel_id: str) -> list[WritingComment]:
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
async def test_bridge_locates_quotes_and_enqueues_comment_run(
    db_session, test_project_id, account_llm_connection
) -> None:
    text = "第一章：信上的地址指向旧港。"
    await _create_draft(db_session, test_project_id, text)
    first_ref = str(uuid.uuid4())
    second_ref = str(uuid.uuid4())
    receipt = await submit_comment_revision(
        db_session,
        test_project_id,
        operation_id=str(uuid.uuid4()),
        selections=[
            replace(
                _selection(text, ref=first_ref, quote="地址指向旧港"),
                overlap_confirmed=True,
            ),
            replace(
                _selection(text, ref=second_ref, quote="信上的地址"),
                overlap_confirmed=True,
            ),
        ],
    )
    assert receipt.unlocated == []
    assert len(receipt.tasks) == 1
    task_receipt = receipt.tasks[0]
    assert task_receipt.chapter_index == 1
    assert task_receipt.replayed is False
    assert task_receipt.task_id
    assert sorted(task_receipt.refs) == sorted([first_ref, second_ref])

    rows = await _bridge_comments(db_session, test_project_id)
    assert len(rows) == 2
    by_excerpt = {row.excerpt: row for row in rows}
    anchored = by_excerpt["地址指向旧港"]
    assert text[anchored.start_offset : anchored.end_offset] == "地址指向旧港"
    assert anchored.source_hash == hash_text(text)
    assert "作者处置：按意见方向改写这句话" in anchored.body
    assert all(row.origin == "ai" and row.status == "open" for row in rows)


@pytest.mark.asyncio
async def test_bridge_reports_unlocated_selection_without_blocking_others(
    db_session, test_project_id, account_llm_connection
) -> None:
    text = "第一章：信上的地址指向旧港。"
    await _create_draft(db_session, test_project_id, text)
    located_ref = str(uuid.uuid4())
    missing_ref = str(uuid.uuid4())
    receipt = await submit_comment_revision(
        db_session,
        test_project_id,
        operation_id=str(uuid.uuid4()),
        selections=[
            _selection(text, ref=located_ref, quote="地址指向旧港"),
            # hash 相同但引文不在稿内（如审查器引文异常）：该条不可定位
            _selection(text, ref=missing_ref, quote="地址指向新港"),
        ],
    )
    assert [entry.ref for entry in receipt.unlocated] == [missing_ref]
    assert "无法定位" in receipt.unlocated[0].reason
    assert len(receipt.tasks) == 1
    assert receipt.tasks[0].refs == [located_ref]


@pytest.mark.asyncio
async def test_bridge_fails_closed_on_frozen_hash_drift(
    db_session, test_project_id, account_llm_connection
) -> None:
    frozen_text = "第一章：信上的地址指向旧港。"
    base = await _create_draft(db_session, test_project_id, frozen_text)
    await WritingDraftService().update_draft(
        db_session,
        base.id,
        WritingDraftUpdate(content="第一章：信上的地址指向新港。"),
        test_project_id,
    )
    stale_hash = hash_text(frozen_text)
    with pytest.raises(ConflictError, match="重新审读"):
        await submit_comment_revision(
            db_session,
            test_project_id,
            operation_id=str(uuid.uuid4()),
            selections=[
                _selection(
                    frozen_text,
                    ref=str(uuid.uuid4()),
                    quote="信上的地址",
                    content_hash=stale_hash,
                )
            ],
        )
    assert await _bridge_comments(db_session, test_project_id) == []


@pytest.mark.asyncio
async def test_bridge_replay_is_idempotent(
    db_session, test_project_id, account_llm_connection
) -> None:
    text = "第一章：信上的地址指向旧港。"
    await _create_draft(db_session, test_project_id, text)
    ref = str(uuid.uuid4())
    operation_id = str(uuid.uuid4())
    selections = [_selection(text, ref=ref, quote="地址指向旧港")]
    first = await submit_comment_revision(
        db_session, test_project_id, operation_id=operation_id, selections=selections
    )
    replay = await submit_comment_revision(
        db_session, test_project_id, operation_id=operation_id, selections=selections
    )
    assert replay.tasks[0].task_id == first.tasks[0].task_id
    assert replay.tasks[0].replayed is True
    assert len(await _bridge_comments(db_session, test_project_id)) == 1


@pytest.mark.asyncio
async def test_bridge_requires_instruction(
    db_session, test_project_id, account_llm_connection
) -> None:
    text = "第一章：信上的地址指向旧港。"
    await _create_draft(db_session, test_project_id, text)
    with pytest.raises(ValidationError, match="处置说明"):
        await submit_comment_revision(
            db_session,
            test_project_id,
            operation_id=str(uuid.uuid4()),
            selections=[
                _selection(
                    text,
                    ref=str(uuid.uuid4()),
                    quote="地址指向旧港",
                    instruction="  ",
                )
            ],
        )


def _comment_run_patches(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_client(*_args, **_kwargs):
        yield object()

    async def fake_structured(_client, _request, _schema, **_kwargs):
        return WritingTargetedRevisionOutput.model_validate(
            {"patches": [{"patch_id": "patch-1", "replacement": "果断的地址线索"}]}
        )

    async def fake_governed(_client, *, hooks, **_kwargs):
        output = await hooks.generate(None, ())
        return SimpleNamespace(
            passed=True, output=output, audit=object(), generator_keys=()
        )

    async def fake_checkpoint(*_args, **_kwargs):
        return None

    monkeypatch.setattr(comment_run, "open_project_snapshot_llm_client", fake_client)
    monkeypatch.setattr(comment_run, "run_managed_structured", fake_structured)
    monkeypatch.setattr(comment_run, "run_governed_generation", fake_governed)
    monkeypatch.setattr(
        comment_run, "knowledge_review_payload", lambda **_kwargs: {"status": "passed"}
    )
    from infrastructure.tasks import facade as task_facade

    monkeypatch.setattr(task_facade, "checkpoint_handler_session", fake_checkpoint)


async def _add_bridge_comment(db_session, base, text: str, excerpt: str):
    row = WritingComment(
        novel_id=uuid.UUID(str(base.novel_id)),
        draft_id=uuid.UUID(base.id),
        chapter_index=base.chapter_index,
        version_number=base.version_number,
        source_hash=base.content_hash,
        range_hash=hash_text(excerpt),
        start_offset=text.find(excerpt),
        end_offset=text.find(excerpt) + len(excerpt),
        excerpt=excerpt,
        body="地址线索或许揭示过早\n作者处置：按意见方向改写这句话",
        origin="ai",
        status="open",
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.asyncio
async def test_bridge_candidate_provenance_records_editorial_issues(
    db_session, test_project_id, monkeypatch
) -> None:
    text = "第一章：信上的地址指向旧港。"
    base = await _create_draft(db_session, test_project_id, text)
    comment = await _add_bridge_comment(db_session, base, text, "地址指向旧港")
    issue_id = str(uuid.uuid4())

    async def passing_review(self, db, *, draft_ids, **_kwargs):
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

    _comment_run_patches(monkeypatch)
    monkeypatch.setattr(
        comment_run.WritingSemanticWorkflowService, "review_for_task", passing_review
    )
    bridge_task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": test_project_id,
            "draft_id": base.id,
            "source_hash": base.content_hash,
            "comment_ids": [str(comment.id)],
            "include_ai_review": False,
            "editorial_refs": {str(comment.id): issue_id},
        },
        update_progress=lambda _value: None,
    )
    result = await comment_run.run_comment_task(
        db_session, bridge_task, {"profile": {"model": "test-model"}}
    )
    candidate = await WritingDraftRepository().get(
        db_session, uuid.UUID(result["candidate_draft_id"])
    )
    assert candidate.status == "candidate"
    assert candidate.provenance_json["editorial_issue_ids"] == [issue_id]

    # 无桥接来源的普通批注修订保持原 provenance 形态
    normal_task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": test_project_id,
            "draft_id": base.id,
            "source_hash": base.content_hash,
            "comment_ids": [str(comment.id)],
            "include_ai_review": False,
        },
        update_progress=lambda _value: None,
    )
    normal_result = await comment_run.run_comment_task(
        db_session, normal_task, {"profile": {"model": "test-model"}}
    )
    normal_candidate = await WritingDraftRepository().get(
        db_session, uuid.UUID(normal_result["candidate_draft_id"])
    )
    assert "editorial_issue_ids" not in normal_candidate.provenance_json


@pytest.mark.asyncio
async def test_adoption_of_bridge_candidate_triggers_editorial_recheck(
    db_session, test_project_id, monkeypatch
) -> None:
    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    issue_id = str(uuid.uuid4())
    candidate = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=1,
            title="修订候选",
            content="修订后的正文",
            provenance_json={
                "source": "writing_comment_revision",
                "knowledge_review": {"status": "passed"},
                "editorial_issue_ids": [issue_id],
            },
        ),
        status="candidate",
    )
    calls: list[dict] = []

    async def fake_rechecks(_db, **kwargs):
        calls.append(kwargs)
        return [{"issue_id": issue_id, "status": "queued"}]

    with container_scope({"assistant.editorial.post_adoption_rechecks": fake_rechecks}):
        adopted = await WritingDraftService().adopt_candidate_to_working(
            db_session, str(candidate.id), test_project_id
        )
    assert calls == [
        {
            "novel_id": test_project_id,
            "issue_ids": [issue_id],
            "adopted_draft_id": adopted.id,
        }
    ]
    assert adopted.provenance_json["editorial_issue_ids"] == [issue_id]


@pytest.mark.asyncio
async def test_adoption_degrades_when_recheck_service_unavailable(
    db_session, test_project_id, monkeypatch
) -> None:
    async def accept_candidate(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(
        "modules.writing.semantic_review.validate_candidate_upstream",
        accept_candidate,
    )
    candidate = await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=test_project_id,
            chapter_index=1,
            title="修订候选",
            content="修订后的正文",
            provenance_json={
                "source": "writing_comment_revision",
                "knowledge_review": {"status": "passed"},
                "editorial_issue_ids": [str(uuid.uuid4())],
            },
        ),
        status="candidate",
    )
    # 未注册 DI 键（如助手组合根缺失）：采用不受影响，只降级。
    adopted = await WritingDraftService().adopt_candidate_to_working(
        db_session, str(candidate.id), test_project_id
    )
    assert adopted.status != "deprecated"
    stored_candidate = await WritingDraftRepository().get(db_session, candidate.id)
    assert stored_candidate.status == "deprecated"
