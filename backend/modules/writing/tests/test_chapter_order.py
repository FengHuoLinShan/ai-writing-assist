from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from core.container import container_scope
from core.errors import ConflictError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from infrastructure.tasks.models import AsyncTask
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.assistant.operation_scope import require_operation_targets
from modules.evidence.compilation.facade import (
    attach_result_ref,
    confirm_context,
    require_confirmation,
)
from modules.evidence.contracts import ContextConfirmationRequest
from modules.evidence.indexing.models import RagIndexState
from modules.story.continuity.chapter_order import StoryChapterOrderService
from modules.story.continuity.models import (
    MemoryEvent,
    MemorySceneCheckpoint,
    MemorySceneSnapshot,
    MemorySnapshot,
    StoryChapterOrderReceipt,
)
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
    SceneChapterLink,
    SceneSpan,
    SceneSummaryCheckpoint,
)
from modules.writing.chapter_order_operations import (
    ChapterOrderHistoryArgs,
    ChapterOrderOperationArgs,
    _history_read,
    _reorder_prepare,
)
from modules.writing.conflict_check_service import WritingConflictCheckService
from modules.writing.draft_service import WritingChapterOrderService
from modules.writing.models import (
    WritingChapterOrderOperation,
    WritingComment,
    WritingConflictCheck,
    WritingConflictItem,
    WritingDraft,
)
from modules.writing.repositories import WritingConflictCheckRepository
from modules.writing.schemas import ChapterOrderPreviewRequest
from modules.writing.source_hashing import hash_text


@pytest.mark.asyncio
async def test_assistant_chapter_order_rejects_narrow_and_excluded_work(
    db_session, test_project_id
) -> None:
    current = AssistantOperationContext(
        str(uuid.uuid4()), str(uuid.uuid4()), WorkContext(chapter_index=1)
    )
    excluded = AssistantOperationContext(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        WorkContext(scope="project", excluded_targets=[str(uuid.uuid4())]),
    )
    with container_scope(
        {ASSISTANT_REQUIRE_OPERATION_TARGETS: require_operation_targets}
    ):
        for context in (current, excluded):
            with pytest.raises(ConflictError):
                await _reorder_prepare(
                    db_session,
                    test_project_id,
                    ChapterOrderOperationArgs(chapter_indices=[2, 1]),
                    context=context,
                )
            with pytest.raises(ConflictError):
                await _history_read(
                    db_session,
                    test_project_id,
                    ChapterOrderHistoryArgs(),
                    context=context,
                )
    assert not (
        await db_session.scalars(select(WritingChapterOrderOperation))
    ).all()


