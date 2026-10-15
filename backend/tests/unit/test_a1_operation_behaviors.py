from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.schemas import WorkContext
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextItem,
    ContextSection,
    Tier,
)
from modules.story.outline_state.schemas import SceneCreate, SceneUpdate
from modules.world.models import CoreEntity, EntityRevision
from modules.world.schemas import CoreEntityUpdate
from tests.utils import _create_project


async def _project(db_session) -> str:
    novel_id = uuid.uuid4()
    await _create_project(db_session, novel_id)
    return str(novel_id)


def _context(page: str = "world", **work_values) -> AssistantOperationContext:
    work_values.setdefault("scope", "project")
    return AssistantOperationContext(
        run_id="a1-operation-test",
        owner_id=str(BOOTSTRAP_ACCOUNT_ID),
        work=WorkContext(page=page, **work_values),
    )


@pytest.mark.asyncio
async def test_world_type_transition_revalidates_baseline_and_calls_domain_service(
    db_session,
):
    from modules.world.assistant_author_operations import (
        TransitionEntityType,
        _transition_apply,
        _transition_preview,
    )
    from modules.world.services.core.entity_service import WorldEntityService

    novel_id = await _project(db_session)
    assert (
        TransitionEntityType(entity_id=uuid.uuid4(), new_type=" Faction ").new_type
        == "faction"
    )
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="星门钥匙",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    args = TransitionEntityType(entity_id=entity.id, new_type="faction")
    context = _context()

    stale_preview = await _transition_preview(db_session, novel_id, args, context=context)
    await WorldEntityService().update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="作者刚补充的现状"),
        novel_id=novel_id,
    )
    with pytest.raises(ConflictError, match="重新准备"):
        await _transition_apply(
            db_session, novel_id, args, stale_preview, context=context
        )
    assert (
        await WorldEntityService().get(db_session, str(entity.id), novel_id=novel_id)
    ).entity_type == "item"

    fresh_preview = await _transition_preview(db_session, novel_id, args, context=context)
    result = await _transition_apply(
        db_session, novel_id, args, fresh_preview, context=context
    )
    current = await WorldEntityService().get(
        db_session, str(entity.id), novel_id=novel_id
    )
    assert current.entity_type == "faction"
    assert result["id"] == str(entity.id)

    other_novel_id = await _project(db_session)
    other_entity = CoreEntity(
        novel_id=uuid.UUID(other_novel_id),
        entity_type="item",
        name="跨作品钥匙",
        status="canonical",
    )
    db_session.add(other_entity)
    await db_session.flush()
    with pytest.raises(NotFoundError):
        await _transition_preview(
            db_session,
            novel_id,
            args.model_copy(update={"entity_id": other_entity.id}),
            context=context,
        )


@pytest.mark.asyncio
async def test_world_revision_note_and_restore_use_revision_services_and_cas(
    db_session,
):
    from modules.world.assistant_author_operations import (
        RestoreEntityRevision,
        SetRevisionNote,
        _restore_apply,
        _restore_preview,
        _revision_note_apply,
        _revision_note_preview,
    )
    from modules.world.services.core.entity_service import WorldEntityService
    from modules.world.services.revision_notes import (
        load_revision_notes,
        set_revision_note,
    )

    novel_id = await _project(db_session)
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="旧钥匙",
        summary="历史摘要",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    revision = EntityRevision(
        novel_id=uuid.UUID(novel_id),
        entity_id=entity.id,
        snapshot={
            "entity_type": "item",
            "name": "旧钥匙",
            "summary": "历史摘要",
            "public_info": None,
            "hidden_truth": None,
            "content_json": None,
            "importance": None,
            "importance_level": None,
            "reveal_level": None,
            "status": "canonical",
        },
        revision_reason="manual_update",
    )
    db_session.add(revision)
    await db_session.flush()
    context = _context()

    note_args = SetRevisionNote(
        target_kind="entity", revision_id=revision.id, note="修订来由"
    )
    note_preview = await _revision_note_preview(
        db_session, novel_id, note_args, context=context
    )
    await _revision_note_apply(
        db_session, novel_id, note_args, note_preview, context=context
    )
    assert await load_revision_notes(db_session, novel_id, "entity", [revision.id]) == {
        revision.id: "修订来由"
    }

    stale_note_preview = await _revision_note_preview(
        db_session, novel_id, note_args, context=context
    )
    await set_revision_note(db_session, novel_id, "entity", revision.id, "作者已改")
    with pytest.raises(ConflictError, match="重新准备"):
        await _revision_note_apply(
            db_session, novel_id, note_args, stale_note_preview, context=context
        )

    await WorldEntityService().update(
        db_session,
        str(entity.id),
        CoreEntityUpdate(summary="当前摘要"),
        novel_id=novel_id,
    )
    restore_args = RestoreEntityRevision(entity_id=entity.id, revision_id=revision.id)
    restore_preview = await _restore_preview(
        db_session, novel_id, restore_args, context=context
    )
    result = await _restore_apply(
        db_session, novel_id, restore_args, restore_preview, context=context
    )
    current = await WorldEntityService().get(
        db_session, str(entity.id), novel_id=novel_id
    )
    assert current.summary == "历史摘要"
    assert result["id"] == str(entity.id)


