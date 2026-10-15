"""Frozen author-simulated Writing roles and the omission control boundary."""

from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from dataclasses import asdict

import pytest
from sqlalchemy import select

from evals.map_spatial import (
    MapSpatialEvalError,
    _read_private_json,
    _write_private_json,
)
from evals.map_spatial_guard import digest
from evals.tests.test_map_spatial_guard import binding_fixture, completed_calibration


def _roles_file(root, family, source, *, omission_case_id):
    value = {
        "schema_version": 1,
        "origin": "agent_simulated",
        "human_validated": False,
        "family_id": family["family_id"],
        "source_sha256": family["source_sha256"],
        "cases": {
            case["case_id"]: {
                "role": "omission_control"
                if case["case_id"] == omission_case_id
                else "positive",
                "source_excerpt_sha256": hashlib.sha256(
                    case["source_excerpt"].encode("utf-8")
                ).hexdigest(),
                "reason": "冻结前明确声明对照场景"
                if case["case_id"] == omission_case_id
                else "冻结前明确声明有图场景",
            }
            for case in source["cases"]
        },
    }
    path = root / "writing-roles.json"
    _write_private_json(path, value)
    return path, value


def test_roles_freeze_to_exact_five_sources_and_reject_later_tamper(
    tmp_path, monkeypatch
):
    from evals.map_spatial_guard import (
        freeze_writing_roles,
        read_common_binding,
        read_writing_roles,
        writing_role,
    )

    root, binding, matrix = binding_fixture(tmp_path, monkeypatch)
    family = matrix["families"][0]
    source = _read_private_json(root / family["family_id"] / "source.json")
    common = read_common_binding(root, family["family_id"])
    omission_case_id = source["cases"][0]["case_id"]
    assert writing_role(common, omission_case_id) == "positive"
    path, manifest = _roles_file(root, family, source, omission_case_id=omission_case_id)
    malformed = deepcopy(manifest)
    del malformed["cases"][source["cases"][1]["case_id"]]
    _write_private_json(path, malformed)
    with pytest.raises(MapSpatialEvalError, match="全部五case"):
        freeze_writing_roles(root, family, source, common["case_bindings"], path)

    _write_private_json(path, manifest)
    frozen = freeze_writing_roles(root, family, source, common["case_bindings"], path)
    common["writing_roles"] = frozen
    _write_private_json(root / "common-bindings" / f"{family['family_id']}.json", common)
    checked = read_common_binding(root, family["family_id"])
    assert read_writing_roles(root, checked) == frozen
    assert writing_role(checked, omission_case_id) == "omission_control"
    assert all(
        writing_role(checked, case_id) == "positive"
        for case_id in checked["case_bindings"]
        if case_id != omission_case_id
    )
    forged = deepcopy(manifest)
    forged["cases"][omission_case_id]["reason"] = "事后改写"
    _write_private_json(path, forged)
    with pytest.raises(MapSpatialEvalError, match="漂移"):
        read_common_binding(root, family["family_id"])


@pytest.mark.parametrize(
    "scene,brief,role,expected",
    [
        ({"structure_meta": {}}, {"items": []}, "positive", "unavailable"),
        ({"structure_meta": {}}, {"items": []}, "omission_control", "available"),
        (
            {"structure_meta": {"location_entity_id": "known"}},
            {"items": []},
            "omission_control",
            "reject",
        ),
        (
            {"structure_meta": {}},
            {"items": [{"content": "移动对象最后位置"}]},
            "omission_control",
            "reject",
        ),
    ],
)
def test_omission_requires_actual_empty_brief_without_scene_location(
    scene, brief, role, expected
):
    from evals.map_spatial import writing_brief_eligibility

    if expected == "reject":
        with pytest.raises(MapSpatialEvalError, match="必须无Scene地点.*brief为空"):
            writing_brief_eligibility(scene, brief, role)
        return
    result = writing_brief_eligibility(scene, brief, role)
    assert result["status"] == expected
    assert result["writing_pair_status"] == "not_run"
    if role == "omission_control":
        assert result["reason"] == "predeclared_omission_control"