async def _seed_story_and_writing(db, novel_id: str) -> dict[str, object]:
    nid = uuid.UUID(novel_id)
    drafts = [
        WritingDraft(
            novel_id=nid,
            chapter_index=1,
            version_number=1,
            status="canonical",
            title="潮汐",
            content="潮汐退去。",
            content_hash=hash_text("潮汐退去。"),
        ),
        WritingDraft(
            novel_id=nid,
            chapter_index=1,
            version_number=2,
            status="draft",
            title="潮汐·修订",
            content="潮汐退去，露出旧船。",
            content_hash=hash_text("潮汐退去，露出旧船。"),
        ),
        WritingDraft(
            novel_id=nid,
            chapter_index=2,
            version_number=1,
            status="draft",
            title="旧港",
            content="旧港没有灯。",
            content_hash=hash_text("旧港没有灯。"),
        ),
        WritingDraft(
            novel_id=nid,
            chapter_index=3,
            version_number=1,
            status="published",
            title="来信",
            content="信封里没有署名。",
            content_hash=hash_text("信封里没有署名。"),
        ),
    ]
    db.add_all(drafts)
    await db.flush()

    comment = WritingComment(
        novel_id=nid,
        draft_id=drafts[1].id,
        chapter_index=1,
        version_number=2,
        source_hash=drafts[1].content_hash,
        range_hash=hash_text("旧船"),
        start_offset=7,
        end_offset=9,
        excerpt="旧船",
        body="这个线索需要留到下一章。",
        origin="author",
        status="open",
    )
    scene = Scene(
        novel_id=nid,
        scene_index=0,
        title="退潮后",
        chapter_ids=["1"],
        scene_chunks=[
            {
                "chapter_index": 1,
                "chapter_id": "1",
                "source_draft_id": str(drafts[1].id),
                "source_content_hash": drafts[1].content_hash,
                "start_offset": 0,
                "end_offset": len(drafts[1].content),
                "mapping_status": "exact",
            }
        ],
    )
    db.add(scene)
    await db.flush()
    scene_link = SceneChapterLink(
        novel_id=nid,
        scene_id=scene.id,
        chapter_index=1,
    )
    scene_span = SceneSpan(
        novel_id=nid,
        scene_id=scene.id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=drafts[1].id,
        source_content_hash=drafts[1].content_hash,
        start_offset=0,
        end_offset=len(drafts[1].content),
        part_no=0,
        mapping_status="exact",
        source="manual",
        status="draft",
    )
    event = MemoryEvent(
        novel_id=nid,
        chapter_index=1,
        scene_id=scene.id,
        scene_index=0,
        scene_sequence=1,
        sequence=1,
        dimension="entities",
        event_type="entity_updated",
        snapshot_before={"name": "旧船"},
        snapshot_after={"name": "旧船", "state": "显露", "meta": {"id": "private"}},
        source="author",
    )
    memory_snapshot = MemorySnapshot(
        novel_id=nid,
        chapter_index=1,
        status="current",
        full_state={"entities": ["old"]},
        events_until=1,
    )
    checkpoint = MemorySceneCheckpoint(
        novel_id=nid,
        scene_id=scene.id,
        scene_index=0,
        stage_index=1,
        dimension="entities",
        status="ready",
        source="system_generated",
        confirmed=False,
        is_current=True,
        state_json={"entities": ["old"]},
        evidence_refs=[],
        display_summary="旧船显露",
        source_hash=hash_text("checkpoint"),
    )
    scene_snapshot = MemorySceneSnapshot(
        novel_id=nid,
        scene_id=scene.id,
        scene_index=0,
        stage_index=1,
        snapshot_reasons=["scene_end"],
        full_state={"entities": ["old"]},
        source_hash=hash_text("scene-snapshot"),
        is_current=True,
        is_latest=True,
    )
    summary = SceneSummaryCheckpoint(
        novel_id=nid,
        scene_id=scene.id,
        content_mode="canonical",
        through_chapter=1,
        through_offset=-1,
        summary="退潮后发现旧船。",
        source_refs=[],
        based_on_hash=hash_text("scene-summary"),
        source="derived",
        status="ready",
    )
    thread = PlotThread(
        novel_id=nid,
        name="旧船线索",
        thread_type="mystery",
        start_chapter=1,
        planned_payoff_chapter=3,
        status="active",
    )
    foreshadowing = ForeshadowingPlan(
        novel_id=nid,
        name="旧船",
        planned_seed_chapter=1,
        planned_reinforce_chapters=[2],
        planned_payoff_chapter=3,
        status="draft",
    )
    reveal = RevealPlan(
        novel_id=nid,
        target_type="character",
        target_id=uuid.uuid4(),
        secret_summary="旧船属于失踪的船长。",
        reveal_stages=[
            {"stage_index": 1, "chapter_index": 1, "reveal_content": "发现船名"},
            {"stage_index": 2, "chapter_index": 3, "reveal_content": "确认船主"},
        ],
        status="draft",
    )
    db.add_all(
        [
            comment,
            scene_link,
            scene_span,
            event,
            memory_snapshot,
            checkpoint,
            scene_snapshot,
            summary,
            thread,
            foreshadowing,
            reveal,
        ]
    )
    await db.flush()
    return {
        "drafts": drafts,
        "comment": comment,
        "scene": scene,
        "scene_link": scene_link,
        "scene_span": scene_span,
        "event": event,
        "memory_snapshot": memory_snapshot,
        "checkpoint": checkpoint,
        "scene_snapshot": scene_snapshot,
        "summary": summary,
        "thread": thread,
        "foreshadowing": foreshadowing,
        "reveal": reveal,
    }


