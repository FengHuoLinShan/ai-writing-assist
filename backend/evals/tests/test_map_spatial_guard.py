"""Synthetic behavior tests: no model, connection verification or external DB calls."""

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import pytest

from evals.codex_executor import (
    CodexExecutionError,
    CodexStructuredExecutor,
    MapSpatialEvaluationScope,
    _strict_json_schema,
)
from evals.map_spatial import (
    MapSpatialEvalError,
    _database_identity,
    _read_private_json,
    _sha256_file,
    _write_private_json,
    claim_case,
    pipeline_hash,
    scene_source_refs,
    update_run,
    writing_arm,
)
from evals.map_spatial_guard import (
    CALIBRATION_STEP,
    SEEDS,
    CalibrationResult,
    calibration_prompt,
    digest,
    evaluate_development,
    finish_request,
    read_binding,
    request_path,
    require_calibration,
    require_development_gate,
    rubric_hash,
    same_source_baseline,
    start_request,
    verify_runtime,
)
from evals.tests.test_map_spatial import _fixture

URL = "postgresql+asyncpg://eval_owner@127.0.0.1:65204/map_spatial_eval_20261015"


def binding_fixture(tmp_path, monkeypatch):
    root, manifest, matrix = _fixture(tmp_path, monkeypatch)
    family = matrix["families"][0]
    owner, novel = str(uuid.uuid4()), str(uuid.uuid4())
    snapshot = {
        "profile": {
            "provider_id": "codex",
            "model": "gpt-6-luna",
            "connection_verified": True,
        }
    }
    binding = {
        **family,
        "suite": "map_spatial",
        "owner_id": owner,
        "novel_id": novel,
        "database_target": _database_identity(URL),
        "project_snapshot": snapshot,
        "project_snapshot_hash": digest(snapshot),
        "manifest_sha256": _sha256_file(manifest),
        "rubric_sha256": rubric_hash(),
        "private_root_sha256": digest(str(root.resolve())),
        "pipeline_hash": pipeline_hash(),
        "case_bindings": {},
    }
    for index in range(1, 6):
        binding["case_bindings"][f"{family['family_id']}-p{index}"] = {
            "novel_id": novel,
            "scene_id": str(uuid.uuid4()),
            "chapter_index": index,
        }
    _write_private_json(root / "bindings" / f"{family['family_id']}.json", binding)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DATABASE_URL", URL)
    return root, binding, matrix


def completed_calibration(root, binding, *, wrong=False):
    executor = CodexStructuredExecutor(attempts=1)
    prompt = calibration_prompt(binding)
    path = start_request(
        root,
        binding,
        "teacher_calibration",
        "seeded-v1",
        prompt,
        CALIBRATION_STEP,
        _strict_json_schema(CalibrationResult.model_json_schema()),
        executor.meta,
    )
    output = {
        "decisions": [
            {
                "case_id": row["id"],
                "label": "unknown" if wrong else row["label"],
                "reason": "synthetic fixture",
            }
            for row in SEEDS
        ]
    }
    finish_request(root, path, json.dumps(output), completed=True)
    return path


def test_calibration_uses_exact_raw_seed_results_and_executor_metadata(
    tmp_path, monkeypatch
):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    path = completed_calibration(root, binding)
    assert require_calibration(root, binding)["status"] == "completed"
    row = _read_private_json(path)
    row["executor_hash"] = "handwritten-passed"
    _write_private_json(path, row)
    with pytest.raises(MapSpatialEvalError, match="executor/schema"):
        require_calibration(root, binding)


def test_failed_calibration_is_consumed_and_cannot_be_replaced(tmp_path, monkeypatch):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    completed_calibration(root, binding, wrong=True)
    with pytest.raises(MapSpatialEvalError, match="校准未通过"):
        require_calibration(root, binding)
    with pytest.raises(MapSpatialEvalError, match="不重发"):
        completed_calibration(root, binding)


def test_seed_output_tamper_closes_gate(tmp_path, monkeypatch):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    path = completed_calibration(root, binding)
    row = _read_private_json(path)
    _write_private_json(root / row["raw_output"], {"passed": True})
    with pytest.raises(MapSpatialEvalError, match="账本不完整"):
        require_calibration(root, binding)


def test_binding_rejects_material_or_pipeline_drift(tmp_path, monkeypatch):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    assert read_binding(root, binding["family_id"]) == binding
    monkeypatch.setattr("evals.map_spatial.pipeline_hash", lambda: "changed")
    with pytest.raises(MapSpatialEvalError, match="管线代码版本"):
        read_binding(root, binding["family_id"])