@pytest.mark.asyncio
async def test_final_binding_accepts_only_predeclared_empty_omission(
    tmp_path, monkeypatch
):
    from evals import map_spatial_control as control
    from evals.map_spatial import writing_brief_eligibility
    from evals.map_spatial_guard import (
        freeze_writing_roles,
        read_binding,
        read_common_binding,
    )

    root, binding, matrix = binding_fixture(tmp_path, monkeypatch)
    family = matrix["families"][0]
    family_id = family["family_id"]
    source = _read_private_json(root / family_id / "source.json")
    common = read_common_binding(root, family_id)
    omission_case_id = source["cases"][0]["case_id"]
    roles_path, _manifest = _roles_file(
        root, family, source, omission_case_id=omission_case_id
    )
    common["writing_roles"] = freeze_writing_roles(
        root, family, source, common["case_bindings"], roles_path
    )
    _write_private_json(root / "common-bindings" / f"{family_id}.json", common)
    completed_calibration(root, binding)
    (root / "bindings" / f"{family_id}.json").unlink()
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setattr(control, "_load_family_source", lambda *_a, **_k: source)
    monkeypatch.setattr(
        control,
        "_validated_setup",
        lambda *_a: (
            {"scopes_sha256": common["scopes_sha256"]},
            {
                key: {
                    field: case[field]
                    for field in ("novel_id", "scene_id", "chapter_index")
                }
                for key, case in common["case_bindings"].items()
            },
        ),
    )

    async def preflight(**kwargs):
        case_id = next(
            case_id
            for case_id, case in common["case_bindings"].items()
            if case["scene_id"] == kwargs["scene_id"]
        )
        omission = case_id == omission_case_id
        assert kwargs["writing_role"] == ("omission_control" if omission else "positive")
        case = deepcopy(binding["case_bindings"][case_id])
        return {
            **{
                key: value
                for key, value in binding.items()
                if key
                not in {
                    "case_bindings",
                    "common_binding_sha256",
                    "map_heads_sha256",
                }
            },
            **case,
            "map_revision_count": 0 if omission else 1,
            "map_source_refs": []
            if omission
            else [{"node_id": f"node-{case_id}", "revision_id": "head"}],
            "map_brief_eligibility": writing_brief_eligibility(
                {"structure_meta": {}},
                {"items": [] if omission else [{"content": "current place"}]},
                kwargs["writing_role"],
            ),
            **({"writing_role": "omission_control"} if omission else {}),
        }

    monkeypatch.setattr(control, "preflight_project", preflight)
    frozen = await control.freeze_binding(
        private_root=root,
        family_id=family_id,
        scopes=root / "scopes" / f"{family_id}.json",
        execute=True,
    )
    assert frozen["status"] == "frozen"
    actual = read_binding(root, family_id)
    assert actual["case_bindings"][omission_case_id]["map_revision_count"] == 0
    assert actual["case_bindings"][omission_case_id]["writing_role"] == "omission_control"
    assert actual["writing_roles"] == common["writing_roles"]
    assert actual["map_heads_sha256"] == digest(
        {
            case_id: {
                "map_snapshot_hash": case["map_snapshot_hash"],
                "map_revision_count": case["map_revision_count"],
            }
            for case_id, case in actual["case_bindings"].items()
        }
    )
    tampered = deepcopy(actual)
    tampered["case_bindings"][omission_case_id]["writing_role"] = "positive"
    _write_private_json(root / "bindings" / f"{family_id}.json", tampered)
    with pytest.raises(MapSpatialEvalError, match="共同来源已漂移"):
        read_binding(root, family_id)


@pytest.mark.asyncio
async def test_mixed_author_inputs_patch_four_scenes_and_leave_omission_unchanged(
    tmp_path, monkeypatch, async_client, db_session, test_project_id
):
    from evals import map_spatial_scene_locations as helper
    from evals.tests.test_map_spatial_scene_locations import (
        _bind,
        _case_project,
        _manifest,
    )

    root, common, choices, _location, node, saved = await _case_project(
        tmp_path, monkeypatch, async_client, db_session, test_project_id
    )
    omission = choices[-1]
    common["writing_roles"] = {
        "cases": {
            choice["case_id"]: {
                "role": "omission_control"
                if choice["case_id"] == omission["case_id"]
                else "positive"
            }
            for choice in choices
        }
    }
    review_path = root / "author-review" / f"{common['family_id']}.json"
    review = _read_private_json(review_path)
    review["common_binding_sha256"] = digest(common)
    _write_private_json(review_path, review)
    _bind(monkeypatch, helper, root, common, async_client, db_session)
    forbidden_path, forbidden_sha = _manifest(root, common, choices)
    with pytest.raises(MapSpatialEvalError, match="positive case"):
        await helper.apply_scene_locations(
            private_root=root,
            family_id=common["family_id"],
            decisions=forbidden_path,
            manifest_sha256=forbidden_sha,
            execute=True,
        )
    assert not helper.ledger_path(root, common["family_id"]).exists()
    path, sha = _manifest(root, common, choices[:-1])
    omitted_route = (
        f"/api/outline/scenes/{omission['scene_id']}?novel_id={test_project_id}"
    )
    before = (await async_client.get(omitted_route)).json()
    tasks_before = (
        await async_client.get(f"/api/tasks?novel_id={test_project_id}")
    ).json()["items"]
    result = await helper.apply_scene_locations(
        private_root=root,
        family_id=common["family_id"],
        decisions=path,
        manifest_sha256=sha,
        execute=True,
    )
    assert result["status"] == "completed"
    assert result["extra_author_decisions"] == result["patch_attempt_count"] == 4
    assert result["omission_control_count"] == 1
    assert (await async_client.get(omitted_route)).json() == before
    assert (await async_client.get(f"/api/tasks?novel_id={test_project_id}")).json()[
        "items"
    ] == tasks_before

    ledger = _read_private_json(helper.ledger_path(root, common["family_id"]))
    assert ledger["status"] == "completed"
    assert ledger["cases"][omission["case_id"]]["extra_author_decisions"] == 0
    assert ledger["cases"][omission["case_id"]]["before_scene_hash"] == digest(before)
    assert ledger["cases"][omission["case_id"]]["after_scene_hash"] == digest(before)
    final_cases = deepcopy(common["case_bindings"])
    for choice in choices:
        event = ledger["cases"][choice["case_id"]]
        final_cases[choice["case_id"]].update(
            scene_hash=event["scene_contract_hash"],
            map_snapshot_hash=event["brief_sha256"],
            map_source_refs=[]
            if choice["case_id"] == omission["case_id"]
            else [{"node_id": node["id"], "revision_id": saved.id}],
        )
    summary = helper.author_binding(root, common, final_cases)
    assert summary["extra_author_decisions"] == 4
    assert summary["omission_controls"][omission["case_id"]] == {
        "extra_author_decisions": 0,
        "original_card_hash": digest(before),
        "scene_hash": final_cases[omission["case_id"]]["scene_hash"],
    }