@pytest.mark.asyncio
async def test_chapter_reorder_moves_all_assets_and_restores(
    db_session, test_project_id
) -> None:
    seeded = await _seed_story_and_writing(db_session, test_project_id)
    invalidations: list[str] = []

    async def invalidate(_db, *, novel_id: str) -> None:
        invalidations.append(novel_id)

    service = WritingChapterOrderService()
    story = StoryChapterOrderService()
    with container_scope(
        {
            "story.chapter_order": story,
            "story.invalidate_world_progression_for_reorder": invalidate,
        }
    ):
        preview = await service.preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[3, 1, 2]),
        )
        assert preview.story_impact["blockers"] == []
        assert preview.story_impact["writing"] == {
            "draft_version_count": 4,
            "comment_count": 1,
            "unlisted_version_chapter_count": 0,
        }
        assert len(preview.moves) == 3
        assert {move.title for move in preview.moves} == {
            "潮汐·修订",
            "旧港",
            "来信",
        }

        executed = await service.confirm(
            db_session,
            test_project_id,
            str(preview.receipt_id),
            expected_preview_hash=preview.preview_hash,
            confirmed=True,
        )
        assert executed.status == "executed"
        assert executed.chapter_map == {3: 1, 1: 2, 2: 3}
        assert executed.result_ref == {
            "type": "writing_chapter_order",
            "id": str(preview.receipt_id),
        }
        assert (
            await service.confirm(
                db_session,
                test_project_id,
                str(preview.receipt_id),
                expected_preview_hash=preview.preview_hash,
                confirmed=True,
            )
        ).replayed is True

        drafts = list(
            (
                await db_session.scalars(
                    select(WritingDraft).where(
                        WritingDraft.novel_id == uuid.UUID(test_project_id)
                    )
                )
            ).all()
        )
        index_by_id = {row.id: row.chapter_index for row in drafts}
        original = seeded["drafts"]
        assert index_by_id[original[0].id] == 2
        assert index_by_id[original[1].id] == 2
        assert index_by_id[original[2].id] == 3
        assert index_by_id[original[3].id] == 1
        assert {row.id: row.content_hash for row in drafts} == {
            row.id: row.content_hash for row in original
        }
        comment = await db_session.get(WritingComment, seeded["comment"].id)
        assert comment is not None
        assert comment.draft_id == original[1].id
        assert comment.chapter_index == 2
        assert comment.body == "这个线索需要留到下一章。"

        scene = await db_session.get(Scene, seeded["scene"].id)
        link = await db_session.get(SceneChapterLink, seeded["scene_link"].id)
        span = await db_session.get(SceneSpan, seeded["scene_span"].id)
        assert scene is not None and scene.chapter_ids == ["2"]
        assert scene.scene_chunks[0]["chapter_index"] == 2
        assert link is not None and link.chapter_index == 2
        assert span is not None and span.chapter_index == 2
        assert span.source_draft_id == original[1].id
        assert span.source_content_hash == original[1].content_hash
        assert (await db_session.get(MemoryEvent, seeded["event"].id)).chapter_index == 1
        assert (
            await db_session.get(MemorySnapshot, seeded["memory_snapshot"].id)
        ).status == "stale"
        assert (
            await db_session.get(MemorySceneCheckpoint, seeded["checkpoint"].id)
        ).status == "superseded"
        assert (
            await db_session.get(MemorySceneSnapshot, seeded["scene_snapshot"].id)
        ).is_latest is False
        assert (
            await db_session.get(SceneSummaryCheckpoint, seeded["summary"].id)
        ).status == "needs_revalidation"
        assert (await db_session.get(PlotThread, seeded["thread"].id)).start_chapter == 2
        assert (
            await db_session.get(ForeshadowingPlan, seeded["foreshadowing"].id)
        ).planned_reinforce_chapters == [3]
        assert (await db_session.get(RevealPlan, seeded["reveal"].id)).reveal_stages[0][
            "chapter_index"
        ] == 2

        restore_preview = await service.preview_restore(
            db_session, test_project_id, str(preview.receipt_id)
        )
        assert restore_preview.can_restore is True
        restored = await service.restore(
            db_session,
            test_project_id,
            str(preview.receipt_id),
            expected_preview_hash=restore_preview.restore_preview_hash,
            confirmed=True,
        )
        assert restored.status == "restored"
        assert (
            await service.restore(
                db_session,
                test_project_id,
                str(preview.receipt_id),
                expected_preview_hash=restore_preview.restore_preview_hash,
                confirmed=True,
            )
        ).replayed is True

    drafts = list(
        (
            await db_session.scalars(
                select(WritingDraft).where(
                    WritingDraft.novel_id == uuid.UUID(test_project_id)
                )
            )
        ).all()
    )
    index_by_id = {row.id: row.chapter_index for row in drafts}
    original = seeded["drafts"]
    assert index_by_id[original[0].id] == 1
    assert index_by_id[original[1].id] == 1
    assert index_by_id[original[2].id] == 2
    assert index_by_id[original[3].id] == 3
    assert (await db_session.get(WritingComment, seeded["comment"].id)).chapter_index == 1
    assert (await db_session.get(Scene, seeded["scene"].id)).chapter_ids == ["1"]
    assert (
        await db_session.get(MemorySnapshot, seeded["memory_snapshot"].id)
    ).status == "current"
    assert (
        await db_session.get(MemorySceneCheckpoint, seeded["checkpoint"].id)
    ).is_current is True
    assert (
        await db_session.get(MemorySceneSnapshot, seeded["scene_snapshot"].id)
    ).is_latest is True
    assert (
        await db_session.get(SceneSummaryCheckpoint, seeded["summary"].id)
    ).status == "ready"
    assert (await db_session.get(PlotThread, seeded["thread"].id)).start_chapter == 1
    assert (
        await db_session.get(ForeshadowingPlan, seeded["foreshadowing"].id)
    ).planned_reinforce_chapters == [2]
    assert (await db_session.get(RevealPlan, seeded["reveal"].id)).reveal_stages[0][
        "chapter_index"
    ] == 1
    assert invalidations == [test_project_id, test_project_id]
    receipts = list(
        (
            await db_session.scalars(
                select(StoryChapterOrderReceipt).where(
                    StoryChapterOrderReceipt.novel_id == uuid.UUID(test_project_id)
                )
            )
        ).all()
    )
    operations = list(
        (
            await db_session.scalars(
                select(WritingChapterOrderOperation).where(
                    WritingChapterOrderOperation.novel_id == uuid.UUID(test_project_id)
                )
            )
        ).all()
    )
    assert len(receipts) == len(operations) == 1
    assert receipts[0].id == operations[0].story_receipt_id == operations[0].id
    assert operations[0].status == receipts[0].status == "restored"