def test_handwritten_gate_cannot_substitute_real_development_records(
    tmp_path, monkeypatch
):
    root, _, matrix = binding_fixture(tmp_path, monkeypatch)
    _write_private_json(root / "gates/development-gate.json", {"passed": True})
    with pytest.raises(MapSpatialEvalError):
        require_development_gate(root, matrix)
    with pytest.raises(MapSpatialEvalError):
        evaluate_development(root, matrix)
    assert not (root / "run-ledger.json").exists()


def test_claim_is_atomic_and_unknown_is_immutable(tmp_path, monkeypatch):
    root, binding, matrix = binding_fixture(tmp_path, monkeypatch)
    family = matrix["families"][0]
    case_id = next(iter(binding["case_bindings"]))

    def claim():
        try:
            return claim_case(root, matrix, family, case_id)["status"]
        except MapSpatialEvalError:
            return "refused"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: claim(), range(8)))
    assert results.count("started") == 1
    assert results.count("refused") == 7
    update_run(root, family["family_id"], case_id, status="unknown")
    with pytest.raises(MapSpatialEvalError, match="不能重置"):
        update_run(root, family["family_id"], case_id, status="started")


def test_writing_override_restores_frozen_settings_after_interruption(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("MAP_SPATIAL_ENABLED_CAPABILITIES", "world.ask,writing.generate")
    get_settings.cache_clear()
    original = get_settings()
    try:
        with pytest.raises(asyncio.CancelledError):
            with writing_arm(False):
                assert get_settings().map_spatial_enabled_capabilities == ("world.ask",)
                raise asyncio.CancelledError
        assert original.map_spatial_enabled_capabilities == (
            "world.ask",
            "writing.generate",
        )
        assert (
            get_settings().map_spatial_enabled_capabilities
            == original.map_spatial_enabled_capabilities
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "db", "owner", "project", "snapshot", "effort", "unverified"]
)
async def test_runtime_rechecks_normal_owner_and_snapshot_and_always_rolls_back(
    tmp_path, monkeypatch, fault
):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    current = deepcopy(binding["project_snapshot"])
    owner = binding["owner_id"]
    events = []
    if fault == "snapshot":
        current["changed"] = True
    if fault == "unverified":
        current["profile"]["connection_verified"] = False

    async def active_account(db, account_id, *, allow_local_bootstrap):
        assert allow_local_bootstrap is False
        events.append("account")

    async def active_project(db, novel_id):
        assert novel_id == binding["novel_id"]
        events.append("project")

    async def build(db, novel_id):
        events.append("snapshot")
        return current

    async def restore(db, novel_id, snapshot):
        return {
            "llm": {"extra": {"reasoning_effort": "high" if fault == "effort" else "max"}}
        }

    async def scalar(query):
        return SimpleNamespace(
            owner_id=owner,
            project_kind="author",
            title="real-manuscript"
            if fault == "project"
            else f"MAP-EVAL:{binding['family_id']}:test",
        )

    async def rollback():
        events.append("rollback")

    monkeypatch.setattr(
        "modules.account.facade.current_account_id",
        lambda: uuid.UUID(owner) if fault != "owner" else uuid.uuid4(),
    )
    monkeypatch.setattr("modules.account.facade.require_account_active", active_account)
    monkeypatch.setattr("modules.project.facade.require_active_project", active_project)
    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot", build
    )
    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings", restore
    )
    actual = URL.replace("65204", "65205") if fault == "db" else URL
    db = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(url=actual), scalar=scalar, rollback=rollback
    )
    if fault:
        with pytest.raises(MapSpatialEvalError):
            await verify_runtime(db, binding)
    else:
        await verify_runtime(db, binding)
        assert events == ["account", "project", "snapshot", "rollback"]
    assert events[-1] == "rollback"


