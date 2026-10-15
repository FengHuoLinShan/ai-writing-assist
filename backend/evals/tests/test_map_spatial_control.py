"""Driver safety and quality gates; synthetic products only, no real model IO."""

import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from evals import map_spatial
from evals import map_spatial_control as control
from evals.map_spatial import MapSpatialEvalError
from evals.map_spatial_guard import Metric, summarize_metric
from evals.tests.test_map_spatial_guard import URL, binding_fixture, completed_calibration


@pytest.mark.parametrize(
    "scene,brief,status,reason",
    [
        (
            {"source": "manual"},
            {"items": []},
            "unavailable",
            "scene_location_unavailable",
        ),
        (
            {"structure_meta": {"location_entity_id": "trusted"}},
            {"items": []},
            "unavailable",
            "no_usable_map_brief",
        ),
        ({}, {"items": [{}]}, "available", None),
    ],
)
def test_writing_eligibility_requires_actual_brief_items(scene, brief, status, reason):
    assert map_spatial.writing_brief_eligibility(scene, brief) == {
        "status": status,
        "reason": reason,
        "writing_pair_status": "not_run",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [30, 31, 50])
async def test_evolution_start_preserves_explicit_finite_headroom_without_topup(
    tmp_path, monkeypatch, limit
):
    import uuid

    import httpx

    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    family_id = binding["family_id"]
    common = control.read_common_binding(root, family_id)
    completed_calibration(root, binding)
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DATABASE_URL", URL)
    operation_id = str(uuid.uuid4())
    request = control._evolution_request(common, operation_id, limit)
    preview = {
        "spatial_discovery_enabled": True,
        "scene_count": 5,
        "end_chapter": request["end_chapter"],
        "request_limit": limit,
        "budget_mode": "bounded",
        "model": "gpt-6-luna",
        "fingerprint": "a" * 64,
        "mandatory_request_reserve": 21,
        "optional_steps": {
            "spatial": {
                "quota": 10,
                "per_scene_limit": 2,
                "used": 0,
                "remaining": 10,
                "request_range": {"minimum": 0, "maximum": 10},
            }
        },
    }
    facts = control._validate_evolution_preview(preview, request)
    for invalid_limit in (True, 0, 1001):
        with pytest.raises(MapSpatialEvalError, match="完整空间子额度"):
            control._validate_evolution_preview(
                {**preview, "request_limit": invalid_limit},
                {**request, "request_limit": invalid_limit},
            )
    control._write_private_json(
        control._evolution_preview_path(root, family_id, operation_id),
        {
            "suite": "map_spatial",
            "family_id": family_id,
            "split": "development",
            "operation_id": operation_id,
            "common_binding_sha256": control.digest(common),
            "request_sha256": control.digest(request),
            "request": request,
            "preview": facts,
            "preview_sha256": control.digest(preview),
            "status": "previewed",
            "human_validated": False,
        },
    )
    posts = []

    async def post(path, *, json):
        posts.append((path, json))
        if path.startswith("/api/evolution/reading/preview?"):
            assert json == request
            return httpx.Response(200, json=preview)
        assert json == {
            **request,
            "expected_fingerprint": preview["fingerprint"],
            "authorization_confirmed": True,
        }
        return httpx.Response(
            200,
            json={
                "run": {
                    "run_key": f"reading-{operation_id}",
                    "status": "pending",
                    "task_id": str(uuid.uuid4()),
                    "total_scenes": 5,
                    "spatial_discovery_enabled": True,
                }
            },
        )

    @asynccontextmanager
    async def client(*args):
        yield SimpleNamespace(post=post, timeout=SimpleNamespace(read=30))

    @asynccontextmanager
    async def session():
        yield None

    async def verify(*args):
        pass

    monkeypatch.setattr(control, "_product_client", client)
    monkeypatch.setattr(control, "verify_runtime", verify)
    monkeypatch.setattr(
        "core.database.get_manager", lambda: SimpleNamespace(session=session)
    )
    options = {
        "private_root": root,
        "family_id": family_id,
        "operation_id": operation_id,
        "api_base_url": "http://map-spatial-eval.internal",
        "execute": True,
    }
    if limit < 31:
        with pytest.raises(MapSpatialEvalError, match="不得重发"):
            await control.start_evolution(**options)
        assert posts == []
        assert not control._evolution_record_path(root, family_id).exists()
        return
    result = await control.start_evolution(**options)
    assert result["request_limit"] == limit
    assert result["extra_headroom"] == limit - 31
    assert result["completion_guaranteed"] is False
    assert result["total_call_upper_bound"] == 1 + 5 + 10 * 14 + 5 * 30 + limit
    assert result["total_call_upper_bound_with_connection_verification"] == 297 + limit
    saved = map_spatial._read_private_json(
        control._evolution_record_path(root, family_id)
    )
    assert saved["preview"] == facts
    with pytest.raises(MapSpatialEvalError, match="不得重发"):
        await control.start_evolution(**options)
    assert len(posts) == 2