@pytest.mark.asyncio
async def test_world_fusion_requires_distinct_participants_and_preserves_domain_result(
    db_session,
):
    from modules.world.assistant_author_operations import (
        ApplyEntityFusion,
        FusionDecision,
        _fusion_apply,
        _fusion_preview,
    )

    novel_id = await _project(db_session)
    source = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="周明瑞",
        status="canonical",
    )
    target = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="克莱恩",
        status="canonical",
    )
    db_session.add_all([source, target])
    await db_session.flush()
    context = _context()
    args = ApplyEntityFusion(
        suggestions=[
            FusionDecision(
                action="alias_only",
                source_entity_id=source.id,
                target_entity_id=target.id,
                alias="周明瑞",
            )
        ]
    )
    preview = await _fusion_preview(db_session, novel_id, args, context=context)
    result = await _fusion_apply(db_session, novel_id, args, preview, context=context)
    assert result["applied"] == 1
    assert set(result["affected_entity_ids"]) == {str(source.id), str(target.id)}
    assert "warning_count" in result

    duplicate = ApplyEntityFusion(
        suggestions=[
            FusionDecision(
                action="alias_only",
                source_entity_id=source.id,
                target_entity_id=target.id,
            ),
            FusionDecision(
                action="merge",
                source_entity_id=target.id,
                target_entity_id=source.id,
            ),
        ]
    )
    with pytest.raises(ValidationError, match="只能出现在一条"):
        await _fusion_preview(db_session, novel_id, duplicate, context=context)


@pytest.mark.asyncio
async def test_story_scene_order_and_split_merge_call_workbench_with_stale_guard(
    db_session,
):
    from modules.story.assistant_scene_operations import (
        MergeScenes,
        ReorderScenes,
        SplitScene,
        _merge_apply,
        _merge_preview,
        _reorder_apply,
        _reorder_preview,
        _split_apply,
        _split_preview,
    )
    from modules.story.outline_state.services import SceneService

    novel_id = await _project(db_session)
    service = SceneService()
    first = await service.create(
        db_session,
        novel_id,
        SceneCreate(scene_index=0, title="入口", chapter_ids=["1"]),
    )
    second = await service.create(
        db_session,
        novel_id,
        SceneCreate(scene_index=1, title="密室", chapter_ids=["2", "3"]),
    )
    context = _context("outline")

    reorder = ReorderScenes(scene_ids=[uuid.UUID(second.id), uuid.UUID(first.id)])
    stale_preview = await _reorder_preview(db_session, novel_id, reorder, context=context)
    await service.update(
        db_session,
        first.id,
        SceneUpdate(goal="作者已修改目标"),
        novel_id=novel_id,
    )
    with pytest.raises(ConflictError, match="重新准备"):
        await _reorder_apply(
            db_session, novel_id, reorder, stale_preview, context=context
        )
    fresh_preview = await _reorder_preview(db_session, novel_id, reorder, context=context)
    await _reorder_apply(db_session, novel_id, reorder, fresh_preview, context=context)
    ordered = await service.get_ordered(db_session, novel_id)
    assert [item.id for item in ordered] == [second.id, first.id]

    split_args = SplitScene(source_scene_id=second.id, split_chapter_index=3)
    split_preview = await _split_preview(
        db_session, novel_id, split_args, context=context
    )
    assert split_preview == await _split_preview(
        db_session, novel_id, split_args, context=context
    )
    split_result = await _split_apply(
        db_session, novel_id, split_args, split_preview, context=context
    )
    assert split_result["new_scene_id"]
    merge_args = MergeScenes(
        target_scene_id=first.id,
        source_scene_ids=[uuid.UUID(split_result["new_scene_id"])],
    )
    merge_preview = await _merge_preview(
        db_session, novel_id, merge_args, context=context
    )
    merge_result = await _merge_apply(
        db_session, novel_id, merge_args, merge_preview, context=context
    )
    assert merge_result["id"] == first.id


