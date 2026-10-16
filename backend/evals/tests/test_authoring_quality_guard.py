"""Offline admission tests: no model process or real account/DB access."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from evals import authoring_quality_guard as guard
from evals.codex_executor import (
    CodexExecutionError,
    CodexStructuredExecutor,
    _strict_json_schema,
)

VERIFY_PROJECT_RUNTIME = guard.verify_project_runtime


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in (path.parent, *path.parents):
        if parent.name == "private":
            parent.chmod(0o700)
            break
        parent.chmod(0o700)
    path.write_bytes(guard.canonical_json(value))
    path.chmod(0o600)


def _fixture(tmp_path, monkeypatch, *, domain="director"):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    models = {
        "seed": guard.SeedCalibrationResult,
        "teacher": guard.TeacherReferenceResult,
        "judge": guard.JudgeResult,
    }
    entries = []
    source = "The adopted ledger records a closed east gate."
    for phase, model in models.items():
        case_id = "seed-v1" if phase == "seed" else "case-1"
        folder = root / "cases" / domain / phase / case_id
        text = {
            "schema_version": 1,
            "domain": domain,
            "case_id": case_id,
            "task": "Determine whether the gate is open.",
            "constraints": [],
            "sources": [
                {
                    "source_id": "source-1",
                    "source_kind": "author_source",
                    "text": source,
                    "source_sha256": guard._sha256_bytes(source.encode()),
                }
            ]
            if phase == "teacher"
            else [],
        }
        rubric = {
            "schema_version": 1,
            "version": guard.AUTHORING_QUALITY_VERSION,
            "domain": domain,
            "case_id": case_id,
            "human_validated": False,
            "criteria": [
                {
                    "criterion_id": "source-fidelity",
                    "description": "No invented evidence",
                    "scale": "pass_fail_unknown",
                }
            ],
        }
        case = {
            "schema_version": 1,
            "domain": domain,
            "case_id": case_id,
            "source_group_id": "synthetic-family",
            "input_sha256": guard.digest(text),
            "product_ref": {
                "kind": domain,
                "scene_id": str(uuid4()),
                "root_id": str(uuid4()),
                "branch_id": str(uuid4()),
                "task_id": str(uuid4()),
                "source_sha256": "a" * 64,
                "output_ids": [str(uuid4())],
            }
            if phase == "judge" and domain in {"director", "world_progression"}
            else None,
        }
        split = {
            "schema_version": 1,
            "domain": domain,
            "case_id": case_id,
            "source_group_id": "synthetic-family",
            "split": "calibration" if phase == "seed" else "development",
        }
        for name, value in {
            "case": case,
            "input": text,
            "rubric": rubric,
            "split": split,
        }.items():
            _write(folder / f"{name}.json", value)
        entries.append(
            {
                "domain": domain,
                "phase": phase,
                "case_id": case_id,
                "split": split["split"],
                "schema_sha256": guard.schema_fingerprint(
                    model, _strict_json_schema(model.model_json_schema())
                ),
                **{
                    f"{name}_sha256": guard.digest(value)
                    for name, value in {
                        "case": case,
                        "input": text,
                        "rubric": rubric,
                        "split": split,
                    }.items()
                },
                "product_evidence_sha256": guard.digest({"proof": "actual-reader"})
                if phase == "judge"
                else None,
            }
        )
    project = str(uuid4())
    snapshot = {
        "novel_id": project,
        "profile": {
            "provider_id": "codex",
            "model": "gpt-6-luna",
            "connection_verified": True,
        },
    }
    manifest = {
        "schema_version": 1,
        "suite": "authoring_quality",
        "version": guard.AUTHORING_QUALITY_VERSION,
        "owner_id": str(uuid4()),
        "project_id": project,
        "project_title": "AUTHORING-QUALITY: synthetic",
        "project_snapshot": snapshot,
        "project_snapshot_sha256": guard.digest(snapshot),
        "pipeline_sha256": guard.pipeline_fingerprint(),
        "private_root_sha256": guard.digest(str(root.resolve())),
        "database_sha256": guard.digest("isolated-db"),
        "request_budget": 12,
        "human_validated": False,
        "cases": entries,
    }
    _write(root / "manifest.json", manifest)
    db = SimpleNamespace(rollback=AsyncMock())

    async def verify(db, _manifest):
        await db.rollback()

    monkeypatch.setattr(guard, "verify_project_runtime", verify)
    monkeypatch.setenv(guard.AUTHORING_QUALITY_LIVE_ENV, "1")
    scope = guard.AuthoringQualityEvaluationScope(
        db, root, manifest, domain, "seed", "seed-v1", True
    )
    return scope, models


def _prompt(scope):
    root = scope.private_root
    manifest = guard.AuthoringQualityManifest.model_validate(scope.manifest)
    entry = guard._entry(manifest, scope.domain, scope.phase, scope.case_id)
    case, text, rubric, *_ = guard._load_case_artifacts(root, manifest, entry)
    manifest_hash = guard._sha256_bytes((root / "manifest.json").read_bytes())
    if scope.phase == "seed":
        return guard._seed_prompt(scope.domain, rubric, manifest_hash)
    if scope.phase == "teacher":
        return guard._teacher_prompt(entry, case, text, rubric, manifest_hash)
    return guard._judge_prompt(
        entry,
        case,
        text,
        rubric,
        {"proof": "actual-reader"},
        manifest_hash,
        guard._require_teacher(root, manifest, entry),
    )


def _result(scope):
    if scope.phase == "seed":
        return {
            "decisions": [
                {
                    "seed_id": row["seed_id"],
                    "label": row["expected"],
                    "reason": "Synthetic evidence anchor",
                }
                for row in guard.SEED_CASES
            ]
        }
    if scope.phase == "teacher":
        return {
            "case_id": "case-1",
            "reference_points": [
                {
                    "claim": "The gate is closed.",
                    "status": "supported",
                    "source_ids": ["source-1"],
                    "rationale": "Direct source statement",
                }
            ],
            "omissions": [],
        }
    return {
        "case_id": "case-1",
        "criteria": [
            {
                "criterion_id": "source-fidelity",
                "outcome": "pass",
                "evidence_ids": ["source"],
                "rationale": "Bounded product evidence",
            }
        ],
        "missing_evidence": [],
    }


async def _call(scope, models, monkeypatch, *, response=None, calls=None):
    executor = CodexStructuredExecutor(calibration=scope, attempts=1)
    monkeypatch.setattr("evals.codex_executor.shutil.which", lambda _: "/offline/codex")

    async def invoke(_executable, _prompt, _schema, *, step_name):
        if calls is not None:
            calls.append(step_name)
        return json.dumps(response if response is not None else _result(scope))

    monkeypatch.setattr(executor, "_invoke", invoke)
    return await executor.generate_structured(
        _prompt(scope),
        models[scope.phase],
        step_name=guard.STEPS[(scope.domain, scope.phase)],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", ["execute", "environment"])
async def test_default_closed_before_model_io(tmp_path, monkeypatch, closed):
    scope, models = _fixture(tmp_path, monkeypatch)
    if closed == "execute":
        scope = replace(scope, execute=False)
    else:
        monkeypatch.delenv(guard.AUTHORING_QUALITY_LIVE_ENV)
    calls = []
    with pytest.raises(CodexExecutionError, match="require execute"):
        await _call(scope, models, monkeypatch, calls=calls)
    assert calls == []
    assert not (scope.private_root / "request-journal.json").exists()


@pytest.mark.asyncio
async def test_seed_teacher_and_reader_bound_judge_only_once(tmp_path, monkeypatch):
    scope, models = _fixture(tmp_path, monkeypatch)
    calls = []
    await _call(scope, models, monkeypatch, calls=calls)
    teacher = replace(scope, phase="teacher", case_id="case-1")
    prompt = _prompt(teacher)
    assert '"product_ref":null' in prompt and '"source-1"' in prompt
    assert "product_evidence" not in json.loads(prompt)
    await _call(teacher, models, monkeypatch, calls=calls)
    reader = AsyncMock(return_value={"proof": "actual-reader"})
    monkeypatch.setattr("evals.authoring_quality_product.read_product_evidence", reader)
    judge = replace(scope, phase="judge", case_id="case-1")
    await _call(judge, models, monkeypatch, calls=calls)
    reader.assert_awaited_once()
    with pytest.raises(CodexExecutionError, match="cannot be replayed"):
        await _call(judge, models, monkeypatch, calls=calls)
    assert len(calls) == 3
    assert scope.db.rollback.await_count >= 4
    assert all(
        row["status"] == "completed"
        for row in guard._read_journal(scope.private_root)["requests"].values()
    )


@pytest.mark.asyncio
async def test_bad_seed_blocks_teacher_without_another_request(tmp_path, monkeypatch):
    scope, models = _fixture(tmp_path, monkeypatch)
    response = _result(scope)
    response["decisions"][0]["label"] = "contradicted"
    await _call(scope, models, monkeypatch, response=response)
    with pytest.raises(CodexExecutionError, match="calibration has not passed"):
        await _call(
            replace(scope, phase="teacher", case_id="case-1"), models, monkeypatch
        )
    assert len(guard._read_journal(scope.private_root)["requests"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift", ["pipeline", "manifest", "source", "rubric", "permissions", "symlink"]
)
async def test_artifact_and_pipeline_drift_deny_before_io(tmp_path, monkeypatch, drift):
    scope, models = _fixture(tmp_path, monkeypatch)
    prompt = _prompt(scope)
    if drift == "pipeline":
        monkeypatch.setattr(guard, "pipeline_fingerprint", lambda: "0" * 64)
    elif drift == "manifest":
        changed = {**scope.manifest, "project_title": "AUTHORING-QUALITY: another"}
        _write(scope.private_root / "manifest.json", changed)
    else:
        filename = "input" if drift == "source" else "rubric"
        path = (
            scope.private_root
            / "cases"
            / scope.domain
            / "seed"
            / "seed-v1"
            / f"{filename}.json"
        )
        if drift == "permissions":
            path.chmod(0o644)
        elif drift == "symlink":
            target = tmp_path / "replaced.json"
            path.rename(target)
            path.symlink_to(target)
        else:
            path.write_text(path.read_text() + " ")
    with pytest.raises(guard.AuthoringQualityError):
        await scope.authorize(
            prompt,
            models["seed"],
            guard.STEPS[(scope.domain, "seed")],
            _strict_json_schema(models["seed"].model_json_schema()),
        )
    assert not (scope.private_root / "request-journal.json").exists()


@pytest.mark.asyncio
async def test_invalid_provider_result_is_unknown_and_never_retried(
    tmp_path, monkeypatch
):
    scope, models = _fixture(tmp_path, monkeypatch)
    calls = []
    with pytest.raises(ValueError):
        await _call(scope, models, monkeypatch, response={"invalid": True}, calls=calls)
    with pytest.raises(CodexExecutionError, match="cannot be replayed"):
        await _call(scope, models, monkeypatch, calls=calls)
    assert len(calls) == 1
    assert [
        x["status"] for x in guard._read_journal(scope.private_root)["requests"].values()
    ] == ["unknown"]


@pytest.mark.asyncio
async def test_seed_response_tampering_and_foreign_teacher_citation_are_rejected(
    tmp_path, monkeypatch
):
    scope, models = _fixture(tmp_path, monkeypatch)
    await _call(scope, models, monkeypatch)
    teacher = replace(scope, phase="teacher", case_id="case-1")
    response = _result(teacher)
    response["reference_points"][0]["source_ids"] = ["foreign-source"]
    with pytest.raises(guard.AuthoringQualityError, match="unfrozen source"):
        await _call(teacher, models, monkeypatch, response=response)
    key = next(
        key
        for key, row in guard._read_journal(scope.private_root)["requests"].items()
        if row["phase"] == "seed"
    )
    _write(scope.private_root / f"response-{key}.json", {"decisions": []})
    with pytest.raises(guard.AuthoringQualityError, match="receipt"):
        guard._require_seed(scope.private_root, scope.domain)


def test_request_claim_is_atomic_and_budget_is_cumulative(tmp_path, monkeypatch):
    scope, _models = _fixture(tmp_path, monkeypatch)
    entry = guard.CaseBinding.model_validate(scope.manifest["cases"][0])

    def claim(_index):
        try:
            return scope.start_request(entry, "seed", "same frozen request", {})
        except guard.AuthoringQualityError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(x is not None for x in pool.map(claim, range(2))) == 1
    for index in range(11):
        scope.start_request(entry, "seed", f"separate frozen request {index}", {})
    with pytest.raises(guard.AuthoringQualityError, match="exhausted"):
        scope.start_request(entry, "seed", "thirteenth request", {})
    assert len(guard._read_journal(scope.private_root)["requests"]) == 12


@pytest.mark.asyncio
async def test_judge_revalidates_actual_product_reader(tmp_path, monkeypatch):
    scope, models = _fixture(tmp_path, monkeypatch)
    await _call(scope, models, monkeypatch)
    await _call(replace(scope, phase="teacher", case_id="case-1"), models, monkeypatch)
    monkeypatch.setattr(
        "evals.authoring_quality_product.read_product_evidence",
        AsyncMock(return_value={"proof": "changed-output"}),
    )
    with pytest.raises(CodexExecutionError, match="evidence drifted"):
        await _call(replace(scope, phase="judge", case_id="case-1"), models, monkeypatch)
    assert len(guard._read_journal(scope.private_root)["requests"]) == 2


@pytest.mark.parametrize("domain", ["dossier", "forecast", "notices", "goal"])
def test_other_judges_remain_closed(tmp_path, monkeypatch, domain):
    scope, _models = _fixture(tmp_path, monkeypatch, domain=domain)
    manifest = guard.AuthoringQualityManifest.model_validate(scope.manifest)
    with pytest.raises(guard.AuthoringQualityError, match="limited"):
        guard._entry(manifest, domain, "judge", "case-1")


def test_no_retry_or_cross_scope_transport_override(tmp_path, monkeypatch):
    scope, _models = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="never automatically retries"):
        CodexStructuredExecutor(calibration=scope, attempts=2)
    assert guard._case_relative("director", "teacher", "valid-case", "case.json")
    for case_id in ("..", ".", "../other", "/absolute"):
        with pytest.raises(guard.AuthoringQualityError):
            guard._case_relative("director", "teacher", case_id, "case.json")


def test_pipeline_changes_when_capability_contract_changes(tmp_path):
    path = tmp_path / "backend/modules/assistant/forecast/capabilities.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"version":1}')
    previous = guard.pipeline_fingerprint(tmp_path)
    path.write_text('{"version":2}')
    assert guard.pipeline_fingerprint(tmp_path) != previous


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        None,
        "database",
        "owner",
        "project_owner",
        "model",
        "unverified",
        "reasoning",
        "inactive",
    ],
)
async def test_actual_runtime_gate_releases_reads_and_checks_owner_and_luna(
    tmp_path, monkeypatch, change
):
    scope, _models = _fixture(tmp_path, monkeypatch)
    manifest = guard.AuthoringQualityManifest.model_validate(scope.manifest)
    snapshot = deepcopy(manifest.project_snapshot)
    if change in {"model", "unverified"}:
        snapshot["profile"].update(
            {"model": "gpt-6.1-sol"}
            if change == "model"
            else {"connection_verified": False}
        )
        manifest = manifest.model_copy(
            update={
                "project_snapshot": snapshot,
                "project_snapshot_sha256": guard.digest(snapshot),
            }
        )
    account_id = str(uuid4()) if change == "owner" else manifest.owner_id
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setattr(
        guard,
        "database_fingerprint",
        lambda: "0" * 64 if change == "database" else manifest.database_sha256,
    )
    monkeypatch.setattr("modules.account.facade.current_account_id", lambda: account_id)
    monkeypatch.setattr("modules.account.facade.require_account_active", AsyncMock())
    monkeypatch.setattr(
        "modules.project.facade.require_active_project",
        AsyncMock(side_effect=ValueError("inactive") if change == "inactive" else None),
    )
    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        AsyncMock(
            return_value={
                "llm": {
                    "extra": {
                        "reasoning_effort": "high" if change == "reasoning" else "max"
                    }
                }
            }
        ),
    )
    scope.db.scalar = AsyncMock(
        return_value=SimpleNamespace(
            id=manifest.project_id,
            owner_id=str(uuid4()) if change == "project_owner" else manifest.owner_id,
            project_kind="author",
            title=manifest.project_title,
        )
    )
    if change is None:
        await VERIFY_PROJECT_RUNTIME(scope.db, manifest)
    else:
        with pytest.raises(guard.AuthoringQualityError):
            await VERIFY_PROJECT_RUNTIME(scope.db, manifest)
    scope.db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_artifact_change_during_runtime_check_is_rejected_before_io(
    tmp_path, monkeypatch
):
    scope, models = _fixture(tmp_path, monkeypatch)
    prompt = _prompt(scope)
    path = (
        scope.private_root / "cases" / scope.domain / "seed" / "seed-v1" / "rubric.json"
    )

    async def verify(db, _manifest):
        await db.rollback()
        path.write_text(path.read_text() + " ")

    monkeypatch.setattr(guard, "verify_project_runtime", verify)
    with pytest.raises(guard.AuthoringQualityError, match="fingerprint drift"):
        await scope.authorize(
            prompt,
            models["seed"],
            guard.STEPS[(scope.domain, "seed")],
            _strict_json_schema(models["seed"].model_json_schema()),
        )
    assert not (scope.private_root / "request-journal.json").exists()


@pytest.mark.asyncio
async def test_seed_receipt_cannot_be_rebound_to_another_manifest(tmp_path, monkeypatch):
    scope, models = _fixture(tmp_path, monkeypatch)
    await _call(scope, models, monkeypatch)
    changed = {**scope.manifest, "project_title": "AUTHORING-QUALITY: changed binding"}
    _write(scope.private_root / "manifest.json", changed)
    with pytest.raises(guard.AuthoringQualityError, match="calibration has not passed"):
        guard._require_seed(scope.private_root, scope.domain)


def test_fifo_artifacts_and_locks_are_rejected_without_blocking(tmp_path, monkeypatch):
    scope, _models = _fixture(tmp_path, monkeypatch)
    manifest = scope.private_root / "manifest.json"
    manifest.unlink()
    os.mkfifo(manifest, mode=0o600)
    with pytest.raises(guard.AuthoringQualityError, match="regular"):
        guard._read_private_file(scope.private_root, "manifest.json")
    os.mkfifo(scope.private_root / ".authoring-quality.lock", mode=0o600)
    with pytest.raises(guard.AuthoringQualityError, match="regular"):
        with guard._journal_lock(scope.private_root):
            pytest.fail("FIFO acquired as a journal lock")