@pytest.mark.parametrize(
    "name",
    [
        "pipeline.py",
        "tasks.py",
        "optional_scene.py",
        "world.py",
        "structure.py",
        "optional_step_budget.py",
    ],
)
def test_execution_protocol_changes_invalidate_pipeline_hash(monkeypatch, name):
    before = map_spatial.pipeline_hash()
    path = map_spatial.REPO_ROOT / "backend/modules/evolution" / name
    assert path.is_file()
    real_hash = map_spatial._sha256_file
    monkeypatch.setattr(
        map_spatial,
        "_sha256_file",
        lambda target: "0" * 64 if target == path else real_hash(target),
    )
    assert map_spatial.pipeline_hash() != before


@pytest.mark.parametrize(
    "reading",
    [
        {"engine": {"engine": "legacy", "epoch": 1}, "run": {"status": "active"}},
        {"engine": {"engine": "legacy", "epoch": True}, "run": None},
        {"engine": {"engine": "read_only", "epoch": 2}, "run": None},
    ],
)
@pytest.mark.asyncio
async def test_setup_rejects_unexpected_engine_without_switch_or_retry(
    tmp_path, monkeypatch, reading
):
    import httpx

    from evals.map_spatial import _read_private_json
    from evals.tests.test_map_spatial import _fixture

    root, _, matrix = _fixture(tmp_path, monkeypatch)
    family = matrix["families"][0]
    monkeypatch.setattr(
        control,
        "_load_family_source",
        lambda *_args, **_kwargs: {"project_setup": {"chapter_index": 1}},
    )
    seen = []

    def route(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path == "/api/projects":
            return httpx.Response(201, json={**json.loads(request.content), "id": "new"})
        if request.method == "GET" and request.url.path == "/api/evolution/reading":
            return httpx.Response(200, json=reading)
        pytest.fail("unexpected engine state must not trigger a switch or other mutation")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(route), base_url="http://test"
    ) as client:
        with pytest.raises(MapSpatialEvalError, match="不能停止已有流程"):
            await control._setup_family_via_client(
                private_root=root, family_id=family["family_id"], client=client
            )
        assert (
            _read_private_json(control._setup_record_path(root, family["family_id"]))[
                "status"
            ]
            == "unknown"
        )
        with pytest.raises(MapSpatialEvalError, match="不可重复创建项目"):
            await control._setup_family_via_client(
                private_root=root, family_id=family["family_id"], client=client
            )
    assert seen == [("POST", "/api/projects"), ("GET", "/api/evolution/reading")]