@pytest.mark.asyncio
async def test_chapter_reorder_stales_source_checks_and_indexes_on_both_moves(
    db_session, test_project_id
) -> None:
    seeded = await _seed_story_and_writing(db_session, test_project_id)
    draft = seeded["drafts"][1]
    nid = uuid.UUID(test_project_id)
    check = WritingConflictCheck(
        novel_id=nid,
        chapter_index=1,
        draft_id=draft.id,
        version_number=draft.version_number,
        scope={"chapter_index": 1, "content_hash": draft.content_hash},
        status="completed",
        summary_json={},
    )
    db_session.add(check)
    await db_session.flush()
    db_session.add(
        WritingConflictItem(
            novel_id=nid,
            check_id=check.id,
            kind="required_missing",
            severity="high",
            source_module="outline",
            evidence_summary="需补充旧船线索",
            status="open",
        )
    )
    first_confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="writing.generate",
            task="根据当前正文继续写作",
            scope="chapter",
            chapter_index=1,
        ),
    )
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=first_confirmation.id,
        result_type="writing_draft",
        result_id=str(draft.id),
        status="adopted",
    )
    service = WritingChapterOrderService()
    with container_scope(
        {
            "story.chapter_order": StoryChapterOrderService(),
            "story.invalidate_world_progression_for_reorder": (
                lambda _db, *, novel_id: _noop_invalidation(novel_id)
            ),
        }
    ):
        preview = await service.preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[3, 1, 2]),
        )
        await service.confirm(
            db_session,
            test_project_id,
            str(preview.receipt_id),
            expected_preview_hash=preview.preview_hash,
            confirmed=True,
        )
        await db_session.refresh(check)
        assert check.chapter_index == 2
        assert check.scope["chapter_index"] == 1
        assert (
            await WritingConflictCheckRepository().build_latest_snapshot(
                db_session, novel_id=nid, chapter_index=2, scene_id=None
            )
            is None
        )
        attention = await WritingConflictCheckService().get_author_attention_items(
            db_session, test_project_id
        )
        assert any(item.key == f"writing:recheck:{check.id}" for item in attention)
        stored = await require_confirmation(
            db_session,
            novel_id=test_project_id,
            action="writing.generate",
            confirmation_id=first_confirmation.id,
        )
        assert stored.result_status == "stale_context"
        assert "chapter_order_changed" in stored.stale_reasons
        states = list(
            (
                await db_session.scalars(
                    select(RagIndexState).where(RagIndexState.novel_id == nid)
                )
            ).all()
        )
        assert {(row.chapter_index, row.content_mode) for row in states} == {
            (chapter, mode)
            for chapter in (1, 2, 3)
            for mode in ("working", "canonical")
        }
        assert all(row.status == "pending" for row in states)
        assert all(row.active_task_id is not None for row in states)
        index_tasks = list(
            (
                await db_session.scalars(
                    select(AsyncTask).where(
                        AsyncTask.novel_id == nid,
                        AsyncTask.task_type == "rag_index_chapter",
                    ))
            ).all()
        )
        assert len(index_tasks) == 6
        assert all(task.status == "pending" for task in index_tasks)

        second_confirmation = await confirm_context(
            db_session,
            ContextConfirmationRequest(
                novel_id=test_project_id,
                action="writing.generate",
                task="根据重排后的正文继续写作",
                scope="chapter",
                chapter_index=2,
            ),
        )
        await attach_result_ref(
            db_session,
            novel_id=test_project_id,
            confirmation_id=second_confirmation.id,
            result_type="writing_draft",
            result_id=str(draft.id),
            status="adopted",
        )
        restore_preview = await service.preview_restore(
            db_session, test_project_id, str(preview.receipt_id)
        )
        assert restore_preview.can_restore
        await service.restore(
            db_session,
            test_project_id,
            str(preview.receipt_id),
            expected_preview_hash=restore_preview.restore_preview_hash,
            confirmed=True,
        )
        await db_session.refresh(check)
        assert check.chapter_index == 1
        assert check.scope["chapter_index"] == 1
        assert (
            await WritingConflictCheckRepository().build_latest_snapshot(
                db_session, novel_id=nid, chapter_index=1, scene_id=None
            )
            is not None
        )
        stored = await require_confirmation(
            db_session,
            novel_id=test_project_id,
            action="writing.generate",
            confirmation_id=second_confirmation.id,
        )
        assert stored.result_status == "stale_context"
        assert "chapter_order_changed" in stored.stale_reasons
        states = list(
            (
                await db_session.scalars(
                    select(RagIndexState).where(RagIndexState.novel_id == nid)
                )
            ).all()
        )
        assert all(row.status == "pending" for row in states)
        assert {
            row.content_mode: row.requested_source_id
            for row in states
            if row.chapter_index == 1
        } == {"working": draft.id, "canonical": None}