@pytest.mark.asyncio
async def test_map_scope_accepts_only_exact_seeded_role_and_journals_one_call(
    tmp_path, monkeypatch
):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")
    events = []

    async def verify(db, value):
        assert value == binding
        events.append("verified-and-rolled-back")

    async def invoke(*args, **kwargs):
        events.append("native-test-double")
        return json.dumps(
            {
                "decisions": [
                    {
                        "case_id": row["id"],
                        "label": row["label"],
                        "reason": "seed fixture",
                    }
                    for row in SEEDS
                ]
            }
        )

    monkeypatch.setattr("evals.map_spatial_guard.verify_runtime", verify)
    monkeypatch.setattr("evals.codex_executor.shutil.which", lambda _: "/synthetic/codex")
    scope = MapSpatialEvaluationScope(
        None, root, binding, "teacher_calibration", "seeded-v1", execute=True
    )
    executor = CodexStructuredExecutor(attempts=1, calibration=scope)
    monkeypatch.setattr(executor, "_invoke", invoke)
    prompt = calibration_prompt(binding)
    with pytest.raises(CodexExecutionError, match="fixed seeded"):
        await executor.generate_structured(
            prompt + "changed", CalibrationResult, step_name=CALIBRATION_STEP
        )
    assert "native-test-double" not in events
    events.clear()
    await executor.generate_structured(
        prompt, CalibrationResult, step_name=CALIBRATION_STEP
    )
    assert events == [
        "verified-and-rolled-back",
        "verified-and-rolled-back",
        "native-test-double",
    ]
    require_calibration(root, binding)
    with pytest.raises(MapSpatialEvalError, match="不重发"):
        await executor.generate_structured(
            prompt, CalibrationResult, step_name=CALIBRATION_STEP
        )
    assert events.count("native-test-double") == 1


@pytest.mark.asyncio
async def test_unknown_scoring_request_never_retries(tmp_path, monkeypatch):
    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", "1")

    async def verify(*args):
        pass

    calls = []

    async def invoke(*args, **kwargs):
        calls.append("call")
        raise asyncio.CancelledError

    monkeypatch.setattr("evals.map_spatial_guard.verify_runtime", verify)
    monkeypatch.setattr("evals.codex_executor.shutil.which", lambda _: "/synthetic/codex")
    scope = MapSpatialEvaluationScope(
        None, root, binding, "teacher_calibration", "seeded-v1", execute=True
    )
    executor = CodexStructuredExecutor(attempts=1, calibration=scope)
    monkeypatch.setattr(executor, "_invoke", invoke)
    with pytest.raises(asyncio.CancelledError):
        await executor.generate_structured(
            calibration_prompt(binding), CalibrationResult, step_name=CALIBRATION_STEP
        )
    row = _read_private_json(
        request_path(root, binding, "teacher_calibration", "seeded-v1")
    )
    assert row["status"] == "unknown"
    with pytest.raises(MapSpatialEvalError, match="不重发"):
        await executor.generate_structured(
            calibration_prompt(binding), CalibrationResult, step_name=CALIBRATION_STEP
        )
    assert calls == ["call"]