@pytest.mark.parametrize(
    "target", ["http://127.0.0.1:65303", "http://localhost:8000", "https://example.com"]
)
@pytest.mark.asyncio
async def test_wrong_api_target_is_rejected_before_any_write(
    tmp_path, monkeypatch, target
):
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")

    async def forbidden(*args, **kwargs):
        pytest.fail("wrong API endpoint must receive zero requests")

    monkeypatch.setattr(control, "_setup_family_via_client", forbidden)
    with pytest.raises(MapSpatialEvalError, match="同进程ASGI"):
        await control.setup_family(
            private_root=tmp_path, family_id="unused", api_base_url=target, execute=True
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_manager_mismatch_closes_client_before_transport(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")
    manager = SimpleNamespace(engine=SimpleNamespace(url=URL.replace("65204", "65205")))
    monkeypatch.setattr("core.database.get_manager", lambda: manager)
    with pytest.raises(MapSpatialEvalError, match="实际数据库"):
        async with control._product_client("http://map-spatial-eval.internal", 30):
            pytest.fail("wrong manager cannot create a product client")


@pytest.mark.asyncio
async def test_product_asgi_routes_skip_lifespan_and_network(monkeypatch):
    from app.main import app

    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setattr(
        "core.database.get_manager",
        lambda: SimpleNamespace(engine=SimpleNamespace(url=URL)),
    )

    @asynccontextmanager
    async def forbidden_lifespan(_app):
        pytest.fail("ASGI eval must not start embedding/background workers")
        yield

    monkeypatch.setattr(app.router, "lifespan_context", forbidden_lifespan)
    async with control._product_client("http://map-spatial-eval.internal", 30) as client:
        assert client.headers["X-Requested-With"] == "XMLHttpRequest"
        response = await client.get("/api/auth/config")
    assert response.status_code == 200
    assert response.json()["auth_mode"] == "local"


def test_fresh_process_initializes_composition_before_facades_without_io():
    code = """
import asyncio
from evals.map_spatial_control import explicit_execution, _product_client
explicit_execution(True)
from app.bootstrap import register_container_services
register_container_services(ignore_existing=True)
from core.database import get_manager
manager = get_manager()
def no_external_connection(*args, **kwargs):
    raise AssertionError("fresh composition must not connect to a database")
from sqlalchemy import event
event.listen(manager.engine.sync_engine, "do_connect", no_external_connection)
async def run():
    async with _product_client("http://map-spatial-eval.internal", 30) as client:
        response = await client.get("/api/auth/config")
        assert response.status_code == 200
    await manager.close()
asyncio.run(run())
print("composition-ready-no-model-or-database-io")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=map_spatial.REPO_ROOT / "backend",
        env={
            **os.environ,
            "DATABASE_URL": URL,
            "APP_ENV": "test",
            "AUTH_MODE": "local",
            "MAP_SPATIAL_EVAL_ALLOW_LIVE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "composition-ready-no-model-or-database-io" in result.stdout


@pytest.mark.asyncio
async def test_assistant_capability_covers_submit_worker_and_restores(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("MAP_SPATIAL_ENABLED_CAPABILITIES", "writing.generate")
    get_settings.cache_clear()
    seen = []

    async def body(**kwargs):
        for stage in ("normal-submit", "exact-worker"):
            assert "assistant.turn" in get_settings().map_spatial_enabled_capabilities
            seen.append(stage)
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(control, "_run_assistant_turn", body)
    with pytest.raises(RuntimeError):
        await control.run_assistant_turn()
    assert seen == ["normal-submit", "exact-worker"]
    assert get_settings().map_spatial_enabled_capabilities == ("writing.generate",)
    get_settings.cache_clear()


def metric(
    name="clue_precision", status="observed", numerator=1, denominator=1, without_map=None
):
    return Metric(
        group="cold_start",
        name=name,
        status=status,
        numerator=numerator,
        denominator=denominator,
        without_map=without_map,
        evidence_task_ids=["synthetic-task"],
        reason="synthetic opportunity",
    )


def test_quality_sums_opportunities_and_allows_case_with_none():
    summary = summarize_metric(
        "cold_start",
        "clue_precision",
        [
            metric(numerator=19, denominator=20),
            metric(status="not_applicable", numerator=0, denominator=0),
        ],
    )
    assert summary["passed"] is True
    assert (summary["numerator"], summary["denominator"], summary["value"]) == (
        19,
        20,
        0.95,
    )
    assert summary["applicable_case_count"] == 1
    for rows in (
        [metric(status="not_applicable", numerator=0, denominator=0)],
        [metric(status="unknown", numerator=None, denominator=None)],
        [None],
    ):
        assert summarize_metric("cold_start", "clue_precision", rows)["passed"] is False


def test_cost_unknown_does_not_invent_quality_threshold():
    summary = summarize_metric(
        "cold_start",
        "total_cost",
        [metric(name="total_cost", status="unknown", numerator=None, denominator=None)],
    )
    assert summary["status"] == "unknown" and summary["value"] is None
    assert summary["numerator"] is None and summary["denominator"] is None
    assert summary["threshold"] is None and summary["passed"] is None
    assert summary["required_for_gate"] is False


@pytest.mark.parametrize("fault", ["concurrency", "assistant", "writing_root_cap"])
def test_pilot_runtime_and_call_caps_fail_before_model_io(tmp_path, monkeypatch, fault):
    from core.config import get_settings

    _, binding, _ = binding_fixture(tmp_path, monkeypatch)
    snapshot = binding["project_snapshot"]
    if fault == "concurrency":
        monkeypatch.setenv(
            "LLM_MODEL_LIMITS_JSON", '{"subscription/codex/gpt-6-luna":{"concurrency":3}}'
        )
    elif fault == "assistant":
        monkeypatch.setenv("ASSISTANT_ENABLED", "false")
    get_settings.cache_clear()
    with pytest.raises(MapSpatialEvalError):
        if fault == "writing_root_cap":
            task = SimpleNamespace(
                task_type="writing_generate", meta={"included_sources_upper_bound": 65}
            )
            map_spatial.task_execution_budget(task, snapshot, 900)
        else:
            map_spatial.runtime_limits(snapshot)


def test_paired_baseline_weights_same_opportunities_and_requires_gain():
    rows = [
        metric(name="spatial_consistency", numerator=9, denominator=10, without_map=0.8),
        metric(name="spatial_consistency", numerator=1, denominator=1, without_map=1),
    ]
    summary = summarize_metric("writing_paired", "spatial_consistency", rows)
    assert summary["without_map"] == pytest.approx(9 / 11)
    assert summary["value"] == pytest.approx(10 / 11) and summary["passed"]
    rows[0].without_map = 0.9
    assert not summarize_metric("writing_paired", "spatial_consistency", rows)["passed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", [False, True])
async def test_final_freeze_keeps_distinct_scene_source_spans(
    tmp_path, monkeypatch, unavailable
):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    family_id = binding["family_id"]
    common = control.read_common_binding(root, family_id)
    completed_calibration(root, binding)
    (root / "bindings" / f"{family_id}.json").unlink()
    source = map_spatial._read_private_json(root / family_id / "source.json")
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
                for key, case in binding["case_bindings"].items()
            },
        ),
    )

    async def preflight(**kwargs):
        case = deepcopy(
            next(
                case
                for case in binding["case_bindings"].values()
                if case["scene_id"] == kwargs["scene_id"]
            )
        )
        return {
            **{
                key: value
                for key, value in binding.items()
                if key
                not in {"case_bindings", "common_binding_sha256", "map_heads_sha256"}
            },
            **case,
            "map_revision_count": 0 if unavailable else 1,
            "map_brief_eligibility": map_spatial.writing_brief_eligibility(
                {"source": "manual", "structure_meta": {}},
                {"items": [] if unavailable else [{}]},
            ),
        }

    monkeypatch.setattr(control, "preflight_project", preflight)
    result = await control.freeze_binding(
        private_root=root,
        family_id=family_id,
        scopes=root / "scopes" / f"{family_id}.json",
        execute=True,
    )
    if unavailable:
        from evals.map_spatial_guard import (
            binding_path,
            evaluate_development,
            read_writing_eligibility,
        )

        assert result["status"] == "not_run"
        assert not binding_path(root, family_id).exists()
        assert read_writing_eligibility(root, family_id) == result
        assert all(
            {key: case[key] for key in ("status", "reason", "writing_pair_status")}
            == {
                "status": "unavailable",
                "reason": "scene_location_unavailable",
                "writing_pair_status": "not_run",
            }
            for case in result["cases"].values()
        )
        with pytest.raises(MapSpatialEvalError, match="writing_pair_not_run"):
            first_id, first = next(iter(binding["case_bindings"].items()))
            await map_spatial.run_writing_pair(
                private_root=root,
                family_id=family_id,
                case_id=first_id,
                novel_id=first["novel_id"],
                scene_id=first["scene_id"],
                chapter_index=first["chapter_index"],
                execute=True,
            )
        with pytest.raises(MapSpatialEvalError, match="不能覆盖"):
            await control.freeze_binding(
                private_root=root,
                family_id=family_id,
                scopes=root / "scopes" / f"{family_id}.json",
                execute=True,
            )
        assert read_writing_eligibility(root, family_id) == result
        report_path = root / "report.json"
        map_spatial.build_report(root, report_path)
        report = map_spatial._read_private_json(report_path)
        assert report["writing_eligibility"][family_id] == result
        gate = evaluate_development(root, map_spatial.load_matrix())
        assert gate["passed"] is False
        assert any(
            row["reason"] == "writing_pair_not_run_map_brief_unavailable"
            for row in gate["blockers"]
        )
        assert not map_spatial._read_ledger(root)["runs"]
        return
    assert result["status"] == "frozen"
    frozen = control.read_binding(root, family_id)
    assert (
        len(
            {
                case["source_refs"][0]["start_offset"]
                for case in frozen["case_bindings"].values()
            }
        )
        == 5
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["done", "timeout", "attempted", "wrong_run", "wrong_operation", "sixth_scene"],
)
async def test_evolution_executes_only_new_exact_tasks_and_observes_final_stage(
    tmp_path, monkeypatch, outcome
):
    import uuid

    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    family_id = binding["family_id"]
    common = control.read_common_binding(root, family_id)
    completed_calibration(root, binding)
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setenv("APP_ENV", "test")
    operation_id = str(uuid.uuid4())
    ids = [str(uuid.uuid4()) for _ in range(6)]
    scene_ids = [item["scene_id"] for item in common["case_bindings"].values()]
    tasks = {
        task_id: SimpleNamespace(
            task_type="evolution_scene_step_v2",
            status="pending",
            attempt=1 if outcome == "attempted" else 0,
            result={},
            meta={
                "run_key": "synthetic-run",
                **(
                    {"operation": "structure"}
                    if index == 5
                    else {"scene_id": scene_ids[index], "scene_index": index}
                ),
            },
        )
        for index, task_id in enumerate(ids)
    }
    if outcome == "wrong_run":
        tasks[ids[0]].meta["run_key"] = "other-run"
    if outcome == "sixth_scene":
        tasks[ids[5]].meta = {
            "run_key": "synthetic-run",
            "scene_id": scene_ids[0],
            "scene_index": 5,
        }
    called = []

    async def scalar(query):
        return tasks[str(next(iter(query.compile().params.values())))]

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(scalar=scalar)

    async def verify(*args):
        pass

    async def state(*args):
        return {
            "status": "completed" if len(called) == 6 else "pending",
            "completed_scenes": min(len(called), 5),
        }

    async def receipts(*args):
        return {
            "task_id": ids[len(called)] if len(called) < 6 else ids[-1],
            "run_key": "synthetic-run",
            "operation_id": "other-operation"
            if outcome == "wrong_operation"
            else operation_id,
        }

    async def run_once(*, task_id, novel_id):
        assert novel_id == common["novel_id"] and task_id == ids[len(called)]
        if outcome == "timeout":
            raise TimeoutError("synthetic timeout")
        called.append(task_id)
        tasks[task_id].status = "done"

    monkeypatch.setattr(
        "core.database.get_manager", lambda: SimpleNamespace(session=session)
    )
    monkeypatch.setattr(control, "verify_runtime", verify)
    monkeypatch.setattr("modules.evolution.facade.read_map_cold_start_status", state)
    monkeypatch.setattr(
        "modules.evolution.facade.read_map_spatial_evaluation_receipts", receipts
    )
    monkeypatch.setattr("run_worker._configure_worker_process", lambda: None)
    monkeypatch.setattr(
        "run_worker._build_task_worker", lambda: SimpleNamespace(run_once=run_once)
    )
    path = control._evolution_record_path(root, family_id)
    map_spatial._write_private_json(
        path,
        {
            "status": "pending",
            "common_binding_sha256": control.digest(common),
            "run_key": "synthetic-run",
            "operation_id": operation_id,
            "tasks_completed": 0,
            "task_ids": [],
            "request_limit": 30,
        },
    )
    args = dict(
        private_root=root,
        family_id=family_id,
        api_base_url="http://map-spatial-eval.internal",
        max_tasks=2,
        execute=True,
    )
    if outcome == "done":
        first = await control.run_evolution(**args)
        assert first["status"] == "pending" and first["next_task_id"] == ids[2]
        assert called == ids[:2]
        await control.run_evolution(**args)
        last = await control.run_evolution(**args)
        assert last["status"] == "completed" and called == ids
    elif outcome == "sixth_scene":
        await control.run_evolution(**args)
        await control.run_evolution(**args)
        with pytest.raises(MapSpatialEvalError, match="最终结构阶段"):
            await control.run_evolution(**args)
        assert called == ids[:5]
        assert map_spatial._read_private_json(path)["status"] == "unknown"
    else:
        with pytest.raises((TimeoutError, MapSpatialEvalError)):
            await control.run_evolution(**args)
        assert map_spatial._read_private_json(path)["status"] == "unknown"
        with pytest.raises(MapSpatialEvalError):
            await control.run_evolution(**args)
        assert not called


@pytest.mark.asyncio
async def test_assistant_driver_uses_unknown_intent_and_exact_enabled_worker(
    tmp_path, monkeypatch
):
    import uuid

    import httpx

    from core.config import get_settings

    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    family_id = binding["family_id"]
    completed_calibration(root, binding)
    case_id, scope = next(iter(binding["case_bindings"].items()))
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setenv("APP_ENV", "test")
    source = {
        "cases": [{"case_id": case_id, "assistant": {"request": "预览调整当前地图"}}]
    }
    monkeypatch.setattr(control, "_load_family_source", lambda *_a, **_k: source)
    task_id, session_id = str(uuid.uuid4()), str(uuid.uuid4())
    task = SimpleNamespace(
        task_type="assistant_turn", status="pending", attempt=0, meta={}, result={}
    )
    requests = []

    async def post(path, *, json):
        assert "assistant.turn" in get_settings().map_spatial_enabled_capabilities
        requests.append((path, json))
        if path == "/api/assistant/sessions":
            return httpx.Response(200, json={"id": session_id})
        task.meta = {"run_id": json["operation_id"]}
        return httpx.Response(
            200,
            json={"id": json["operation_id"], "task_id": task_id, "status": "pending"},
        )

    @asynccontextmanager
    async def product_client(*args):
        yield SimpleNamespace(post=post, timeout=SimpleNamespace(read=30))

    async def scalar(query):
        assert str(next(iter(query.compile().params.values()))) == task_id
        return task

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(scalar=scalar)

    async def verify(*args):
        pass

    async def run_once(**kwargs):
        assert kwargs == {"task_id": task_id, "novel_id": binding["novel_id"]}
        assert "assistant.turn" in get_settings().map_spatial_enabled_capabilities
        task.status = "done"

    async def evidence(db, novel_id, run_id):
        return {
            "novel_id": novel_id,
            "run_id": run_id,
            "task_id": task_id,
            "scene_ids": [scope["scene_id"]],
            "scene_scope_status": "known",
            "status": "completed",
            "answer_status": "known",
            "tool_invocations_status": "unknown",
        }

    monkeypatch.setattr(control, "_product_client", product_client)
    monkeypatch.setattr(control, "verify_runtime", verify)
    monkeypatch.setattr(
        "core.database.get_manager", lambda: SimpleNamespace(session=session)
    )
    monkeypatch.setattr("run_worker._configure_worker_process", lambda: None)
    monkeypatch.setattr(
        "run_worker._build_task_worker", lambda: SimpleNamespace(run_once=run_once)
    )
    monkeypatch.setattr(
        "modules.assistant.facade.read_map_spatial_evaluation_turn", evidence
    )
    result = await control.run_assistant_turn(
        private_root=root,
        family_id=family_id,
        case_id=case_id,
        api_base_url="http://map-spatial-eval.internal",
        execute=True,
    )
    assert result["status"] == "completed"
    assert requests[1][1]["context"]["task_hint"] == "unknown"
    assert requests[1][1]["context"]["scene_id"] == scope["scene_id"]
    assert "assistant.turn" not in get_settings().map_spatial_enabled_capabilities


@pytest.mark.asyncio
async def test_proxy_author_promotes_through_original_route_then_confirms_map_separately(
    tmp_path, monkeypatch
):
    import uuid

    import httpx

    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    family_id = binding["family_id"]
    common = control.read_common_binding(root, family_id)
    completed_calibration(root, binding)
    case_id, scope = next(iter(common["case_bindings"].items()))
    source = map_spatial._read_private_json(root / family_id / "source.json")
    excerpt = source["cases"][0]["source_excerpt"]
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setattr(control, "_load_family_source", lambda *_a, **_k: source)
    operation_id = str(uuid.uuid4())
    clue_id, node_id, revision_id, entity_id = [str(uuid.uuid4()) for _ in range(4)]
    map_spatial._write_private_json(
        control._evolution_record_path(root, family_id),
        {"status": "completed", "operation_id": operation_id, "run_key": "synthetic-run"},
    )
    source_ref = scope["source_refs"][0]
    clue = {
        "id": clue_id,
        "scene_id": scope["scene_id"],
        "status": "pending_review",
        "fingerprint": "clue-fingerprint",
        "source_binding": {
            "draft_id": source_ref["draft_id"],
            "chapter_index": source_ref["chapter_index"],
            "content_hash": source_ref["source_hash"],
            "start_offset": source_ref["start_offset"],
            "end_offset": source_ref["end_offset"],
            "range_hash": source_ref["range_hash"],
            "content_mode": "canonical",
        },
        "clue_payload": {
            "quote": excerpt,
            "review": {"verdict": "supported"},
            "modality": "event_observed",
        },
    }
    artifacts = {
        "clues": [clue],
        "batches": [
            {
                "id": "batch",
                "result_refs": [
                    {
                        "status": "candidate",
                        "node_id": node_id,
                        "revision_id": revision_id,
                        "source_clue_ids": [clue_id],
                    }
                ],
            }
        ],
        "nodes": [{"id": node_id, "status": "provisional"}],
        "revisions": [{"id": revision_id, "base_revision_id": None}],
        "drafts": [],
    }
    calls = []

    async def evolution(*args):
        return {
            "world": artifacts,
            "receipts": {"steps": [{"scene_id": scope["scene_id"], "scene_index": 0}]},
        }

    async def read_artifacts(*args):
        return artifacts

    async def verify(*args):
        pass

    @asynccontextmanager
    async def session():
        yield None

    async def post(path, *, json):
        calls.append((path, json))
        if path.endswith("spatial-clues/" + clue_id + "/review"):
            return httpx.Response(
                200,
                json={
                    "id": clue_id,
                    "status": "adopted",
                    "fingerprint": "clue-fingerprint",
                },
            )
        if path.endswith("auto-drafts/build"):
            return httpx.Response(
                200,
                json={"status": "completed", "batch_id": "batch", "fingerprint": "build"},
            )
        if path.endswith("review-preview"):
            promoted = any("/promote?" in url for url, _ in calls)
            return httpx.Response(
                200,
                json={
                    "candidate_revision_id": revision_id,
                    "base_revision_id": None,
                    "applied_change_keys": ["feature:place"],
                    "candidate_locations": []
                    if promoted
                    else [
                        {
                            "entity_id": entity_id,
                            "name": "原创文本",
                            "can_adopt": True,
                            "source_hash": "source-cas",
                            "promotion_endpoint": (
                                f"/api/world/entities/{entity_id}/promote"
                            ),
                        }
                    ],
                },
            )
        if "/promote?" in path:
            assert json == {"expected_source_hash": "source-cas"}
            return httpx.Response(
                200, json={"entity_id": entity_id, "status": "canonical"}
            )
        assert path.endswith(f"revisions/{revision_id}/review")
        assert json == {
            "base_revision_id": None,
            "action": "adopt",
            "change_keys": ["feature:place"],
        }
        return httpx.Response(200, json={"status": "saved"})

    @asynccontextmanager
    async def client(*args):
        yield SimpleNamespace(post=post, timeout=SimpleNamespace(read=30))

    monkeypatch.setattr(
        "core.database.get_manager", lambda: SimpleNamespace(session=session)
    )
    monkeypatch.setattr(control, "verify_runtime", verify)
    monkeypatch.setattr(control, "read_evolution_product_evidence", evolution)
    monkeypatch.setattr(
        "modules.world.facade.read_map_spatial_evaluation_artifacts", read_artifacts
    )
    monkeypatch.setattr(control, "_product_client", client)
    # Match the real source contract rather than bypassing its validator.
    assert control._source_binding_matches(
        clue["source_binding"], scope["source_refs"], world_clue=True
    )
    result = await control.review_map_family(
        private_root=root,
        family_id=family_id,
        api_base_url="http://map-spatial-eval.internal",
        max_actions=20,
        execute=True,
    )
    assert result["status"] == "completed" and result["review_steps"] == 3
    record = map_spatial._read_private_json(control._review_record_path(root, family_id))
    assert [event["kind"] for event in record["review_events"]] == [
        "spatial_clue_review",
        "world_location_promote",
        "map_revision_review",
    ]
    assert len([url for url, _ in calls if url.endswith("review-preview")]) == 2