async def _noop_invalidation(_novel_id: str) -> None:
    return None


@pytest.mark.asyncio
async def test_chapter_reorder_preview_blocks_unlisted_versions_and_hash_drift(
    db_session, test_project_id
) -> None:
    nid = uuid.UUID(test_project_id)
    first = WritingDraft(
        novel_id=nid,
        chapter_index=1,
        version_number=1,
        status="draft",
        title="一",
        content="正文一",
        content_hash=hash_text("被改过的正文"),
    )
    second = WritingDraft(
        novel_id=nid,
        chapter_index=2,
        version_number=1,
        status="draft",
        title="二",
        content="正文二",
        content_hash=hash_text("正文二"),
    )
    archived_only = WritingDraft(
        novel_id=nid,
        chapter_index=9,
        version_number=1,
        status="deprecated",
        title="旧章",
        content="保留历史",
        content_hash=hash_text("保留历史"),
    )
    db_session.add_all([first, second, archived_only])
    await db_session.flush()

    with container_scope(
        {
            "story.chapter_order": StoryChapterOrderService(),
            "story.invalidate_world_progression_for_reorder": lambda *_args, **_kwargs: (
                None
            ),
        }
    ):
        preview = await WritingChapterOrderService().preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[2, 1]),
        )

    kinds = {item["kind"] for item in preview.story_impact["blockers"]}
    assert "unlisted_chapter_versions" in kinds
    assert "writing_source_hash_mismatch" in kinds
    assert preview.story_impact["writing"]["unlisted_version_chapter_count"] == 1