@pytest.mark.asyncio
async def test_default_map_and_global_executor_remain_closed_before_db_or_cli(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", raising=False)
    scope = MapSpatialEvaluationScope(
        None, tmp_path, {}, "teacher_calibration", "seeded-v1"
    )
    with pytest.raises(CodexExecutionError, match="closed"):
        await CodexStructuredExecutor(attempts=1, calibration=scope).generate_structured(
            "x", CalibrationResult, step_name=CALIBRATION_STEP
        )
    with pytest.raises(CodexExecutionError, match="paused"):
        await CodexStructuredExecutor().generate_structured(
            "x", CalibrationResult, step_name=CALIBRATION_STEP
        )
    with pytest.raises(ValueError, match="never automatically retries"):
        CodexStructuredExecutor(calibration=scope)


@pytest.mark.asyncio
async def test_scene_source_preflight_reads_real_exact_canonical_ranges(
    db_session, test_project_id
):
    from modules.story.outline_state.models import Scene, SceneSpan
    from modules.writing.models import WritingDraft
    from modules.writing.source_hashing import hash_text

    content = "门外是北港。沿同一街向南就是钟楼。"
    draft = WritingDraft(
        novel_id=uuid.UUID(test_project_id),
        chapter_index=1,
        content=content,
        content_hash=hash_text(content),
        status="published",
    )
    scene = Scene(
        novel_id=uuid.UUID(test_project_id),
        scene_index=1,
        title="source ref only",
        chapter_ids=["1"],
        status="canonical",
    )
    db_session.add_all([draft, scene])
    await db_session.flush()
    span = SceneSpan(
        novel_id=uuid.UUID(test_project_id),
        scene_id=scene.id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=draft.id,
        source_content_hash=draft.content_hash,
        start_offset=0,
        end_offset=len(content),
        mapping_status="exact",
        part_no=1,
        status="canonical",
    )
    db_session.add(span)
    await db_session.flush()
    refs = await scene_source_refs(db_session, test_project_id, str(scene.id), 1, content)
    assert len(refs) == 1 and refs[0]["source_hash"] == draft.content_hash
    span.source_content_hash = "f" * 64
    await db_session.flush()
    with pytest.raises(MapSpatialEvalError, match="来源已经漂移"):
        await scene_source_refs(db_session, test_project_id, str(scene.id), 1, content)


def test_verify_never_decodes_holdout_content_before_gate(tmp_path, monkeypatch):
    from evals import map_spatial

    root, _, matrix = _fixture(tmp_path, monkeypatch)
    actual_read = map_spatial._read_private_json
    reads = []

    def read(path):
        assert "holdout" not in str(path)
        reads.append(path)
        return actual_read(path)

    monkeypatch.setattr(map_spatial, "_read_private_json", read)
    assert len(map_spatial.verify_materials(root, matrix)) == 10
    assert len(reads) == 10


@pytest.mark.asyncio
async def test_lifecycle_default_refuses_before_manager_or_binding(tmp_path, monkeypatch):
    from evals.map_spatial_control import freeze_binding, score

    monkeypatch.delenv("MAP_SPATIAL_EVAL_ALLOW_LIVE", raising=False)
    with pytest.raises(MapSpatialEvalError, match="默认关闭"):
        await freeze_binding(
            private_root=tmp_path / "absent",
            family_id="x",
            scopes=tmp_path / "scopes",
            execute=True,
        )
    with pytest.raises(MapSpatialEvalError, match="默认关闭"):
        await score(
            private_root=tmp_path / "absent",
            family_id="x",
            phase="teacher_calibration",
            case_id="seeded-v1",
            execute=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [False, True])
async def test_pair_freezes_both_confirmations_before_exact_worker_claim(
    tmp_path, monkeypatch, drift
):
    from contextlib import asynccontextmanager

    from core.config import get_settings
    from evals import map_spatial
    from modules.writing.generation_service import WritingGenerationService

    root, binding, matrix = binding_fixture(tmp_path, monkeypatch)
    family = matrix["families"][0]
    case_id = next(iter(binding["case_bindings"]))
    case_scope = binding["case_bindings"][case_id]
    case_scope.update(
        scene_hash="scene",
        map_snapshot_hash="map",
        project_snapshot_hash=binding["project_snapshot_hash"],
    )
    # The orchestration boundary uses deterministic product doubles; actual Scene
    # source reads are covered by the separate SQLite integration test above.
    monkeypatch.setattr(
        map_spatial, "_require_live_scope_approval", lambda *a, **k: binding
    )
    source_path = root / family["family_id"] / "source.json"
    source = _read_private_json(source_path)
    source["cases"][0]["writing_scene_instruction"] = "只写当前场景"
    # Freeze fixture hashes again before any operation, as a new synthetic manifest.
    _write_private_json(source_path, source)
    family["source_sha256"] = _sha256_file(source_path)
    map_spatial.MATRIX_PATH.write_text(json.dumps(matrix))
    binding["source_sha256"] = family["source_sha256"]

    async def preflight(**kwargs):
        return case_scope.copy()

    monkeypatch.setattr(map_spatial, "preflight_project", preflight)
    tasks, drafts, calls = {}, {}, []
    active_task = None

    async def scalar(query):
        return tasks[active_task]

    db = SimpleNamespace(scalar=scalar)

    @asynccontextmanager
    async def session():
        yield db

    manager = SimpleNamespace(session=session)

    async def build(*args):
        return binding["project_snapshot"]

    async def scene(*args):
        return SimpleNamespace(id=case_scope["scene_id"])

    confirmations = {}

    async def confirm(db, request):
        enabled = "writing.generate" in get_settings().map_spatial_enabled_capabilities
        options = {
            "map_spatial_baseline": ["saved-version"] if enabled else [],
            "compiled_context_core_fingerprint": "drift"
            if drift and enabled
            else "same-core",
        }
        value = SimpleNamespace(id=str(uuid.uuid4()), compile_options=options)
        confirmations[value.id] = value
        calls.append(("confirm", enabled))
        return value

    async def prepare(*args, **kwargs):
        return SimpleNamespace(rendered_markdown=source["cases"][0]["source_excerpt"])

    async def submit(self, db, request, **kwargs):
        task_id, draft_id = str(uuid.uuid4()), str(uuid.uuid4())
        tasks[task_id] = SimpleNamespace(
            status="pending", attempt=0, result={"draft_id": draft_id}
        )
        drafts[draft_id] = SimpleNamespace(
            id=draft_id, content="synthetic prose", content_hash="draft-hash"
        )
        calls.append(("submit", task_id))
        return {"task_id": task_id}

    async def run_once(*, task_id, novel_id):
        nonlocal active_task
        assert novel_id == binding["novel_id"]
        assert len(tasks) == 2 and len(confirmations) == 2
        assert task_id in tasks
        active_task = task_id
        tasks[task_id].status = "done"
        calls.append(("run_exact", task_id))

    async def draft(db, novel_id, draft_id):
        return drafts[draft_id]

    async def verify(*args):
        pass

    monkeypatch.setattr("core.database.get_manager", lambda: manager)
    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot", build
    )
    monkeypatch.setattr("modules.story.facade.get_scene_contract", scene)
    monkeypatch.setattr("modules.evidence.facade.confirm_context", confirm)
    monkeypatch.setattr("modules.evidence.facade.prepare_confirmed_ai_action", prepare)
    monkeypatch.setattr(WritingGenerationService, "submit_generation", submit)
    monkeypatch.setattr("modules.writing.facade.get_draft", draft)
    monkeypatch.setattr("run_worker._configure_worker_process", lambda: None)
    monkeypatch.setattr(
        "run_worker._build_task_worker", lambda: SimpleNamespace(run_once=run_once)
    )
    monkeypatch.setattr("evals.map_spatial_guard.verify_runtime", verify)
    original = get_settings().map_spatial_enabled_capabilities
    args = dict(
        private_root=root,
        family_id=family["family_id"],
        case_id=case_id,
        novel_id=binding["novel_id"],
        scene_id=case_scope["scene_id"],
        chapter_index=case_scope["chapter_index"],
        execute=True,
    )
    if drift:
        with pytest.raises(MapSpatialEvalError, match="core_context_hash"):
            await map_spatial.run_writing_pair(**args)
        assert not any(name == "run_exact" for name, _ in calls)
    else:
        assert (await map_spatial.run_writing_pair(**args))["status"] == "completed"
        assert [name for name, _ in calls] == [
            "confirm",
            "submit",
            "confirm",
            "submit",
            "run_exact",
            "run_exact",
        ]
        assert {value for name, value in calls if name == "run_exact"} == set(tasks)
    assert get_settings().map_spatial_enabled_capabilities == original


