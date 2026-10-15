"""Synthetic author decisions through real Scene/World ASGI and exact source reads."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evals.map_spatial import (
    MapSpatialEvalError,
    _as_plain,
    _read_private_json,
    _write_private_json,
    scene_source_refs,
)
from evals.map_spatial_guard import digest
from evals.tests.test_map_spatial import _fixture
from infrastructure.tasks.models import AsyncTask
from modules.world.map_structure_schemas import MapDocument, MapNodeCreate, MapSaveRequest
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity


async def _case_project(tmp_path, monkeypatch, async_client, db_session, test_project_id):
    """Five ordinary manual Scenes, one exact draft, and one adopted World map."""
    root, _matrix_path, _matrix = _fixture(tmp_path, monkeypatch)
    family_id = "map-xianxia-development-v1"
    segments = [f"北门是本场地点；合成场景第{index}段。" for index in range(1, 6)]
    content = "".join(segments)
    draft_response = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": test_project_id,
            "chapter_index": 1,
            "title": "合成北门正文",
            "content": content,
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()["draft"]

    cases = {}
    choices = []
    offset = 0
    for index, segment in enumerate(segments, 1):
        case_id = f"{family_id}-p{index}"
        response = await async_client.post(
            f"/api/outline/scenes?novel_id={test_project_id}",
            json={
                "scene_index": index - 1,
                "title": f"合成场景{index}",
                "source": "manual",
                "chapter_ids": ["1"],
                "scene_chunks": [
                    {
                        "chapter_index": 1,
                        "start_offset": offset,
                        "end_offset": offset + len(segment),
                        "source_draft_id": draft["id"],
                        "source_content_hash": draft["content_hash"],
                    }
                ],
                "structure_meta": {"existing_marker": index},
                "status": "canonical",
            },
        )
        assert response.status_code == 201, response.text
        scene = response.json()
        refs = await scene_source_refs(
            db_session, test_project_id, scene["id"], 1, segment
        )
        cases[case_id] = {
            "novel_id": test_project_id,
            "scene_id": scene["id"],
            "chapter_index": 1,
            "source_refs": refs,
            "source_snapshot_hash": digest(refs),
        }
        choices.append(
            {
                "case_id": case_id,
                "novel_id": test_project_id,
                "scene_id": scene["id"],
                "current_scene_hash": digest(scene),
                "source_refs": refs,
                "source_snapshot_hash": digest(refs),
                "reason": f"精确来源第{index}场明示北门为本场地点。",
            }
        )
        offset += len(segment)

    location = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="北门",
        status="canonical",
    )
    db_session.add(location)
    await db_session.flush()
    entity_response = await async_client.get(
        f"/api/world/entities/{location.id}?novel_id={test_project_id}"
    )
    assert entity_response.status_code == 200, entity_response.text
    maps = MapStructureService()
    node = await maps.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="北门地图", level="region", location_entity_id=location.id),
    )
    saved = await maps.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument(
                features=[
                    {
                        "id": "north-gate",
                        "kind": "location",
                        "label": "北门",
                        "entity_id": str(location.id),
                    }
                ]
            ),
        ),
    )
    # The draft API queues indexing; the synthetic completed-Evolution boundary
    # has no active model/index writer, so settle only those test-owned tasks.
    for task in (
        await db_session.scalars(
            select(AsyncTask).where(
                AsyncTask.novel_id == uuid.UUID(test_project_id),
                AsyncTask.task_type == "rag_index_chapter",
            )
        )
    ).all():
        task.status = "done"
    await db_session.flush()
    for choice in choices:
        current = await async_client.get(
            f"/api/outline/scenes/{choice['scene_id']}?novel_id={test_project_id}"
        )
        assert current.status_code == 200, current.text
        choice.update(
            current_scene_hash=digest(current.json()),
            location_entity_id=str(location.id),
            node_id=node["id"],
            revision_id=saved.id,
        )
    common = {
        "family_id": family_id,
        "split": "development",
        "novel_id": test_project_id,
        "case_bindings": cases,
    }
    operation_id = str(uuid.uuid4())
    _write_private_json(
        root / "evolution" / f"{family_id}.json",
        {
            "status": "completed",
            "operation_id": operation_id,
            "run_key": f"reading-{operation_id}",
        },
    )
    _write_private_json(
        root / "author-review" / f"{family_id}.json",
        {
            "status": "completed",
            "common_binding_sha256": digest(common),
            "operation_id": operation_id,
            "run_key": f"reading-{operation_id}",
            "map_candidate_reviews": [
                {
                    "node_id": node["id"],
                    "saved_revision_id": saved.id,
                    "status": "saved",
                    "action": "adopt",
                }
            ],
        },
    )
    return root, common, choices, location, node, saved


def _manifest(root, common, choices):
    value = {
        "schema_version": 1,
        "origin": "agent_simulated",
        "human_validated": False,
        "family_id": common["family_id"],
        "decisions": choices,
    }
    path = root / "author-scene-decisions.json"
    _write_private_json(path, value)
    return path, digest(value)


def _bind(monkeypatch, helper, root, common, async_client, db_session):
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")

    async def no_model(*_args, **_kwargs):
        pytest.fail("作者地点决定不应调用模型")

    monkeypatch.setattr("infrastructure.llm.client.LLMClient.generate", no_model)
    monkeypatch.setattr(helper, "read_common_binding", lambda *_: common)
    monkeypatch.setattr(helper, "require_calibration", lambda *_: None)

    async def verify(*_args):
        return None

    monkeypatch.setattr(helper, "verify_runtime", verify)

    @asynccontextmanager
    async def session():
        async with AsyncSession(
            bind=db_session.bind,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as read_session:
            yield read_session

    monkeypatch.setattr(
        "core.database.get_manager", lambda: SimpleNamespace(session=session)
    )

    @asynccontextmanager
    async def client(*_args):
        class ProductClient:
            async def request(self, method, path, **kwargs):
                if method == "GET" and path.startswith("/api/evolution/reading?"):
                    return httpx.Response(
                        200,
                        json={
                            "run": {
                                "run_key": f"reading-{operation_id}",
                                "status": "completed",
                                "completed_scenes": 5,
                                "total_scenes": 5,
                                "preparing_structure": False,
                            }
                        },
                    )
                return await async_client.request(method, path, **kwargs)

        from evals.map_spatial_control import _evolution_record_path

        operation_id = _read_private_json(
            _evolution_record_path(root, common["family_id"])
        )["operation_id"]
        yield ProductClient()

    from evals import map_spatial_control

    # The product transport is in-process SQLite; live runs still keep the PG gate.
    monkeypatch.setattr(map_spatial_control, "_validate_live_api_target", lambda *_: None)
    monkeypatch.setattr(map_spatial_control, "_product_client", client)


@pytest.mark.asyncio
async def test_explicit_location_preserves_scene_meta_and_exact_sources(
    tmp_path, monkeypatch, async_client, db_session, test_project_id
):
    from evals import map_spatial_scene_locations as helper
    from modules.story.facade import get_scene_contract

    root, common, choices, _location, node, saved = await _case_project(
        tmp_path, monkeypatch, async_client, db_session, test_project_id
    )
    _bind(monkeypatch, helper, root, common, async_client, db_session)
    path, sha = _manifest(root, common, choices)
    result = await helper.apply_scene_locations(
        private_root=root,
        family_id=common["family_id"],
        decisions=path,
        manifest_sha256=sha,
        execute=True,
    )
    assert result["status"] == "completed"
    assert result["patch_attempt_count"] == 5
    assert result["model_requests"] == 0
    assert result["atomic_cas"] is False
    record = _read_private_json(helper.ledger_path(root, common["family_id"]))
    assert record["status"] == "completed"
    assert len(record["cases"]) == 5
    final_cases = deepcopy(common["case_bindings"])
    for index, choice in enumerate(choices, 1):
        scene = (
            await async_client.get(
                f"/api/outline/scenes/{choice['scene_id']}?novel_id={test_project_id}"
            )
        ).json()
        assert scene["structure_meta"] == {
            "existing_marker": index,
            "location_entity_id": choice["location_entity_id"],
        }
        refs = await scene_source_refs(
            db_session,
            test_project_id,
            choice["scene_id"],
            1,
            f"北门是本场地点；合成场景第{index}段。",
        )
        assert refs == common["case_bindings"][choice["case_id"]]["source_refs"]
        final_scene = _as_plain(
            await get_scene_contract(db_session, test_project_id, choice["scene_id"])
        )
        final_cases[choice["case_id"]].update(
            scene_hash=digest(final_scene),
            map_source_refs=[{"node_id": node["id"], "revision_id": saved.id}],
            map_snapshot_hash=record["cases"][choice["case_id"]]["brief_sha256"],
        )
    assert (
        helper.author_binding(root, common, final_cases)["condition"] == "author_assisted"
    )
    stale_cases = deepcopy(final_cases)
    stale_cases[choices[0]["case_id"]]["map_source_refs"] = []
    with pytest.raises(MapSpatialEvalError, match="地图node/head已漂移"):
        helper.author_binding(root, common, stale_cases)
    with pytest.raises(MapSpatialEvalError, match="不得覆盖|不得重发"):
        await helper.apply_scene_locations(
            private_root=root,
            family_id=common["family_id"],
            decisions=path,
            manifest_sha256=sha,
            execute=True,
        )
    original_manifest = _read_private_json(path)
    _write_private_json(path, {**original_manifest, "extra": True})
    with pytest.raises(MapSpatialEvalError, match="作者决定必须显式提供"):
        helper.author_binding(root, common, final_cases)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,expected",
    [
        ("foreign_entity", "作者设定API拒绝|canonical location"),
        ("candidate_entity", "canonical location"),
        ("wrong_same_name", "所选UUID不在实际地图head"),
        ("source_drift", "精确source不符"),
        ("scene_hash_drift", "current Scene hash已漂移"),
        ("existing_location", "Scene已有地点"),
    ],
)
async def test_invalid_decisions_never_replace_scene_location(
    tmp_path,
    monkeypatch,
    async_client,
    db_session,
    test_project_id,
    project_factory,
    change,
    expected,
):
    from evals import map_spatial_scene_locations as helper

    root, common, choices, location, _node, _saved = await _case_project(
        tmp_path, monkeypatch, async_client, db_session, test_project_id
    )
    _bind(monkeypatch, helper, root, common, async_client, db_session)
    first = choices[0]
    if change in {"foreign_entity", "candidate_entity", "wrong_same_name"}:
        foreign_novel_id = (
            await project_factory.create_project(title="另一本合成小说")
            if change == "foreign_entity"
            else uuid.UUID(test_project_id)
        )
        target = CoreEntity(
            novel_id=foreign_novel_id,
            entity_type="location",
            name=location.name,
            status="candidate" if change == "candidate_entity" else "canonical",
        )
        db_session.add(target)
        await db_session.flush()
        first["location_entity_id"] = str(target.id)
    elif change == "source_drift":
        first["source_refs"] = [{**first["source_refs"][0], "range_hash": "a" * 64}]
    elif change == "scene_hash_drift":
        first["current_scene_hash"] = "a" * 64
    elif change == "existing_location":
        response = await async_client.patch(
            f"/api/outline/scenes/{first['scene_id']}?novel_id={test_project_id}",
            json={
                "structure_meta": {
                    "existing_marker": 1,
                    "location_entity_id": str(location.id),
                }
            },
        )
        assert response.status_code == 200, response.text
        current = await async_client.get(
            f"/api/outline/scenes/{first['scene_id']}?novel_id={test_project_id}"
        )
        assert current.status_code == 200, current.text
        first["current_scene_hash"] = digest(current.json())
    path, sha = _manifest(root, common, choices)
    with pytest.raises(MapSpatialEvalError, match=expected):
        await helper.apply_scene_locations(
            private_root=root,
            family_id=common["family_id"],
            decisions=path,
            manifest_sha256=sha,
            execute=True,
        )
    scene = (
        await async_client.get(
            f"/api/outline/scenes/{first['scene_id']}?novel_id={test_project_id}"
        )
    ).json()
    assert scene["structure_meta"]["existing_marker"] == 1
    assert scene["structure_meta"].get("location_entity_id") == (
        str(location.id) if change == "existing_location" else None
    )
    if change == "source_drift":
        assert not helper.ledger_path(root, common["family_id"]).exists()
    else:
        record = _read_private_json(helper.ledger_path(root, common["family_id"]))
        assert record["status"] == "unknown"
        assert record["patch_attempt_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("brief_kind", ["empty", "same_node_wrong_location"])
async def test_unusable_brief_marks_unknown_and_never_retries_patch(
    tmp_path, monkeypatch, async_client, db_session, test_project_id, brief_kind
):
    from evals import map_spatial_scene_locations as helper

    root, common, choices, _location, _node, _saved = await _case_project(
        tmp_path, monkeypatch, async_client, db_session, test_project_id
    )
    _bind(monkeypatch, helper, root, common, async_client, db_session)
    path, sha = _manifest(root, common, choices)

    async def unusable_brief(*_args, **_kwargs):
        if brief_kind == "empty":
            return {"items": []}
        return {
            "items": [
                {
                    "node_id": choices[0]["node_id"],
                    "revision_id": choices[0]["revision_id"],
                    "content": json.dumps(
                        {
                            "当前地点": [
                                {
                                    "entity_id": str(uuid.uuid4()),
                                    "label": "北门",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        }

    monkeypatch.setattr("modules.world.facade.read_map_spatial_brief", unusable_brief)
    with pytest.raises(MapSpatialEvalError, match="未进入同node/head Brief当前地点"):
        await helper.apply_scene_locations(
            private_root=root,
            family_id=common["family_id"],
            decisions=path,
            manifest_sha256=sha,
            execute=True,
        )
    record = _read_private_json(helper.ledger_path(root, common["family_id"]))
    assert record["status"] == "unknown"
    assert record["patch_attempt_count"] == 1
    with pytest.raises(MapSpatialEvalError, match="不得覆盖|不得重发"):
        await helper.apply_scene_locations(
            private_root=root,
            family_id=common["family_id"],
            decisions=path,
            manifest_sha256=sha,
            execute=True,
        )
