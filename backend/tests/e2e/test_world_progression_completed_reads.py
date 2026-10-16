"""PostgreSQL proof that standing progression counts complete successful reads."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from infrastructure.tasks.models import AsyncTask
from modules.evolution.completed_read_chapters import read_completed_chapter_indices
from modules.evolution.contracts import CommittedPrefix, EvolutionReceipt
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)
from modules.evolution.store import PostgresAttemptStore
from modules.project.models import Project
from modules.story.world_progression_continuous import (
    consider_progression_after_chapter_commit,
    queue_progression_read_check,
)
from modules.story.world_progression_models import (
    StoryWorldProgressionAuthorization,
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
)
from modules.writing.facade import create_published_draft_only


def _step(index, draft, start, end):
    return {
        "scene_index": index,
        "scene_id": str(uuid.uuid4()),
        "source_binding": {
            "draft_id": draft.id,
            "chapter_index": draft.chapter_index,
            "content_hash": draft.content_hash,
            "start_offset": start,
            "end_offset": end,
            "additional_sources": [],
        },
    }


async def _applied(db, novel_id, run_key, step):
    attempt = uuid.uuid4().hex
    db.add(
        EvolutionFrozenAttempt(
            novel_id=novel_id,
            run_key=run_key,
            attempt_key=attempt,
            owner_epoch=1,
            producer_version="synthetic",
            source_manifest_hash="a" * 64,
            payload_json=step,
            status="applied",
        )
    )
    db.add(
        EvolutionReceiptRecord(
            novel_id=novel_id,
            run_key=run_key,
            attempt_key=attempt,
            execution_status="succeeded",
            committed_scene_index=step["scene_index"],
            committed_source_revision=step["source_binding"]["chapter_index"],
            receipt_json={},
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_complete_read_requires_every_scene_and_current_canonical(
    db_session, monkeypatch
):
    import app.main  # noqa: F401 — register Writing's source-change DI

    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")
    novel = uuid.uuid4()
    db_session.add(
        Project(
            id=novel,
            title="完整阅读回执合成测试",
            understanding_engine="evolution",
            understanding_epoch=1,
            understanding_schema_floor=2,
        )
    )
    await db_session.flush()
    draft = await create_published_draft_only(db_session, str(novel), 1, "一", "甲乙丙丁")
    first, second = _step(0, draft, 0, 2), _step(1, draft, 2, 4)
    run_key = "read-" + uuid.uuid4().hex
    run = EvolutionRun(
        novel_id=novel,
        run_key=run_key,
        mode="append",
        owner_epoch=1,
        execution_mode="live",
        status="active",
        reading_plan_json={"steps": [first, second]},
        committed_scene_index=1,
        committed_source_revision=1,
        budget_total=10,
        budget_remaining=8,
    )
    db_session.add(run)
    await db_session.flush()
    assert await read_completed_chapter_indices(db_session, str(novel)) == []
    await _applied(db_session, novel, run_key, first)
    assert await read_completed_chapter_indices(db_session, str(novel)) == []
    await _applied(db_session, novel, run_key, second)
    assert await read_completed_chapter_indices(db_session, str(novel)) == [1]

    fifth = await create_published_draft_only(db_session, str(novel), 5, "五", "戊己")
    fifth_step = _step(2, fifth, 0, 2)
    run.reading_plan_json = {"steps": [first, second, fifth_step]}
    run.committed_scene_index = 2
    await _applied(db_session, novel, run_key, fifth_step)
    assert await read_completed_chapter_indices(db_session, str(novel)) == [1, 5]

    revised = await create_published_draft_only(
        db_session, str(novel), 1, "一改", "新版不同正文"
    )
    assert await read_completed_chapter_indices(db_session, str(novel)) == []
    reread = _step(0, revised, 0, len(revised.content))
    reread_key = "reread-" + uuid.uuid4().hex
    db_session.add(
        EvolutionRun(
            novel_id=novel,
            run_key=reread_key,
            mode="revise",
            owner_epoch=1,
            execution_mode="live",
            status="active",
            reading_plan_json={"steps": [reread]},
            committed_scene_index=0,
            committed_source_revision=1,
            budget_total=10,
            budget_remaining=9,
        )
    )
    await db_session.flush()
    await _applied(db_session, novel, reread_key, reread)
    assert await read_completed_chapter_indices(db_session, str(novel)) == [1]

    root = StoryWorldProgressionRoot(
        novel_id=novel,
        scene_id=uuid.uuid4(),
        source_hash="b" * 64,
        request_json={},
        source_snapshot_json={},
        llm_execution_snapshot_json={},
        run_envelope_json={},
        context_confirmation_id="synthetic",
        status="ready",
    )
    db_session.add(root)
    await db_session.flush()
    branch = StoryWorldProgressionBranch(
        novel_id=novel,
        root_id=root.id,
        branch_kind="start",
        basis_choice="current",
        source_hash="b" * 64,
        request_json={},
        source_snapshot_json={},
        status="complete",
    )
    db_session.add(branch)
    await db_session.flush()
    db_session.add(
        StoryWorldProgressionAuthorization(
            novel_id=novel,
            root_id=root.id,
            branch_id=branch.id,
            enabled=True,
            revision=1,
            participant_ids_json=[],
            every_new_chapters=1,
            last_seen_chapter=1,
            counted_read_chapters_json=[1],
            last_triggered_read_count=1,
            read_count_initialized=True,
            context_confirmation_id="synthetic",
        )
    )
    await db_session.flush()
    result = await consider_progression_after_chapter_commit(
        db_session, novel_id=str(novel), latest_effective_chapter=5
    )
    assert result["status"] == "no_new_read_chapters"


@pytest.mark.asyncio
async def test_successful_read_receipt_and_free_check_share_transaction(
    db_session, monkeypatch
):
    import app.main  # noqa: F401 — compose the Story DI port

    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")
    novel = uuid.uuid4()
    db_session.add(
        Project(
            id=novel,
            title="阅读回执 outbox 合成测试",
            understanding_engine="evolution",
            understanding_epoch=1,
            understanding_schema_floor=2,
        )
    )
    await db_session.flush()
    draft = await create_published_draft_only(db_session, str(novel), 1, "一", "完整正文")
    step = _step(0, draft, 0, len(draft.content))
    run_key = "read-" + uuid.uuid4().hex
    attempt = uuid.uuid4().hex
    db_session.add(
        EvolutionRun(
            novel_id=novel,
            run_key=run_key,
            mode="append",
            owner_epoch=1,
            project_owner_epoch=1,
            execution_mode="live",
            status="active",
            reading_plan_json={"steps": [step]},
            committed_scene_index=-1,
            budget_total=10,
            budget_remaining=9,
        )
    )
    await db_session.flush()
    db_session.add(
        EvolutionFrozenAttempt(
            novel_id=novel,
            run_key=run_key,
            attempt_key=attempt,
            owner_epoch=1,
            producer_version="synthetic",
            source_manifest_hash="a" * 64,
            payload_json=step,
            status="frozen",
        )
    )
    await db_session.flush()
    root = StoryWorldProgressionRoot(
        novel_id=novel,
        scene_id=uuid.uuid4(),
        source_hash="b" * 64,
        request_json={},
        source_snapshot_json={},
        llm_execution_snapshot_json={},
        run_envelope_json={},
        context_confirmation_id="synthetic",
        status="ready",
    )
    db_session.add(root)
    await db_session.flush()
    branch = StoryWorldProgressionBranch(
        novel_id=novel,
        root_id=root.id,
        branch_kind="start",
        basis_choice="current",
        source_hash="b" * 64,
        request_json={},
        source_snapshot_json={},
        status="complete",
    )
    db_session.add(branch)
    await db_session.flush()
    db_session.add(
        StoryWorldProgressionAuthorization(
            novel_id=novel,
            root_id=root.id,
            branch_id=branch.id,
            enabled=True,
            revision=1,
            participant_ids_json=[],
            every_new_chapters=2,
            last_seen_chapter=0,
            counted_read_chapters_json=[],
            last_triggered_read_count=0,
            read_count_initialized=True,
            context_confirmation_id="synthetic",
        )
    )
    await db_session.flush()
    receipt = EvolutionReceipt(
        run_id=run_key,
        attempt_id=attempt,
        owner_epoch=1,
        producer_version="synthetic",
        source_manifest_hash="a" * 64,
        input_state_receipt="c" * 64,
        committed_prefix=CommittedPrefix(
            through_scene_index=0, through_source_revision=1
        ),
        execution_status="succeeded",
        outcome_status="committed",
    )
    await PostgresAttemptStore(db_session, novel).save_receipt(receipt)
    task_count = await db_session.scalar(
        select(func.count())
        .select_from(AsyncTask)
        .where(
            AsyncTask.novel_id == novel,
            AsyncTask.task_type == "story_world_progression_read_commit_check",
        )
    )
    assert task_count == 1
    assert await read_completed_chapter_indices(db_session, str(novel)) == [1]
    assert await queue_progression_read_check(db_session, novel_id=str(novel))
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AsyncTask)
            .where(
                AsyncTask.novel_id == novel,
                AsyncTask.task_type == "story_world_progression_read_commit_check",
            )
        )
        == 1
    )
    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "false")
    assert await queue_progression_read_check(db_session, novel_id=str(novel)) is None
