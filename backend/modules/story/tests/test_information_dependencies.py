from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import select

from core.config import get_settings
from modules.assistant import proactive
from modules.assistant.models import AssistantWatch
from modules.assistant.schemas import ProactivePolicy
from modules.story.models import SceneScriptRevision
from modules.story.outline_state.foreshadowing_repository import (
    ForeshadowingPlanRepository,
)
from modules.story.outline_state.models import SceneChapterLink
from modules.story.proactive import _snapshot
from modules.story.service import StoryService
from modules.story.tests.test_story_service import _scene


@pytest.mark.asyncio
async def test_moving_information_plan_keeps_old_scene_and_new_scripts_detect_it(
    db_session, test_project_id, monkeypatch
):
    db, nid = db_session, test_project_id
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("core.config.get_settings", lambda: settings)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)
    scene = await _scene(db, nid)
    db.add(SceneChapterLink(novel_id=UUID(nid), scene_id=scene.id, chapter_index=1))
    await db.flush()
    repo = ForeshadowingPlanRepository()
    plan = await repo.create(db, UUID(nid), {"name": "来信", "planned_seed_chapter": 1})
    service = StoryService()
    script = await service.create_script_revision(
        db,
        novel_id=nid,
        scene_id=str(scene.id),
        file_key="opening",
        content="信放在桌上。",
        content_json=None,
        expected_revision_id=None,
        adopt=True,
    )
    assets = await service.get_scene_story_assets(
        db, novel_id=nid, scene_id=str(scene.id)
    )
    assert not assets["adopted_scripts"][0]["stale"]
    await proactive.save_policy(
        db, nid, ProactivePolicy(enabled=True, categories=["story"])
    )
    await repo.update(db, plan.id, {"planned_seed_chapter": 5})
    watch = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(nid))
    )
    change = watch.dirty_json[f"foreshadowing_plan:{plan.id}"]
    assert str(scene.id) in change["related_scene_ids"]
    material = await _snapshot(db, nid, change, [])
    assert material["scenes"][0]["scene_id"] == str(scene.id)
    assert material["scenes"][0]["stale_scripts"][0]["id"] == str(script.id)
    await repo.update(db, plan.id, {"planned_seed_chapter": 8})
    assert (
        str(scene.id)
        in watch.dirty_json[f"foreshadowing_plan:{plan.id}"]["related_scene_ids"]
    )
    assert not (await _snapshot(db, nid, change, [str(scene.id)]))["scenes"]


@pytest.mark.asyncio
async def test_old_script_baseline_is_not_invalidated_by_hash_protocol_upgrade(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    scene = await _scene(db, nid)
    service = StoryService()
    script = await service.create_script_revision(
        db,
        novel_id=nid,
        scene_id=str(scene.id),
        file_key="old",
        content="早期剧本",
        content_json=None,
        expected_revision_id=None,
        adopt=True,
    )
    legacy_hash = await service.get_scene_story_basis_hash(
        db,
        novel_id=nid,
        scene_id=str(scene.id),
        exclude_file_id=str(script.id),
        basis_version=1,
    )
    row = await db.get(SceneScriptRevision, script.current_revision_id)
    row.provenance_json = {
        **row.provenance_json,
        "basis_hash": legacy_hash,
        "basis_manifest": {"scene_id": str(scene.id)},
    }
    await db.flush()
    assets = await service.get_scene_story_assets(
        db, novel_id=nid, scene_id=str(scene.id)
    )
    assert not assets["adopted_scripts"][0]["stale"]


@pytest.mark.asyncio
async def test_open_thread_dependencies_and_old_range_survive_moving_the_thread(
    db_session, test_project_id, monkeypatch
):
    from modules.story.information_dependencies import script_information_basis
    from modules.story.outline_state.repositories import PlotThreadRepository
    from modules.story.outline_state.schemas import PlotThreadCreate, PlotThreadUpdate

    db, nid = db_session, test_project_id
    settings = replace(get_settings(), assistant_enabled=True)
    monkeypatch.setattr("core.config.get_settings", lambda: settings)
    monkeypatch.setattr(proactive, "get_settings", lambda: settings)
    scene = await _scene(db, nid)
    db.add(SceneChapterLink(novel_id=UUID(nid), scene_id=scene.id, chapter_index=1))
    await db.flush()
    repository = PlotThreadRepository()
    thread = await repository.create(
        db,
        UUID(nid),
        PlotThreadCreate(name="未完结的来信", thread_type="main", start_chapter=1),
    )
    plan = await ForeshadowingPlanRepository().create(
        db, UUID(nid), {"name": "尚未拆开的信", "related_thread_ids": [str(thread.id)]}
    )
    basis = await script_information_basis(db, UUID(nid), scene.id)
    assert {str(thread.id), str(plan.id)}.issubset({ref["id"] for ref in basis})
    service = StoryService()
    await service.create_script_revision(
        db,
        novel_id=nid,
        scene_id=str(scene.id),
        file_key="opening",
        content="等待来信。",
        content_json=None,
        expected_revision_id=None,
        adopt=True,
    )
    await proactive.save_policy(
        db, nid, ProactivePolicy(enabled=True, categories=["story"])
    )
    await repository.update(
        db, thread.id, PlotThreadUpdate(start_chapter=5, planned_payoff_chapter=7)
    )
    watch = await db.scalar(
        select(AssistantWatch).where(AssistantWatch.novel_id == UUID(nid))
    )
    change = watch.dirty_json[f"plot_thread:{thread.id}"]
    assert str(scene.id) in change["related_scene_ids"]
    assert (await _snapshot(db, nid, change, []))["scenes"][0]["stale_scripts"]
