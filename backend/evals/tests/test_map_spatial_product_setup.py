"""SQLite product-API behavior for the synthetic map evaluation setup."""

from __future__ import annotations

import pytest

from evals.map_spatial import ALLOWED_GENRES
from evals.map_spatial_control import _setup_family_via_client, _validated_setup
from evals.tests.test_map_spatial import _fixture


@pytest.mark.asyncio
async def test_setup_family_uses_real_project_draft_and_scene_apis(
    tmp_path, monkeypatch, async_client, db_session, account_llm_connection
):
    import uuid

    from sqlalchemy import func, select

    from infrastructure.tasks.models import AsyncTask

    async def no_model(*args, **kwargs):
        pytest.fail("setup and readonly preview must never call a model")

    monkeypatch.setattr("infrastructure.llm.client.LLMClient.generate", no_model)
    root, _, matrix = _fixture(tmp_path, monkeypatch)
    family = next(
        row
        for row in matrix["families"]
        if row["genre"] == ALLOWED_GENRES[0] and row["split"] == "development"
    )
    source = {
        "family_id": family["family_id"],
        "genre": family["genre"],
        "split": "development",
        "project_setup": {"chapter_index": 1},
        "cases": [
            {
                "case_id": f"{family['family_id']}-p{index}",
                "source_excerpt": f"合成地图来源片段 {index}：门外有一座钟楼。",
            }
            for index in range(1, 6)
        ],
    }
    monkeypatch.setattr(
        "evals.map_spatial_control._load_family_source",
        lambda *_args, **_kwargs: source,
    )

    result = await _setup_family_via_client(
        private_root=root,
        family_id=family["family_id"],
        client=async_client,
    )

    assert result["status"] == "completed"
    setup, scopes = _validated_setup(root, family, source)
    assert setup["project_id"] == result["novel_id"]
    assert setup["engine_switch"] == {
        "engine": "evolution",
        "epoch": 2,
        "schema_floor": 2,
        "stopped_imports": 0,
        "stopped_evolution_runs": 0,
        "cancelled_tasks": 0,
    }
    assert len(setup["scenes"]) == 5
    assert len({scope["scene_id"] for scope in scopes.values()}) == 5
    from evals.map_spatial import scene_source_refs

    for case in source["cases"]:
        scope = scopes[case["case_id"]]
        refs = await scene_source_refs(
            db_session,
            scope["novel_id"],
            scope["scene_id"],
            scope["chapter_index"],
            case["source_excerpt"],
        )
        assert len(refs) == 1
        assert refs[0]["content_mode"] == "canonical"
        assert refs[0]["start_offset"] < refs[0]["end_offset"]
        assert refs[0]["source_hash"] == setup["scenes"][case["case_id"]]["source_hash"]

    status = await async_client.get(
        f"/api/evolution/reading?novel_id={result['novel_id']}"
    )
    assert status.status_code == 200
    assert status.json()["engine"] == {
        "engine": "evolution",
        "epoch": 2,
        "schema_floor": 2,
    }
    assert status.json()["run"] is None
    task_count = await db_session.scalar(select(func.count()).select_from(AsyncTask))
    preview = await async_client.post(
        f"/api/evolution/reading/preview?novel_id={result['novel_id']}",
        json={
            "operation_id": str(uuid.uuid4()),
            "end_chapter": 1,
            "request_limit": 100,
            "budget_mode": "bounded",
            "discover_spatial": True,
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["scene_count"] == 5
    assert preview.json()["spatial_discovery_enabled"] is True
    assert (
        await db_session.scalar(select(func.count()).select_from(AsyncTask)) == task_count
    )
    assert not await db_session.scalar(
        select(AsyncTask.id).where(AsyncTask.status != "pending")
    )


@pytest.mark.asyncio
async def test_normal_engine_switch_preserves_existing_source_and_llm_snapshot(
    async_client, db_session, test_project_id, account_llm_connection, monkeypatch
):
    import uuid

    from evals.map_spatial import scene_source_refs
    from modules.project.facade import build_project_llm_execution_snapshot

    async def no_model(*args, **kwargs):
        pytest.fail("engine switch and readonly previews must never call a model")

    monkeypatch.setattr("infrastructure.llm.client.LLMClient.generate", no_model)
    content = "合成地图正文：钟楼位于城门外。"
    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": test_project_id,
            "chapter_index": 1,
            "title": "合成引擎切换来源",
            "content": content,
        },
    )
    assert published.status_code == 201, published.text
    draft = published.json()["draft"]
    created = await async_client.post(
        f"/api/outline/scenes?novel_id={test_project_id}",
        json={
            "scene_index": 0,
            "title": "引擎切换前的Scene",
            "source": "manual",
            "chapter_ids": ["1"],
            "scene_chunks": [
                {
                    "chapter_index": 1,
                    "start_offset": 0,
                    "end_offset": len(content),
                    "source_draft_id": draft["id"],
                    "source_content_hash": draft["content_hash"],
                }
            ],
            "status": "canonical",
        },
    )
    assert created.status_code == 201, created.text
    scene_id = created.json()["id"]
    refs_before = await scene_source_refs(
        db_session, test_project_id, scene_id, 1, content
    )
    snapshot_before = await build_project_llm_execution_snapshot(
        db_session, test_project_id
    )
    request = {"end_chapter": 1, "request_limit": 100, "discover_spatial": True}
    preview_path = f"/api/evolution/reading/preview?novel_id={test_project_id}"
    rejected = await async_client.post(
        preview_path, json={**request, "operation_id": str(uuid.uuid4())}
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"] == "understanding_owner_changed"
    status = await async_client.get(f"/api/evolution/reading?novel_id={test_project_id}")
    assert status.status_code == 200
    assert status.json()["run"] is None
    epoch = status.json()["engine"]["epoch"]
    switch = {
        "engine": "evolution",
        "expected_epoch": epoch,
        "stop_active": False,
        "authorization_confirmed": True,
    }
    switched = await async_client.post(
        f"/api/evolution/engine?novel_id={test_project_id}", json=switch
    )
    assert switched.status_code == 200, switched.text
    assert switched.json() == {
        "engine": "evolution",
        "epoch": epoch + 1,
        "schema_floor": 2,
        "stopped_imports": 0,
        "stopped_evolution_runs": 0,
        "cancelled_tasks": 0,
    }
    assert (
        await build_project_llm_execution_snapshot(db_session, test_project_id)
        == snapshot_before
    )
    assert (
        await scene_source_refs(db_session, test_project_id, scene_id, 1, content)
        == refs_before
    )
    admitted = await async_client.post(
        preview_path, json={**request, "operation_id": str(uuid.uuid4())}
    )
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["scene_count"] == 1
    stale = await async_client.post(
        f"/api/evolution/engine?novel_id={test_project_id}", json=switch
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_world_author_chain_uses_real_asgi_promote_source_cas_and_map_confirmation(
    async_client, db_session, test_project_id, project_factory, monkeypatch
):
    import uuid

    from sqlalchemy import select

    from infrastructure.tasks.models import AsyncTask
    from modules.world.map_atlas_models import MapAtlasNode
    from modules.world.tests.test_map_auto_draft_service import (
        _build_request,
        _stage_bound_clue,
    )

    async def no_model(*args, **kwargs):
        pytest.fail("deterministic World author chain must never call a model")

    monkeypatch.setattr("infrastructure.llm.client.LLMClient.generate", no_model)
    scene, first, second, clue = await _stage_bound_clue(
        db_session, test_project_id, entity_status="candidate"
    )
    base = f"/api/world/map-atlas/{test_project_id}"
    reviewed = await async_client.post(
        f"{base}/spatial-clues/{clue.id}/review",
        json={
            "action": "adopt",
            "expected_fingerprint": clue.fingerprint,
            "confirmed": True,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "adopted"
    built = await async_client.post(
        f"{base}/auto-drafts/build",
        json=_build_request(scene, clue).model_dump(mode="json"),
    )
    assert built.status_code == 202, built.text
    candidate = built.json()["revisions"][0]
    node_id, revision_id = candidate["node_id"], candidate["revision_id"]
    route = f"{base}/nodes/{node_id}/revisions/{revision_id}"
    preview = await async_client.post(
        f"{route}/review-preview", json={"action": "adopt", "base_revision_id": None}
    )
    assert preview.status_code == 200, preview.text
    locations = preview.json()["candidate_locations"]
    assert {row["entity_id"] for row in locations} == {str(first.id), str(second.id)}
    stale_location = next(row for row in locations if row["entity_id"] == str(first.id))
    first.summary = "并发编辑后的地点说明"
    await db_session.flush()
    stale = await async_client.post(
        stale_location["promotion_endpoint"],
        params={"novel_id": test_project_id},
        json={"expected_source_hash": stale_location["source_hash"]},
    )
    assert stale.status_code == 409
    other_project = await project_factory.create_project()
    cross_project = await async_client.post(
        stale_location["promotion_endpoint"],
        params={"novel_id": str(other_project)},
        json={"expected_source_hash": stale_location["source_hash"]},
    )
    assert cross_project.status_code == 404
    fresh = await async_client.post(
        f"{route}/review-preview", json={"action": "adopt", "base_revision_id": None}
    )
    for location in fresh.json()["candidate_locations"]:
        assert location["can_adopt"]
        promoted = await async_client.post(
            location["promotion_endpoint"],
            params={"novel_id": test_project_id},
            json={"expected_source_hash": location["source_hash"]},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["status"] == "canonical"
    node = await db_session.get(MapAtlasNode, uuid.UUID(node_id))
    await db_session.refresh(node)
    assert node.current_revision_id is None and node.status == "provisional"
    final = await async_client.post(
        f"{route}/review-preview", json={"action": "adopt", "base_revision_id": None}
    )
    assert final.status_code == 200, final.text
    assert final.json()["candidate_locations"] == []
    wrong_head = await async_client.post(
        f"{route}/review",
        json={
            "action": "adopt",
            "base_revision_id": str(uuid.uuid4()),
            "change_keys": final.json()["applied_change_keys"],
        },
    )
    assert wrong_head.status_code == 409
    saved = await async_client.post(
        f"{route}/review",
        json={
            "action": "adopt",
            "base_revision_id": None,
            "change_keys": final.json()["applied_change_keys"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "saved"
    await db_session.refresh(node)
    assert (
        node.status == "adopted" and str(node.current_revision_id) == saved.json()["id"]
    )
    tasks = (await db_session.scalars(select(AsyncTask))).all()
    assert all(task.status == "pending" for task in tasks)
    assert not any(
        task.task_type
        in {"writing_generate", "assistant_turn", "evolution_scene_step_v2"}
        for task in tasks
    )


@pytest.mark.asyncio
async def test_world_original_promote_rejects_missing_evolution_prefix(
    async_client, db_session, test_project_id
):
    from modules.world.tests.test_map_auto_draft_service import (
        _build_request,
        _stage_bound_clue,
    )

    scene, first, _, clue = await _stage_bound_clue(
        db_session, test_project_id, entity_status="candidate"
    )
    first.content_json = {"_meta": {"evolution_ref": {"run_key": "missing-attempt"}}}
    await db_session.flush()
    base = f"/api/world/map-atlas/{test_project_id}"
    built = await async_client.post(
        f"{base}/auto-drafts/build",
        json=_build_request(scene, clue).model_dump(mode="json"),
    )
    assert built.status_code == 202, built.text
    candidate = built.json()["revisions"][0]
    preview = await async_client.post(
        f"{base}/nodes/{candidate['node_id']}/revisions/{candidate['revision_id']}/review-preview",
        json={"action": "adopt", "base_revision_id": None},
    )
    assert preview.status_code == 200, preview.text
    location = next(
        row
        for row in preview.json()["candidate_locations"]
        if row["entity_id"] == str(first.id)
    )
    assert not location["can_adopt"] and "来源记录不完整" in location["block_reason"]
    denied = await async_client.post(
        location["promotion_endpoint"],
        params={"novel_id": test_project_id},
        json={"expected_source_hash": location["source_hash"]},
    )
    assert denied.status_code == 409
    await db_session.refresh(first)
    assert first.status == "candidate"
