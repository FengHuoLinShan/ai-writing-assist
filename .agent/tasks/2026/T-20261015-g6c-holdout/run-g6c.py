"""Explicit G6c holdout: frozen parent proofs, sealed arms and one material lease."""

import asyncio
import hashlib
import importlib.util
import json
import os
import random
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from core.config import get_settings
from core.database import DatabaseManager
from evals.ask_world import (
    _ASK_WORLD_SYSTEM_PROMPT,
    _ASK_WORLD_TEACHER_RUBRIC,
    _HOLDOUT_RUNS,
    _author_sources,
    _holdout_material_sha,
    evaluate_ask_world_model_cases,
    evaluate_ask_world_teacher_calibration,
    load_ask_world_cases,
)
from evals.codex_executor import AskWorldCalibrationScope, CodexStructuredExecutor
from modules.project.facade import open_project_llm_client
from modules.world.llm_schemas import GeneratedAskWorldOutput
from modules.world.schemas import AskWorldQuestionRequest
from modules.world.services.worldbuilding.ask_world_service import AskWorldService

PRIVATE = Path("/Users/tywww/.codex/private/g6c-holdout-20261015")
OLD = Path("/Users/tywww/.codex/private/g6b-recalibration-20261015")
ROOT = Path(__file__).resolve().parents[4]
CAPTURE = ROOT / ".agent/tasks/2026/T-20261015-g6b-recalibration/native-capture.py"
DATASET = PRIVATE / "holdout-v1.jsonl"
FREEZE_CONFIG = PRIVATE / "FREEZE_CONFIG.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def event(value):
    with (PRIVATE / "events.jsonl").open("a") as stream:
        stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), **value}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def verify_hashes(hashes):
    for name, expected in hashes.items():
        if sha(Path(name).read_bytes()) != expected:
            raise ValueError("Frozen source/evidence drift: " + name)


def lock(path, value):
    save(path, value)


def input_cases():
    cases = load_ask_world_cases(DATASET)
    assert len(cases) == 32 and len({c.scenario_id for c in cases}) == 32
    assert sum(c.should_answer for c in cases) == 16
    assert len({c.family for c in cases}) == 16
    assert all(c.split == "holdout" for c in cases)
    assert len({c.stratum for c in cases}) == 6
    for family in {c.family for c in cases}:
        pair = [c for c in cases if c.family == family]
        assert len(pair) == 2 and sum(c.should_answer for c in pair) == 1
    for case in cases:
        assert all(sha(s.content.encode()) == s.source_hash for s in case.sources)
        assert all(
            s.novel_id == case.novel_id and s.visibility == "author"
            for s in _author_sources(case)
        )
    return cases


def evidence_ready():
    teacher = read(OLD / "live/selftest-result.json")
    previous = read(OLD / "refusal-v1/result.json")
    executor = CodexStructuredExecutor(command=str(CAPTURE), attempts=1)
    assert (
        teacher["all_expected_matched"] and teacher["matched"] == teacher["total"] == 30
    )
    assert teacher["teacher"]["rubric_hash"] == sha(_ASK_WORLD_TEACHER_RUBRIC.encode())
    assert teacher["teacher"]["teacher_model"] == executor.model == "gpt-6.1-sol"
    assert (
        teacher["teacher"]["reasoning_effort"] == executor.reasoning_effort == "xhigh"
    )
    assert teacher["teacher"]["executor_hash"] == executor.meta.executor_hash
    assert all(previous["acceptance"].values())
    assert previous["summary"]["new_family"]["candidate"]["semantic_pass"] == 32
    parent = read(OLD / "refusal-v1/freeze.json")
    assert parent["prompt_hashes"]["candidate"] == sha(
        _ASK_WORLD_SYSTEM_PROMPT.encode()
    )
    for n in ("executor", "rubric", "evaluator", "capture", "setup"):
        assert previous["execution_freeze"][n] == runtime_hashes()[n]


def runtime_hashes():
    return {
        "runner": sha(Path(__file__).read_bytes()),
        "reporter": sha(Path(__file__).with_name("report-g6c.py").read_bytes()),
        "executor": sha((ROOT / "backend/evals/codex_executor.py").read_bytes()),
        "rubric": sha(_ASK_WORLD_TEACHER_RUBRIC.encode()),
        "evaluator": sha((ROOT / "backend/evals/ask_world.py").read_bytes()),
        "capture": sha(CAPTURE.read_bytes()),
        "setup": sha((OLD / "live/setup-result-final.json").read_bytes()),
        "candidate_prompt": sha(_ASK_WORLD_SYSTEM_PROMPT.encode()),
        "schema": sha(
            json.dumps(
                GeneratedAskWorldOutput.model_json_schema(), sort_keys=True
            ).encode()
        ),
    }