@pytest.mark.asyncio
async def test_source_only_omission_runs_both_real_writing_workers(tmp_path, monkeypatch):
    """A missing Scene location is an executable, source-pinned control arm."""
    from core.config import get_settings
    from infrastructure.tasks.models import AsyncTask
    from modules.evidence.compilation.models import ContextConfirmation
    from modules.evidence.facade import prepare_confirmed_ai_action
    from modules.story.outline_state.models import SceneSpan
    from modules.writing.facade import build_manuscript_range_ref
    from modules.writing.models import WritingDraft
    from modules.writing.tests.test_map_product_consumption import (
        _fake_writing_provider,
        _product,
        _seed_five_scenes,
    )
    from run_worker import _build_task_worker

    async with _product(tmp_path, monkeypatch, capabilities="") as (manager, client):
        novel_id, scenes = await _seed_five_scenes(manager)
        async with manager.session() as db:
            span = await db.scalar(
                select(SceneSpan).where(SceneSpan.scene_id == uuid.UUID(scenes[-1]))
            )
            source_ref = await build_manuscript_range_ref(
                db,
                novel_id,
                draft_id=str(span.source_draft_id),
                start_offset=span.start_offset,
                end_offset=span.end_offset,
                content_mode="canonical",
            )
        monkeypatch.setattr(
            "infrastructure.llm.providers.OpenAIProvider.generate",
            _fake_writing_provider,
        )
        observations = []
        for enabled in (False, True):
            monkeypatch.setenv(
                "MAP_SPATIAL_ENABLED_CAPABILITIES", "writing.generate" if enabled else ""
            )
            get_settings.cache_clear()
            confirmed = await client.post(
                "/api/evidence/compilation/confirm",
                json={
                    "novel_id": novel_id,
                    "action": "writing.generate",
                    "task": "续写第五场",
                    "scope": "scene",
                    "chapter_index": 1,
                    "scene_id": scenes[-1],
                    "content_mode": "canonical",
                    "context_mode": "canonical",
                    "pinned_refs": [
                        {"kind": "source_range", "source_ref": asdict(source_ref)}
                    ],
                },
            )
            assert confirmed.status_code == 201, confirmed.text
            async with manager.session() as db:
                row = await db.get(ContextConfirmation, uuid.UUID(confirmed.json()["id"]))
                assert row.compile_options["map_spatial_baseline"] == []
                rendered = await prepare_confirmed_ai_action(
                    db,
                    novel_id=novel_id,
                    action="writing.generate",
                    confirmation_id=confirmed.json()["id"],
                )
                assert "第五场：暮色。" in rendered.rendered_markdown
                core_hash = row.compile_options["compiled_context_core_fingerprint"]
            submitted = await client.post(
                "/api/writing/generate",
                json={
                    "novel_id": novel_id,
                    "chapter_index": 1,
                    "context_confirmation_id": confirmed.json()["id"],
                },
            )
            assert submitted.status_code == 201, submitted.text
            task_id = uuid.UUID(submitted.json()["task_id"])
            task = await _build_task_worker().run_once(
                task_id=task_id, novel_id=uuid.UUID(novel_id)
            )
            assert task is not None and task.status == "done"
            observations.append((enabled, core_hash, task_id))
        assert observations[0][0] is False and observations[1][0] is True
        assert observations[0][1] == observations[1][1]
        assert observations[0][2] != observations[1][2]
        async with manager.session() as db:
            for _enabled, _core, task_id in observations:
                assert (await db.get(AsyncTask, task_id)).status == "done"
            candidates = (
                await db.scalars(
                    select(WritingDraft).where(
                        WritingDraft.novel_id == uuid.UUID(novel_id),
                        WritingDraft.status == "candidate",
                    )
                )
            ).all()
            assert len(candidates) == 2
            assert candidates[0].content == candidates[1].content