@pytest.mark.asyncio
async def test_chapter_reorder_blocks_mismatched_span_source_and_inverted_scene(
    db_session, test_project_id
) -> None:
    seeded = await _seed_story_and_writing(db_session, test_project_id)
    scene = seeded["scene"]
    span = seeded["scene_span"]
    span.source_content_hash = "f" * 64
    scene.chapter_ids = ["1", "2"]
    scene.scene_chunks = [
        *scene.scene_chunks,
        {"chapter_index": 2, "chapter_id": "2"},
    ]
    db_session.add(
        SceneChapterLink(
            novel_id=uuid.UUID(test_project_id),
            scene_id=scene.id,
            chapter_index=2,
        )
    )
    await db_session.flush()
    with container_scope({"story.chapter_order": StoryChapterOrderService()}):
        preview = await WritingChapterOrderService().preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[2, 1, 3]),
        )
    kinds = {item["kind"] for item in preview.story_impact["blockers"]}
    assert "scene_span_source" in kinds
    assert "scene_cross_chapter_order" in kinds


@pytest.mark.asyncio
async def test_chapter_reorder_blocks_noncontiguous_outline_arc(
    db_session, test_project_id
) -> None:
    await _seed_story_and_writing(db_session, test_project_id)
    db_session.add(
        OutlineArc(
            novel_id=uuid.UUID(test_project_id),
            title="开篇篇章",
            start_chapter=1,
            end_chapter=2,
        )
    )
    await db_session.flush()
    with container_scope({"story.chapter_order": StoryChapterOrderService()}):
        preview = await WritingChapterOrderService().preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[1, 3, 2]),
        )
    assert any(
        item["kind"] == "plan_interval_non_contiguous"
        for item in preview.story_impact["blockers"]
    )


@pytest.mark.asyncio
async def test_chapter_reorder_restore_refuses_to_overwrite_later_draft_edit(
    db_session, test_project_id
) -> None:
    seeded = await _seed_story_and_writing(db_session, test_project_id)
    service = WritingChapterOrderService()

    async def invalidate(_db, *, novel_id: str) -> None:
        assert novel_id == test_project_id

    with container_scope(
        {
            "story.chapter_order": StoryChapterOrderService(),
            "story.invalidate_world_progression_for_reorder": invalidate,
        }
    ):
        preview = await service.preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[3, 1, 2]),
        )
        await service.confirm(
            db_session,
            test_project_id,
            str(preview.receipt_id),
            expected_preview_hash=preview.preview_hash,
            confirmed=True,
        )
        edited = await db_session.get(WritingDraft, seeded["drafts"][1].id)
        assert edited is not None
        edited.content = "重排后作者补充的新正文。"
        edited.content_hash = hash_text(edited.content)
        await db_session.flush()

        restore_preview = await service.preview_restore(
            db_session, test_project_id, str(preview.receipt_id)
        )
        assert restore_preview.can_restore is False
        assert any(
            item["kind"] == "writing_source_changed" for item in restore_preview.blockers
        )
        with pytest.raises(ConflictError, match="来源已有变化"):
            await service.restore(
                db_session,
                test_project_id,
                str(preview.receipt_id),
                expected_preview_hash=restore_preview.restore_preview_hash,
                confirmed=True,
            )


