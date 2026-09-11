"""Resolution decisions and undo against independently committed author edits."""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.project.models import Project
from modules.world.facade import (
    apply_review_resolution_decision,
    list_review_resolution_candidates,
    prepare_review_resolution_decision,
    rollback_focused_world_package,
)
from modules.world.models import CoreEntity
from modules.world.tests.test_focused_completion import setup_run
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e


async def test_resolution_decision_does_not_overwrite_concurrent_alias_edit():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Review resolution CAS"))
            await db.flush()
            entity, task, _, _ = await setup_run(db, str(novel_id))
            entity.created_by = "ai_import"
            entity.content_json = {
                "aliases": [
                    {
                        "alias": "北港",
                        "kind": "name",
                        "type": "name",
                        "status": "candidate",
                    }
                ]
            }
            await db.flush()
            rows = await list_review_resolution_candidates(db, str(novel_id))
            package = await prepare_review_resolution_decision(
                db, novel_id=str(novel_id), task_id=str(task.id), rows=rows
            )
            entity_id = entity.id
        async with sessions() as worker:
            await worker.get(CoreEntity, entity_id)
            await worker.commit()
            async with sessions.begin() as author:
                entity = await author.get(CoreEntity, entity_id)
                entity.created_by = "ai_import"
                entity.content_json = {
                    "aliases": [
                        {
                            "alias": "北港",
                            "kind": "identity",
                            "type": "秘密身份",
                            "status": "candidate",
                        }
                    ]
                }
            with pytest.raises(ConflictError):
                await apply_review_resolution_decision(
                    worker, novel_id=str(novel_id), package=package
                )
            await worker.rollback()
        async with sessions() as db:
            entity = await db.get(CoreEntity, entity_id)
            assert entity.content_json["aliases"][0]["kind"] == "identity"
            assert entity.content_json["aliases"][0]["status"] == "candidate"
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.novel_id == novel_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_resolution_undo_preserves_later_author_content():
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Review resolution undo"))
            await db.flush()
            entity, task, _, _ = await setup_run(db, str(novel_id))
            entity.created_by = "ai_import"
            entity.content_json = {
                "aliases": [
                    {
                        "alias": "北港",
                        "kind": "name",
                        "type": "name",
                        "status": "candidate",
                    }
                ]
            }
            await db.flush()
            rows = await list_review_resolution_candidates(db, str(novel_id))
            package = await prepare_review_resolution_decision(
                db, novel_id=str(novel_id), task_id=str(task.id), rows=rows
            )
            await apply_review_resolution_decision(
                db, novel_id=str(novel_id), package=package
            )
            entity_id = entity.id
        async with sessions.begin() as author:
            entity = await author.get(CoreEntity, entity_id)
            entity.created_by = "ai_import"
            entity.content_json = {**entity.content_json, "author_note": "作者后续修订"}
        async with sessions.begin() as db:
            result = await rollback_focused_world_package(
                db, novel_id=str(novel_id), suggestion_id=package["suggestion_id"]
            )
            assert result["results"][0]["status"] == "conflict"
            entity = await db.get(CoreEntity, entity_id)
            assert entity.content_json["author_note"] == "作者后续修订"
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.novel_id == novel_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_scene_group_undo_is_atomic_after_committed_author_edit():
    import hashlib
    from dataclasses import asdict

    from modules.story.outline_state.models import Scene
    from modules.story.outline_state.scene_resolution import (
        SceneBoundaryJudgment,
        apply_group,
        group_scene_inputs,
        preview,
        rollback,
    )
    from modules.writing.facade import build_manuscript_range_ref
    from modules.writing.models import WritingDraft

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Scene group undo"))
            await db.flush()
            text = "甲开门。乙读信。"
            draft = WritingDraft(
                novel_id=novel_id,
                chapter_index=1,
                content=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                status="published",
            )
            scenes = [
                Scene(
                    novel_id=novel_id,
                    scene_index=i,
                    title=str(i),
                    source="deep_import",
                    status="draft",
                    chapter_ids=["1"],
                    scene_chunks=[],
                    structure_meta={},
                )
                for i in range(2)
            ]
            db.add_all([draft, *scenes])
            await db.flush()
            group = group_scene_inputs(await preview(db, str(novel_id), 1, 1))[0]
            ref = await build_manuscript_range_ref(
                db,
                str(novel_id),
                draft_id=str(draft.id),
                start_offset=0,
                end_offset=len(text),
                content_mode="working",
            )
            judgments = [
                SceneBoundaryJudgment(
                    scene_id=str(scene.id),
                    verdict="adjust",
                    confidence=0.99,
                    explanation="补定位",
                    anchors=[
                        {
                            "evidence_key": "source",
                            "start_anchor": quote,
                            "end_anchor": quote,
                        }
                    ],
                )
                for scene, quote in zip(scenes, ("甲开门。", "乙读信。"), strict=True)
            ]
            receipt = await apply_group(
                db,
                novel_id=str(novel_id),
                frozen=group,
                judgments=judgments,
                evidence=[{"key": "source", "text": text, "source_ref": asdict(ref)}],
                workflow_id="test",
            )
            ids = [scene.id for scene in scenes]
        async with sessions.begin() as author:
            scene = await author.get(Scene, ids[0])
            scene.structure_meta = {**scene.structure_meta, "user_edited": True}
        async with sessions.begin() as db:
            assert (
                await rollback(db, novel_id=str(novel_id), receipt=receipt) == "conflict"
            )
            current = [await db.get(Scene, scene_id) for scene_id in ids]
            assert all(scene.scene_chunks for scene in current)
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(AsyncTask).where(AsyncTask.novel_id == novel_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