def test_common_source_baseline_allows_evolution_enrichment_but_not_span_drift():
    common = {
        "novel_id": "novel",
        "owner_id": "owner",
        "database_target": ["127.0.0.1", "65302", "map_spatial_eval_20261015"],
        "scene_id": "scene",
        "chapter_index": 1,
        "scene_hash": "before-enrichment",
        "source_snapshot_hash": "source-hash",
        "source_refs": [{"start_offset": 12, "end_offset": 28}],
        "project_snapshot_hash": "project-hash",
    }
    after_evolution = {**common, "scene_hash": "enriched-scene-card"}
    assert same_source_baseline(after_evolution, common)
    for field, changed in (
        ("source_snapshot_hash", "changed-source-hash"),
        ("project_snapshot_hash", "changed-project-hash"),
        ("scene_id", "another-scene"),
    ):
        drifted = {**after_evolution, field: changed}
        assert not same_source_baseline(drifted, common)
    drifted_span = {
        **after_evolution,
        "source_refs": [{"start_offset": 13, "end_offset": 28}],
    }
    assert not same_source_baseline(drifted_span, common)


def test_evolution_source_receipt_requires_exact_canonical_range():
    from evals.map_spatial_guard import _source_binding_matches

    refs = [
        {
            "draft_id": "draft-1",
            "chapter_index": 2,
            "content_hash": "content-hash",
            "start_offset": 4,
            "end_offset": 19,
            "range_hash": "range-hash",
            "content_mode": "canonical",
        }
    ]
    receipt = {
        "draft_id": "draft-1",
        "chapter_index": 2,
        "content_hash": "content-hash",
        "start_offset": 4,
        "end_offset": 19,
        "range_hash": "range-hash",
        "content_mode": "canonical",
    }
    assert _source_binding_matches(receipt, refs)
    assert not _source_binding_matches({**receipt, "start_offset": 5}, refs)
    assert not _source_binding_matches({**receipt, "content_mode": "draft"}, refs)