@pytest.mark.asyncio
async def test_chapter_reorder_restore_revalidates_new_unbound_check(
    db_session, test_project_id
) -> None:
    await _seed_story_and_writing(db_session, test_project_id)
    service = WritingChapterOrderService()
    with container_scope(
        {
            "story.chapter_order": StoryChapterOrderService(),
            "story.invalidate_world_progression_for_reorder": (
                lambda _db, *, novel_id: _noop_invalidation(novel_id)
            ),
        }
    ):
        preview = await service.preview(
            db_session,
            test_project_id,
            ChapterOrderPreviewRequest(chapter_indices=[3, 1, 2]),
        )
        await service.confirm(
            db_session,
            test_project_id,
            str(preview.receipt_id),
            expected_preview_hash=preview.preview_hash,
            confirmed=True,
        )
        db_session.add(
            WritingConflictCheck(
                novel_id=uuid.UUID(test_project_id),
                chapter_index=2,
                scope={"chapter_index": 2},
                status="completed",
                summary_json={},
            )
        )
        await db_session.flush()
        restore_preview = await service.preview_restore(
            db_session, test_project_id, str(preview.receipt_id)
        )
        assert not restore_preview.can_restore
        assert any(
            item["kind"] == "writing_source_changed"
            for item in restore_preview.blockers
        )


@pytest.mark.asyncio
async def test_chapter_reorder_rolls_back_when_invalidation_fails(
    db_session, test_project_id
) -> None:
    seeded = await _seed_story_and_writing(db_session, test_project_id)
    draft = seeded["drafts"][1]
    check = WritingConflictCheck(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        draft_id=draft.id,
        version_number=draft.version_number,
        scope={"chapter_index": 1, "content_hash": draft.content_hash},
        status="completed",
        summary_json={},
    )
    db_session.add(check)
    confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=test_project_id,
            action="writing.generate",
            task="继续当前章节",
            scope="chapter",
            chapter_index=1,
        ),
    )
    await attach_result_ref(
        db_session,
        novel_id=test_project_id,
        confirmation_id=confirmation.id,
        result_type="writing_draft",
        result_id=str(draft.id),
        status="adopted",
    )
    service = WritingChapterOrderService()
    preview = await service.preview(
        db_session,
        test_project_id,
        ChapterOrderPreviewRequest(chapter_indices=[3, 1, 2]),
    )

    async def reject_invalidation(_db, *, novel_id: str) -> None:
        assert novel_id == test_project_id
        raise RuntimeError("standing authorization port failed")

    with container_scope(
        {
            "story.chapter_order": StoryChapterOrderService(),
            "story.invalidate_world_progression_for_reorder": reject_invalidation,
        }
    ):
        with pytest.raises(RuntimeError, match="standing authorization port failed"):
            async with db_session.begin_nested():
                await service.confirm(
                    db_session,
                    test_project_id,
                    str(preview.receipt_id),
                    expected_preview_hash=preview.preview_hash,
                    confirmed=True,
                )

    await db_session.refresh(seeded["drafts"][0])
    await db_session.refresh(seeded["scene"])
    assert seeded["drafts"][0].chapter_index == 1
    assert seeded["scene"].chapter_ids == ["1"]
    assert (
        await db_session.scalar(
            select(StoryChapterOrderReceipt).where(
                StoryChapterOrderReceipt.novel_id == uuid.UUID(test_project_id)
            )
        )
        is None
    )
    operation = await db_session.get(WritingChapterOrderOperation, preview.receipt_id)
    assert operation is not None and operation.status == "previewed"
    await db_session.refresh(check)
    assert check.chapter_index == 1
    stored = await require_confirmation(
        db_session,
        novel_id=test_project_id,
        action="writing.generate",
        confirmation_id=confirmation.id,
    )
    assert stored.result_status == "adopted"
    assert stored.stale_reasons == []
    assert (
        await db_session.scalars(
            select(RagIndexState).where(
                RagIndexState.novel_id == uuid.UUID(test_project_id)
            )
        )
    ).all() == []
    assert (
        await db_session.scalars(
            select(AsyncTask).where(
                AsyncTask.novel_id == uuid.UUID(test_project_id),
                AsyncTask.task_type == "rag_index_chapter",
            )
        )
    ).all() == []
