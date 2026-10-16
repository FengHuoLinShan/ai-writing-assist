from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from infrastructure.llm.collaboration import content_hash
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.tasks.models import AsyncTask
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)
from modules.evolution.ownership import switch_project_engine
from modules.evolution.reading_notice_sources import list_reading_notices
from modules.evolution.workflow import (
    ReadingRequest,
    ReadingStart,
    preview_reading,
    start_reading,
)
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft


async def _published_draft(db_session, novel_id: str, chapter_index: int) -> WritingDraft:
    text = f"第 {chapter_index} 章的已发布正文。"
    draft = WritingDraft(
        novel_id=uuid.UUID(novel_id),
        chapter_index=chapter_index,
        title=f"第 {chapter_index} 章",
        content=text,
        content_hash=content_hash(text),
        version_number=1,
        status="published",
    )
    db_session.add(draft)
    await db_session.flush()
    return draft


@pytest.mark.asyncio
async def test_unread_notices_use_scene_cutoff_and_refresh_on_source_change(
    db_session, test_project_id
) -> None:
    novel_id = test_project_id
    await switch_project_engine(
        db_session, novel_id, to_engine="evolution", expected_epoch=1
    )
    first = await _published_draft(db_session, novel_id, 1)
    await _published_draft(db_session, novel_id, 2)
    scene_id = uuid.uuid4()
    db_session.add(
        Scene(
            id=scene_id,
            novel_id=uuid.UUID(novel_id),
            scene_index=0,
            title="第一场",
            chapter_ids=["1"],
            status="canonical",
        )
    )
    await db_session.flush()

    notices = await list_reading_notices(
        db_session,
        novel_id,
        {"scene_id": str(scene_id), "chapter_index": 2},
    )
    unread = next(item for item in notices if item["category"] == "reading_unread")
    assert "从第 1 章开始" in unread["summary"]
    assert unread["target"] == {"chapter_index": 1, "scene_id": str(scene_id)}
    assert unread["actions"][0]["open_evolution_reading"] is True
    assert not [item for item in notices if item["category"] == "reading_run"]

    first.content = "第 1 章的修订后已发布正文。"
    first.content_hash = content_hash(first.content)
    await db_session.flush()
    refreshed = await list_reading_notices(
        db_session,
        novel_id,
        {"scene_id": str(scene_id), "chapter_index": 2},
    )
    changed = next(item for item in refreshed if item["category"] == "reading_unread")
    assert changed["notice_key"] == unread["notice_key"]
    assert changed["basis_fingerprint"] != unread["basis_fingerprint"]


@pytest.mark.asyncio
async def test_failed_read_notice_reads_real_task_state_without_enqueuing_or_provider_io(
    db_session, test_project_id, account_llm_connection, monkeypatch
) -> None:
    novel_id = test_project_id
    await switch_project_engine(
        db_session, novel_id, to_engine="evolution", expected_epoch=1
    )
    source = await _published_draft(db_session, novel_id, 1)
    request = ReadingRequest(
        operation_id=uuid.uuid4(),
        mode="bootstrap",
        end_chapter=1,
        request_limit=5,
    )
    preview = await preview_reading(db_session, novel_id, request)
    authorized = ReadingStart(
        **request.model_dump(),
        expected_fingerprint=preview["fingerprint"],
        authorization_confirmed=True,
    )
    started = await start_reading(db_session, novel_id, authorized)
    task = await db_session.get(AsyncTask, uuid.UUID(started["run"]["task_id"]))
    task.status = "failed"
    await db_session.flush()
    before_counts = {
        model: await db_session.scalar(select(func.count()).select_from(model))
        for model in (
            EvolutionRun,
            EvolutionReceiptRecord,
            EvolutionFrozenAttempt,
            AsyncTask,
        )
    }

    async def forbidden_side_effect(*_args, **_kwargs):
        raise AssertionError("reading notices must not start work or call a provider")

    monkeypatch.setattr(
        "infrastructure.tasks.facade.enqueue_coalesced_task", forbidden_side_effect
    )
    monkeypatch.setattr(
        "modules.evolution.workflow.advance_reading", forbidden_side_effect
    )
    monkeypatch.setattr("modules.evolution.workflow.start_reading", forbidden_side_effect)
    monkeypatch.setattr(
        "modules.evolution.workflow.resume_reading", forbidden_side_effect
    )
    monkeypatch.setattr(OpenAIProvider, "generate", forbidden_side_effect)
    notices = await list_reading_notices(db_session, novel_id, {"chapter_index": 1})

    assert {item["category"] for item in notices} == {
        "reading_unread",
        "reading_run",
    }
    failed = next(item for item in notices if item["category"] == "reading_run")
    assert "失败" in failed["summary"]
    assert failed["target"]["chapter_index"] == 1
    assert failed["actions"][0]["open_evolution_reading"] is True
    assert not db_session.new and not db_session.dirty and not db_session.deleted

    source.status = "draft"
    await db_session.flush()
    without_current_canonical_text = await list_reading_notices(
        db_session, novel_id, {"chapter_index": 1}
    )
    assert [item["category"] for item in without_current_canonical_text] == [
        "reading_run"
    ]
    assert without_current_canonical_text[0]["notice_key"] == failed["notice_key"]

    after_counts = {
        model: await db_session.scalar(select(func.count()).select_from(model))
        for model in before_counts
    }
    assert after_counts == before_counts

    run_row = await db_session.scalar(
        select(EvolutionRun).where(EvolutionRun.run_key == started["run"]["run_key"])
    )
    plan = dict(run_row.reading_plan_json)
    preparation = dict(plan.get("preparation") or {})
    preparation["stage"] = "needs_scene_review"
    plan["preparation"] = preparation
    run_row.reading_plan_json = plan
    task.status = "done"
    await db_session.flush()
    review_notices = await list_reading_notices(db_session, novel_id, {})
    assert [item["category"] for item in review_notices] == ["reading_review"]
    assert review_notices[0]["actions"][0]["page"] == "outline"
