"""Actual save/Scene entry points invalidate inputs, replays and map presence together."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.evidence.indexing.models import RagIndexState
from modules.evolution.commit import CommitConflictError
from modules.evolution.contracts import MentionRef
from modules.evolution.identity import candidates_from_world_results, resolve_mention
from modules.evolution.pipeline import exact_name_candidate_lookup
from modules.evolution.sampler import register_scene_sampler
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import handle_evolution_scene_step
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.services import MemoryService
from modules.story.facade import project_scene_presence
from modules.story.outline_state.models import Scene
from modules.story.outline_state.services import SceneService
from modules.world.models import CoreEntity
from modules.writing.facade import (
    create_draft_only,
    create_published_draft_only,
    create_published_drafts_only,
    get_latest_draft_for_chapter,
)
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftUpdate,
    WritingPublishRequest,
)
from modules.writing.services import WritingDraftService


class Sampler:
    def __init__(self):
        self.calls = 0

    async def sample(self, *, scene_text, input_manifest):
        self.calls += 1
        return {
            "observations": [
                {
                    "predicate": "林舟在旧城",
                    "modality": "event_observed",
                    "quote": scene_text,
                    "mentions": [{"surface": "林舟", "entity_type": "character"}],
                }
            ],
            "scene_events": [],
        }


async def setup_chain(db, nid):
    scenes = [
        Scene(
            novel_id=uuid.UUID(nid),
            scene_index=i,
            chapter_ids=[i + 1],
            scene_chunks=[],
            title=f"场景{i}",
            status="draft",
        )
        for i in range(2)
    ]
    db.add_all(scenes)
    await db.flush()
    ids = [str(scene.id) for scene in scenes]
    drafts = [
        await create_draft_only(db, nid, i + 1, f"第{i + 1}章", text)
        for i, text in enumerate(["林舟走进旧城。", "林舟继续前行。"])
    ]
    await db.commit()
    sampler = Sampler()
    register_scene_sampler("invalidation-test", lambda db, novel_id: sampler)
    task = SimpleNamespace(
        meta={
            "novel_id": nid,
            "run_key": "save-paths",
            "scene_index": 0,
            "scene_id": ids[0],
            "chapter_index": 1,
            "scene_text": drafts[0].content,
            "sampler_provider": "invalidation-test",
            "budget_total": 3,
        }
    )
    receipt = await handle_evolution_scene_step(db, task)
    # Valid historical derived and author facts are different authorities.
    for index, source in enumerate(["evolution", "author_confirmation"], 1):
        db.add(
            MemoryEvent(
                novel_id=uuid.UUID(nid),
                chapter_index=1,
                scene_id=uuid.UUID(ids[0]),
                scene_index=0,
                scene_sequence=index,
                sequence=1000 + index,
                dimension="locations",
                event_type="entity_moved",
                entity_id=uuid.uuid4(),
                source=source,
                snapshot_after={"text_state": "旧城"},
            )
        )
    await db.commit()
    return ids, drafts, sampler, receipt


@pytest.mark.parametrize("entry", ["api", "assistant", "collaboration", "import"])
async def test_all_writing_entry_points_fence_stale_prefix_and_replay(
    db_session, evolution_project_id, async_client, entry
):
    db, nid = db_session, evolution_project_id
    ids, drafts, sampler, receipt = await setup_chain(db, nid)
    replacement = "林舟走进新城。"  # same length
    context = AssistantOperationContext(
        str(uuid.uuid4()), str(current_account_id()), WorkContext(scope="project")
    )
    if entry == "api":
        response = await async_client.put(
            f"/api/writing/drafts/{drafts[0].id}",
            params={"novel_id": nid},
            json={"content": replacement},
        )
        assert response.status_code == 200, response.text
    elif entry == "assistant":
        from modules.writing.assistant_tools import OPERATIONS, ReviseChapter

        args = ReviseChapter(
            draft_id=drafts[0].id,
            source_hash=drafts[0].content_hash,
            replacements=[
                {
                    "start": 0,
                    "end": len(drafts[0].content),
                    "original": drafts[0].content,
                    "replacement": replacement,
                }
            ],
        )
        operation = OPERATIONS["writing.revise"]
        preview = await operation.prepare(db, nid, args, context=context)
        await operation.apply(db, nid, args, preview, context=context)
    elif entry == "collaboration":
        from modules.writing.creative import PORT

        baseline = await PORT.read(db, nid, SimpleNamespace(id=drafts[0].id))
        prepared = await PORT.validate(
            db,
            nid,
            baseline,
            SimpleNamespace(
                operation="replace",
                value={"title": drafts[0].title, "content": replacement},
            ),
            context=context,
        )
        await PORT.apply(db, nid, prepared, context=context)
    else:
        await create_published_drafts_only(
            db, nid, [{"chapter_index": 1, "title": "修订", "content": replacement}]
        )

    store = PostgresAttemptStore(db, nid)
    run = await store.load_run("save-paths")
    assert run.status == "source_stale" and run.owner_epoch == 2
    assert run.invalidation_json["recompute_required"]
    assert (await store.load_head_receipt("save-paths")).attempt_id == receipt[
        "attempt_id"
    ]
    current = await get_latest_draft_for_chapter(db, nid, 1)
    index = await db.scalar(
        select(RagIndexState).where(
            RagIndexState.novel_id == uuid.UUID(nid),
            RagIndexState.chapter_index == 1,
            RagIndexState.content_mode == "working",
        )
    )
    assert index.requested_hash == current.content_hash and index.active_task_id
    events = list(
        (
            await db.scalars(
                select(MemoryEvent).where(MemoryEvent.novel_id == uuid.UUID(nid))
            )
        ).all()
    )
    assert len(events) == 2
    assert {event.source: event.source_stale for event in events} == {
        "evolution": True,
        "author_confirmation": False,
    }
    presence = await project_scene_presence(db, nid, through_scene_index=0)
    assert (
        len(presence.nodes) == 1
        and presence.nodes[0].presence_kind == "confirmed_in_scene"
    )
    state = await MemoryService().replay_state(db, nid, 1)
    assert len(state["character_locations"]) == 1
    with pytest.raises(CommitConflictError, match="source_changed"):
        await store.load_prior_observations("save-paths")
    with pytest.raises(CommitConflictError, match="source_changed"):
        await handle_evolution_scene_step(
            db,
            SimpleNamespace(
                meta={
                    "novel_id": nid,
                    "run_key": "save-paths",
                    "scene_index": 1,
                    "scene_id": ids[1],
                    "chapter_index": 2,
                    "scene_text": drafts[1].content,
                    "sampler_provider": "invalidation-test",
                    "budget_total": 3,
                }
            ),
        )
    assert sampler.calls == 1 and run.budget_remaining == 2


async def test_source_change_rollback_restores_text_and_invalidation(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    _, drafts, _, _ = await setup_chain(db, nid)
    await WritingDraftService().update_draft(
        db, drafts[0].id, WritingDraftUpdate(content="林舟走进新城。"), nid
    )
    await db.rollback()
    assert (await get_latest_draft_for_chapter(db, nid, 1)).content == drafts[0].content
    assert (await PostgresAttemptStore(db, nid).load_run("save-paths")).status == "active"
    assert len((await project_scene_presence(db, nid, through_scene_index=0)).nodes) == 2


async def test_candidate_does_not_invalidate_working_sources(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    _, _, _, _ = await setup_chain(db, nid)
    from modules.writing.repositories import WritingDraftRepository

    await WritingDraftRepository().create_with_status(
        db,
        WritingDraftCreate(novel_id=nid, chapter_index=1, content="未采用的另一种写法。"),
        status="candidate",
    )
    assert (await PostgresAttemptStore(db, nid).load_run("save-paths")).status == "active"


async def test_publish_back_to_published_base_invalidates_working_interpretation(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    base = await create_published_draft_only(db, nid, 1, "原稿", "林舟没有进城。")
    _, drafts, _, _ = await setup_chain(db, nid)
    result, published = await WritingDraftService().publish_draft_result(
        db,
        WritingPublishRequest(
            novel_id=nid,
            chapter_index=1,
            draft_id=drafts[0].id,
            title=base.title,
            content=base.content,
        ),
    )
    assert not published and result.id == base.id
    assert (await get_latest_draft_for_chapter(db, nid, 1)).id == base.id
    assert (
        await PostgresAttemptStore(db, nid).load_run("save-paths")
    ).status == "source_stale"
    assert len((await project_scene_presence(db, nid, through_scene_index=0)).nodes) == 1


async def test_scene_fusion_deprecation_fences_original_sources(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    ids, _, _, _ = await setup_chain(db, nid)
    # This repository boundary is shared by fusion/deprecation, including adopted drafts.
    from modules.story.outline_state.repositories import SceneRepository

    repo = SceneRepository()
    scene = await repo.get(db, uuid.UUID(ids[0]))
    await repo.deprecate_with_reference(
        db,
        [scene],
        reference_field="fusion_scene_id",
        reference_scene_id=uuid.UUID(ids[1]),
        clear_mapping=True,
    )
    assert (
        await PostgresAttemptStore(db, nid).load_run("save-paths")
    ).status == "source_stale"
    assert not (await project_scene_presence(db, nid, through_scene_index=0)).nodes
    author_history = await db.scalar(
        select(MemoryEvent).where(
            MemoryEvent.novel_id == uuid.UUID(nid),
            MemoryEvent.scene_id == uuid.UUID(ids[0]),
            MemoryEvent.source == "author_confirmation",
        )
    )
    assert author_history is not None and not author_history.source_stale


async def test_scene_reorder_invalidates_even_without_derived_events(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    ids, _, _, _ = await setup_chain(db, nid)
    await SceneService().reorder(db, nid, list(reversed(ids)))
    run = await PostgresAttemptStore(db, nid).load_run("save-paths")
    assert (
        run.status == "source_stale"
        and run.invalidation_json["reason"] == "scene_order_changed"
    )
    events = list(
        (
            await db.scalars(
                select(MemoryEvent).where(MemoryEvent.novel_id == uuid.UUID(nid))
            )
        ).all()
    )
    assert all(event.scene_index == 1 for event in events)
    assert len(events) == 2 and sum(event.source_stale for event in events) == 1


async def test_precise_scene_range_rejects_text_from_later_scene(
    db_session, evolution_project_id
):
    db, nid = db_session, evolution_project_id
    scene = Scene(
        novel_id=uuid.UUID(nid),
        scene_index=0,
        chapter_ids=[1],
        title="前场",
        scene_chunks=[{"chapter_index": 1, "start_pos": 0, "end_pos": 3}],
        status="draft",
    )
    db.add(scene)
    await db.flush()
    sid = str(scene.id)
    await create_draft_only(db, nid, 1, "一章", "前文。后文。")
    await db.commit()
    sampler = Sampler()
    register_scene_sampler("boundary-test", lambda db, novel_id: sampler)
    with pytest.raises(CommitConflictError, match="source_changed"):
        await handle_evolution_scene_step(
            db,
            SimpleNamespace(
                meta={
                    "novel_id": nid,
                    "run_key": "boundary",
                    "scene_index": 0,
                    "scene_id": sid,
                    "chapter_index": 1,
                    "scene_text": "后文。",
                    "start_offset": 3,
                    "end_offset": 6,
                    "sampler_provider": "boundary-test",
                }
            ),
        )
    assert sampler.calls == 0


async def test_exact_identity_lookup_keeps_competing_names_without_unbounded_aliases(
    db_session, evolution_project_id, project_factory
):
    db, nid = db_session, evolution_project_id
    other = await project_factory.create_project()
    rows = [
        CoreEntity(
            novel_id=uuid.UUID(nid),
            name="林舟",
            entity_type="character",
            status="canonical",
        ),
        CoreEntity(
            novel_id=uuid.UUID(nid),
            name="另一个人",
            entity_type="character",
            status="canonical",
            content_json={"aliases": [{"alias": "林舟", "status": "active"}]},
        ),
        CoreEntity(
            novel_id=uuid.UUID(nid),
            name="林舟",
            entity_type="location",
            status="canonical",
        ),
        CoreEntity(
            novel_id=uuid.UUID(nid),
            name="退役称呼",
            entity_type="character",
            status="canonical",
            content_json={"aliases": [{"alias": "林舟", "status": "deprecated"}]},
        ),
        CoreEntity(
            novel_id=other, name="林舟", entity_type="character", status="canonical"
        ),
    ]
    # A literal duplicate remains ambiguous, but an alias with no learned-position
    # proof must not reveal a later identity in an earlier Scene.
    rows.append(
        CoreEntity(
            novel_id=uuid.UUID(nid),
            name="林舟",
            entity_type="character",
            status="canonical",
        )
    )
    db.add_all(rows)
    await db.flush()
    candidates = candidates_from_world_results(
        await exact_name_candidate_lookup(db)(nid, "林舟", "character")
    )
    assert {candidate.entity_id for candidate in candidates} == {
        str(rows[0].id),
        str(rows[-1].id),
    }
    resolution = resolve_mention(
        MentionRef(
            mention_id="m1",
            surface="林舟",
            entity_type="character",
            unresolved_reason="new",
        ),
        candidates,
    )
    assert resolution.outcome == "ambiguous" and resolution.resolved_entity_id is None