def sealed_baseline():
    spec = importlib.util.spec_from_file_location(
        "g6c_sealed_baseline", PRIVATE / "sources/baseline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prompts = read(PRIVATE / "prompts.json")
    assert module._ASK_WORLD_SYSTEM_PROMPT == prompts["baseline"]
    assert _ASK_WORLD_SYSTEM_PROMPT == prompts["candidate"]
    baseline = (PRIVATE / "sources/baseline.py").read_text()
    candidate = (
        ROOT / "backend/modules/world/services/worldbuilding/ask_world_service.py"
    ).read_text()
    assert baseline.replace(prompts["baseline"], prompts["candidate"], 1) == candidate
    return module.AskWorldService


def selfcheck():
    # Exercise drift rejection and exclusive leases before any live requests.
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "source"
        p.write_bytes(b"frozen")
        h = {str(p): sha(p.read_bytes())}
        verify_hashes(h)
        p.write_bytes(b"drift")
        try:
            verify_hashes(h)
        except ValueError:
            pass
        else:
            raise AssertionError("Source drift accepted")
        marker = Path(d) / "once"
        lock(marker, {})
        try:
            lock(marker, {})
        except FileExistsError:
            pass
        else:
            raise AssertionError("Holdout replay accepted")
    input_cases()
    evidence_ready()
    sealed_baseline()


async def deterministic(cases, generated):
    async def replay(case):
        return generated[case.scenario_id]

    return await evaluate_ask_world_model_cases(cases, replay)


async def main(stage):
    os.umask(0o077)
    assert stage in {"freeze", "run", "judge-0", "judge-1", "selfcheck"}
    assert get_settings().database_url.endswith(":65195/agent_e2e_g6b_calibration")
    assert os.environ["CODEX_CLI_COMMAND"] == str(CAPTURE)
    selfcheck()
    cases = input_cases()
    setup = read(OLD / "live/setup-result-final.json")
    manager = DatabaseManager()
    manager.init()
    try:
        async with manager.session_factory() as db:
            await AskWorldCalibrationScope(
                db, setup["project_id"], setup["snapshot"]
            ).verify()
        if stage == "selfcheck":
            print(
                "Offline invariants and current owner/Project Luna/max verified; no model calls"
            )
            return
        if stage == "freeze":
            files = [
                DATASET,
                PRIVATE / "reference-notes.json",
                PRIVATE / "PROTOCOL.json",
                PRIVATE / "prompts.json",
                *[p for p in (PRIVATE / "sources").rglob("*") if p.is_file()],
            ]
            files += [
                p
                for p in OLD.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            ]
            files += [
                p
                for p in (
                    ROOT / ".agent/tasks/2026/T-20261015-g6b-recalibration"
                ).rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            ]
            files += list((ROOT / "backend/infrastructure/llm").rglob("*.py"))
            files += [
                ROOT / "backend/evals/codex_executor.py",
                ROOT / "backend/evals/ask_world.py",
                ROOT
                / "backend/modules/world/services/worldbuilding/ask_world_service.py",
                Path(__file__),
                Path(__file__).with_name("report-g6c.py"),
            ]
            config = {
                "version": "g6c-holdout-v1",
                "created_at": datetime.now(UTC).isoformat(),
                "review_ready": True,
                "runtime": runtime_hashes(),
                "dataset_sha256": sha(DATASET.read_bytes()),
                "holdout_material_sha256": _holdout_material_sha(cases),
                "hashes": {str(p): sha(p.read_bytes()) for p in files},
                "parent_evidence": {
                    "selftest": "G6b live/selftest-result.json: 30/30",
                    "debug_review": "G6b refusal-v1/result.json: frozen candidate 32/32; original 33/34 preserved",
                },
                "protocol": read(PRIVATE / "PROTOCOL.json"),
                "snapshot": setup["snapshot"],
            }
            save(FREEZE_CONFIG, config)
            public = {
                k: v for k, v in config.items() if k not in {"snapshot", "hashes"}
            }
            public["file_sha256"] = config["hashes"]
            public["cases"] = [
                {
                    k: c.model_dump()[k]
                    for k in (
                        "scenario_id",
                        "family",
                        "stratum",
                        "should_answer",
                        "source_conflict",
                        "split",
                    )
                }
                for c in cases
            ]
            save(Path(__file__).parent / "artifacts/FREEZE_CONFIG.json", public)
            print(
                "FREEZE_CONFIG sealed; 16 new families / 32 holdout cases; 64 planned SUT calls + 2 teacher batches"
            )
            return
        frozen = read(FREEZE_CONFIG)
        verify_hashes(frozen["hashes"])
        assert runtime_hashes() == frozen["runtime"]
        assert setup["snapshot"] == frozen["snapshot"]
        before = {p.parent.name for p in (OLD / "live").glob("*/status.json")}
        lock(
            PRIVATE / f"{stage}.started.json",
            {
                "freeze_sha256": sha(FREEZE_CONFIG.read_bytes()),
                "at": datetime.now(UTC).isoformat(),
            },
        )
        if stage == "run":
            _HOLDOUT_RUNS.mkdir(parents=True, exist_ok=True)
            material = frozen["holdout_material_sha256"]
            lock(
                _HOLDOUT_RUNS / (material + ".json"),
                {
                    "dataset_sha256": frozen["dataset_sha256"],
                    "private_trial": str(PRIVATE),
                    "arms": ["baseline", "candidate"],
                },
            )
            # Per-case leases also prevent silently reusing subsets in a renamed corpus.
            for case in cases:
                case_hash = _holdout_material_sha([case])
                lock(
                    _HOLDOUT_RUNS / ("case-" + case_hash + ".json"), {"trial": material}
                )
            baseline_service = sealed_baseline()
            jobs = [(arm, c) for c in cases for arm in ("baseline", "candidate")]
            random.Random(frozen["protocol"]["random_seed"]).shuffle(jobs)
            save(
                PRIVATE / "request-intents.json",
                [
                    {"arm": arm, "scenario_id": c.scenario_id, "status": "planned"}
                    for arm, c in jobs
                ],
            )
            gate, stopped = asyncio.Semaphore(2), asyncio.Event()

            async def generate(arm, case):
                async with gate:
                    if stopped.is_set():
                        event(
                            {
                                "stage": stage,
                                "arm": arm,
                                "case": case.scenario_id,
                                "status": "not_started",
                            }
                        )
                        return
                    event(
                        {
                            "stage": stage,
                            "arm": arm,
                            "case": case.scenario_id,
                            "status": "pending",
                        }
                    )
                    try:
                        async with manager.session_factory() as db:
                            await AskWorldCalibrationScope(
                                db, setup["project_id"], setup["snapshot"]
                            ).verify()
                            async with open_project_llm_client(
                                db, setup["project_id"], timeout_override=900
                            ) as client:
                                assert client.model_name == "gpt-6-luna"
                                await db.rollback()
                                service = (
                                    baseline_service()
                                    if arm == "baseline"
                                    else AskWorldService()
                                )
                                output = await service._generate(
                                    client,
                                    AskWorldQuestionRequest(
                                        novel_id=setup["project_id"],
                                        question=case.question,
                                    ),
                                    [
                                        s.model_dump(mode="json")
                                        for s in _author_sources(case)
                                    ],
                                    model=client.model_name,
                                )
                        save(
                            PRIVATE / f"{arm}-{case.scenario_id}.json",
                            output.model_dump(mode="json"),
                        )
                        event(
                            {
                                "stage": stage,
                                "arm": arm,
                                "case": case.scenario_id,
                                "status": "generated",
                            }
                        )
                        print(arm, case.scenario_id, "generated", flush=True)
                    except BaseException as exc:
                        stopped.set()
                        event(
                            {
                                "stage": stage,
                                "arm": arm,
                                "case": case.scenario_id,
                                "status": "incomplete",
                                "error_type": type(exc).__name__,
                            }
                        )
                        raise

            outcomes = await asyncio.gather(
                *(generate(a, c) for a, c in jobs), return_exceptions=True
            )
            if any(isinstance(r, BaseException) for r in outcomes):
                raise RuntimeError(
                    "Incomplete holdout; preserve attempts/unknown; do not replay"
                )
            assert all(
                (PRIVATE / f"{a}-{c.scenario_id}.json").exists() for a, c in jobs
            )
        else:
            assert (PRIVATE / "run.complete.json").exists()
            batch = int(stage[-1])
            families = sorted({c.family for c in cases})
            random.Random(617).shuffle(families)
            selected = set(families[batch * 8 : (batch + 1) * 8])
            jobs = [
                (a, c)
                for c in cases
                if c.family in selected
                for a in ("baseline", "candidate")
            ]
            random.Random(619 + batch).shuffle(jobs)
            mapping, blinded, outputs = {}, [], {}
            for i, (arm, case) in enumerate(jobs):
                key = f"ask-g6c-blind-{batch}-{i:03d}"
                mapping[key] = {"arm": arm, "scenario_id": case.scenario_id}
                blinded.append(case.model_copy(update={"scenario_id": key}))
                outputs[key] = GeneratedAskWorldOutput.model_validate(
                    read(PRIVATE / f"{arm}-{case.scenario_id}.json")
                )
            assert len(blinded) == 32
            save(PRIVATE / f"{stage}-mapping.json", mapping)
            d = await deterministic(blinded, outputs)
            save(PRIVATE / f"{stage}-deterministic.json", d)
            async with manager.session_factory() as db:
                executor = CodexStructuredExecutor(
                    command=str(CAPTURE),
                    timeout_seconds=1200,
                    attempts=1,
                    calibration=AskWorldCalibrationScope(
                        db, setup["project_id"], setup["snapshot"]
                    ),
                )
                judged = await evaluate_ask_world_teacher_calibration(
                    blinded, outputs, d["case_results"], executor
                )
            save(PRIVATE / f"{stage}-result.json", judged)
            print(stage, json.dumps(judged["metrics"]), flush=True)
        event({"stage": stage, "status": "complete"})
        save(
            PRIVATE / f"{stage}.complete.json",
            {
                "new_native_calls": sorted(
                    {p.parent.name for p in (OLD / "live").glob("*/status.json")}
                    - before
                )
            },
        )
    except BaseException as exc:
        event(
            {"stage": stage, "status": "incomplete", "error_type": type(exc).__name__}
        )
        raise
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