@pytest.mark.asyncio
async def test_assistant_adapter_preserves_real_unknown_tool_telemetry_without_inference(
    tmp_path, monkeypatch
):
    import sys
    from types import ModuleType

    from evals.map_spatial import _write_private_json
    from evals.map_spatial_guard import read_assistant_product_evidence

    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    case_id, scope = next(iter(binding["case_bindings"].items()))
    run_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())
    evidence = {
        "schema_version": 1,
        "novel_id": binding["novel_id"],
        "run_id": run_id,
        "task_id": task_id,
        "scene_ids": [scope["scene_id"]],
        "scene_scope_status": "known",
        "request": {"context": {"scene_id": scope["scene_id"]}},
        "result": {"answer": "当前证据不足，无法确认该地点位置。"},
        "answer_status": "completed",
        "tool_invocations": None,
        "tool_invocations_status": "unknown",
        "truncated": False,
        "omitted_count": 0,
        "human_validated": False,
    }
    _write_private_json(
        root
        / "task-ledger"
        / "assistant"
        / binding["family_id"]
        / case_id
        / f"{task_id}.json",
        {
            "task_type": "assistant_turn",
            "status": "completed",
            "run_id": run_id,
            "task_id": task_id,
        },
    )
    module = ModuleType("modules.assistant.facade")

    async def read_turn(db, novel_id, requested_run_id):
        assert db == "synthetic-db-handle"
        assert novel_id == binding["novel_id"]
        assert requested_run_id == run_id
        return evidence

    module.read_map_spatial_evaluation_turn = read_turn
    monkeypatch.setitem(sys.modules, "modules.assistant.facade", module)
    record = {
        "run_id": run_id,
        "task_id": task_id,
        "evidence_sha256": digest(evidence),
    }

    adapted = await read_assistant_product_evidence(
        "synthetic-db-handle", root, binding, case_id, record
    )

    assert adapted["result"] == evidence["result"]
    assert adapted["tool_invocations"] is None
    assert adapted["tool_invocations_status"] == "unknown"
    assert adapted["answer_status"] == "completed"


@pytest.mark.asyncio
async def test_assistant_adapter_rejects_cross_project_or_scene_receipt(
    tmp_path, monkeypatch
):
    import sys
    from types import ModuleType

    from evals.map_spatial import _write_private_json
    from evals.map_spatial_guard import read_assistant_product_evidence

    root, binding, _ = binding_fixture(tmp_path, monkeypatch)
    case_id, scope = next(iter(binding["case_bindings"].items()))
    run_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())
    evidence = {
        "schema_version": 1,
        "novel_id": str(uuid.uuid4()),
        "run_id": run_id,
        "task_id": task_id,
        "scene_ids": [scope["scene_id"]],
        "scene_scope_status": "known",
        "request": {"context": {"scene_id": scope["scene_id"]}},
        "tool_invocations": None,
        "tool_invocations_status": "unknown",
        "truncated": False,
        "omitted_count": 0,
        "human_validated": False,
    }
    _write_private_json(
        root
        / "task-ledger"
        / "assistant"
        / binding["family_id"]
        / case_id
        / f"{task_id}.json",
        {
            "task_type": "assistant_turn",
            "status": "completed",
            "run_id": run_id,
            "task_id": task_id,
        },
    )
    module = ModuleType("modules.assistant.facade")
    module.read_map_spatial_evaluation_turn = lambda *args: _async_value(evidence)
    monkeypatch.setitem(sys.modules, "modules.assistant.facade", module)

    with pytest.raises(MapSpatialEvalError, match="真实Scene/run/task"):
        await read_assistant_product_evidence(
            "synthetic-db-handle",
            root,
            binding,
            case_id,
            {"run_id": run_id, "task_id": task_id, "evidence_sha256": digest(evidence)},
        )


async def _async_value(value):
    return value


def test_binding_identity_is_checked_before_any_private_decode(tmp_path, monkeypatch):
    root, _, _ = binding_fixture(tmp_path, monkeypatch)

    def forbidden_read(path):
        pytest.fail("unknown family must not read private data")

    monkeypatch.setattr("evals.map_spatial._read_private_json", forbidden_read)
    with pytest.raises(MapSpatialEvalError, match="冻结manifest"):
        read_binding(root, "../map-xianxia-holdout-v1/source")