@pytest.mark.asyncio
async def test_writing_rename_comment_status_and_conflict_report_are_version_bound(
    db_session,
):
    from modules.writing.assistant_a1_operations import (
        CheckChapterConflicts,
        DisposeComment,
        MarkEditorialReady,
        RenameChapter,
        _comment_apply,
        _comment_preview,
        _conflict_apply,
        _conflict_preview,
        _editorial_ready_apply,
        _editorial_ready_preview,
        _rename_apply,
        _rename_preview,
    )
    from modules.writing.comments import create_comment
    from modules.writing.repositories import WritingDraftRepository
    from modules.writing.schemas import WritingCommentCreate, WritingDraftCreate
    from modules.writing.services import WritingDraftService
    from modules.writing.source_hashing import hash_text

    novel_id = await _project(db_session)
    service = WritingDraftService()
    draft = await service.create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=1, title="旧标题", content="钟声响起。"
        ),
    )
    context = _context("writing")

    rename_args = RenameChapter(draft_id=draft.id, title="新标题")
    rename_preview = await _rename_preview(
        db_session, novel_id, rename_args, context=context
    )
    rename_result = await _rename_apply(
        db_session, novel_id, rename_args, rename_preview, context=context
    )
    renamed = await WritingDraftRepository().get(
        db_session, uuid.UUID(rename_result["id"])
    )
    assert renamed is not None and renamed.title == "新标题"
    assert renamed.content == "钟声响起。"

    comment_payload = WritingCommentCreate(
        novel_id=novel_id,
        source_hash=renamed.content_hash,
        start_offset=0,
        end_offset=2,
        excerpt="钟声",
        body="声音线索保持一致。",
    )
    comment = await create_comment(db_session, renamed.id, comment_payload)
    comment_args = DisposeComment(comment_id=comment["id"], status="resolved")
    comment_preview = await _comment_preview(
        db_session, novel_id, comment_args, context=context
    )
    comment_result = await _comment_apply(
        db_session, novel_id, comment_args, comment_preview, context=context
    )
    assert comment_result["status"] == "resolved"

    ready_args = MarkEditorialReady(
        draft_id=renamed.id, expected_content_hash=renamed.content_hash
    )
    ready_preview = await _editorial_ready_preview(
        db_session, novel_id, ready_args, context=context
    )
    await _editorial_ready_apply(
        db_session, novel_id, ready_args, ready_preview, context=context
    )
    ready_draft = await WritingDraftRepository().get(db_session, renamed.id)
    assert ready_draft.editorial_ready_hash == renamed.content_hash

    conflict_args = CheckChapterConflicts(
        draft_id=renamed.id,
        expected_content_hash=renamed.content_hash,
    )
    conflict_preview = await _conflict_preview(
        db_session, novel_id, conflict_args, context=context
    )
    conflict_result = await _conflict_apply(
        db_session, novel_id, conflict_args, conflict_preview, context=context
    )
    assert conflict_result["status"] in {"completed", "degraded"}
    assert conflict_result["item_count"] >= 0

    stale_args = CheckChapterConflicts(
        draft_id=renamed.id,
        expected_content_hash=hash_text("旧正文"),
    )
    with pytest.raises(ConflictError, match="新版本"):
        await _conflict_preview(db_session, novel_id, stale_args, context=context)


@pytest.mark.asyncio
async def test_evidence_reads_keep_author_cutoff_and_exact_source_ref(
    db_session,
):
    from modules.evidence.assistant_read_operations import (
        ReadSource,
        SearchProject,
        SourceRange,
        _read_source,
        _search,
    )
    from modules.writing.schemas import WritingDraftCreate
    from modules.writing.services import WritingDraftService
    from modules.writing.source_hashing import hash_text

    novel_id = await _project(db_session)
    draft = await WritingDraftService().create_draft_contract(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=2, title="第二章", content="青铜钟响。"
        ),
    )
    context = _context("writing")
    source = SourceRange(
        draft_id=str(draft.id),
        chapter_index=2,
        version_number=draft.version_number,
        content_mode="working",
        start_offset=0,
        end_offset=3,
        source_hash=draft.content_hash,
        range_hash=hash_text("青铜钟"),
    )
    read = await _read_source(
        db_session,
        novel_id,
        ReadSource(source_ref=source),
        context=context,
    )
    assert "青铜钟" in read["text"]

    search_args = SearchProject(query="青铜钟", scopes=["manuscript"])
    result = await _search(db_session, novel_id, search_args, context=context)
    assert result["coverage"] == "retrieval_only"
    with pytest.raises(ValueError, match="超出当前可见截止位置"):
        await _read_source(
            db_session,
            novel_id,
            ReadSource(source_ref=source),
            context=_context("writing", scope="current", chapter_index=1),
        )


@pytest.mark.asyncio
async def test_evidence_search_rejects_other_owner_and_interaction_projects(
    db_session,
):
    from modules.evidence.assistant_read_operations import SearchProject, _search
    from modules.project.models import Project

    novel_id = await _project(db_session)
    args = SearchProject(query="只读测试")
    with pytest.raises(NotFoundError, match="不可访问"):
        await _search(
            db_session,
            novel_id,
            args,
            context=AssistantOperationContext(
                run_id="a1-other-owner",
                owner_id=str(uuid.uuid4()),
                work=WorkContext(page="writing", scope="project"),
            ),
        )

    project = await db_session.get(Project, uuid.UUID(novel_id))
    assert project is not None
    project.project_kind = "interaction"
    await db_session.flush()
    with pytest.raises(NotFoundError, match="不可访问"):
        await _search(db_session, novel_id, args, context=_context("writing"))


def test_evidence_confirmation_source_read_requires_selected_and_non_omitted_range():
    from modules.evidence.assistant_read_operations import _confirmed_source_selected
    from modules.evidence.source_ref_contracts import SourceRangeRefContract

    source = SourceRangeRefContract(
        draft_id="draft-selected",
        chapter_index=2,
        version_number=3,
        content_mode="working",
        start_offset=2,
        end_offset=7,
        source_hash="a" * 64,
        range_hash="b" * 64,
    )
    source_payload = {
        "type": "rag",
        "id": "chunk-1",
        "source_ref": {
            "draft_id": source.draft_id,
            "chapter_index": source.chapter_index,
            "version_number": source.version_number,
            "content_mode": source.content_mode,
            "start_offset": source.start_offset,
            "end_offset": source.end_offset,
            "source_hash": source.source_hash,
            "range_hash": source.range_hash,
        },
    }
    item = ContextItem(
        key="selected-range",
        content="精确片段",
        source=source_payload,
        selection_state="author_pinned",
    )
    confirmed = SimpleNamespace(
        confirmation=SimpleNamespace(
            selected_asset_ids={"writing_drafts": [source.draft_id]},
            excluded_asset_ids={},
        ),
        compiled=CompiledContext(
            sections=[
                ContextSection(
                    key="retrieval_evidence_packs",
                    tier=Tier.P2,
                    content="精确片段",
                    items=[item],
                )
            ]
        ),
    )
    assert _confirmed_source_selected(confirmed, source)
    confirmed.confirmation.excluded_asset_ids["writing_drafts"] = [source.draft_id]
    assert not _confirmed_source_selected(confirmed, source)
    confirmed.confirmation.excluded_asset_ids = {}
    confirmed.compiled.omitted_items.append(
        item.model_copy(update={"selection_state": "omitted"})
    )
    assert not _confirmed_source_selected(confirmed, source)


@pytest.mark.asyncio
async def test_evolution_reading_operation_only_returns_its_own_authorization_preview(
    monkeypatch,
):
    from modules.evolution import assistant_tools, workflow

    calls = []

    async def preview(_db, novel_id, request):
        calls.append((novel_id, request.mode))
        return {"fingerprint": "c" * 64, "call_count": 2, "additional_budget": 2}

    monkeypatch.setattr(workflow, "preview_reading", preview)
    args = assistant_tools.PrepareReading(
        operation_id=uuid.uuid4(), mode="append", run_key="prior-run", end_chapter=4
    )
    prepared = await assistant_tools._reading_preview(None, "novel-a", args)
    result = await assistant_tools._reading_apply(None, "novel-a", args, prepared)
    assert calls == [("novel-a", "append"), ("novel-a", "append")]
    assert result["authorization_required"] is True
    assert result["authorization_preview"]["additional_budget"] == 2
    assert "task_id" not in result
