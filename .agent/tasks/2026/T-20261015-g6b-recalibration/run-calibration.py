"""G6b Ask World calibration; explicit stages, private receipts, no holdout."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from core.config import get_settings
from core.database import DatabaseManager
from evals.ask_world import (
    _ASK_WORLD_SYSTEM_PROMPT,
    _ASK_WORLD_TEACHER_RUBRIC,
    AskWorldEvalCase,
    _author_sources,
    _code_provenance,
    evaluate_ask_world_model_cases,
    evaluate_ask_world_teacher_calibration,
    load_ask_world_cases,
)
from evals.codex_executor import AskWorldCalibrationScope, CodexStructuredExecutor
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    open_project_llm_client,
)
from modules.world.llm_schemas import GeneratedAskWorldOutput
from modules.world.schemas import AskWorldQuestionRequest
from modules.world.services.worldbuilding.ask_world_service import AskWorldService

PRIVATE = Path("/Users/tywww/.codex/private/g6b-recalibration-20261015/live")
DATASET = Path("evals/datasets/baselines/ask-world-model-probes-v3.jsonl")
CAPTURE = Path(__file__).with_name("native-capture.py").resolve()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    with (PRIVATE / name).open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def event(value):
    with (PRIVATE / "stage-ledger.jsonl").open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read(name):
    return json.loads((PRIVATE / name).read_text())


async def teacher(db, setup, cases, generated, deterministic):
    executor = CodexStructuredExecutor(
        command=str(CAPTURE),
        timeout_seconds=1200,
        attempts=1,
        calibration=AskWorldCalibrationScope(db, setup["project_id"], setup["snapshot"]),
    )
    result = await evaluate_ask_world_teacher_calibration(
        cases, generated, deterministic["case_results"], executor
    )
    return result


async def main(stage):
    os.umask(0o077)
    assert stage in {"selftest", "debug", "score"}
    assert get_settings().database_url.endswith(":65195/agent_e2e_g6b_calibration")
    assert os.environ["CODEX_CLI_COMMAND"] == str(CAPTURE)
    setup = read("setup-result.json")
    assert setup["status"] == "verified" and setup["effective_reasoning_effort"] == "max"
    expected_hashes = {
        "dataset": digest(DATASET.read_bytes()),
        "rubric": digest(_ASK_WORLD_TEACHER_RUBRIC.encode()),
        "system_prompt": digest(_ASK_WORLD_SYSTEM_PROMPT.encode()),
        "runner": digest(Path(__file__).read_bytes()),
        "executor": digest(Path("evals/codex_executor.py").read_bytes()),
        "capture": digest(CAPTURE.read_bytes()),
        "seeded": digest((PRIVATE / "seeded-input.json").read_bytes()),
    }
    freeze = PRIVATE / "run-freeze.json"
    if freeze.exists():
        assert read("run-freeze.json")["hashes"] == expected_hashes, (
            "Frozen G6b source drift"
        )
    else:
        assert stage == "selftest"
        save(
            "run-freeze.json",
            {
                "hashes": expected_hashes,
                "provenance": _code_provenance(),
                "teacher": "gpt-6.1-sol/xhigh",
                "sut": "gpt-6-luna/max",
            },
        )
    # Exclusive markers survive interruption and prevent accidental request replay.
    with (PRIVATE / f"{stage}.started").open("x") as marker:
        marker.write(json.dumps(expected_hashes))
        marker.flush()
        os.fsync(marker.fileno())
    event({"stage": stage, "status": "started"})
    manager = DatabaseManager()
    manager.init()
    try:
        async with manager.session_factory() as db:
            scope = AskWorldCalibrationScope(db, setup["project_id"], setup["snapshot"])
            await scope.verify()
            if stage == "selftest":
                fixture = read("seeded-input.json")
                cases = [AskWorldEvalCase.model_validate(c) for c in fixture["cases"]]
                assert len(cases) == 30 and all(c.split == "debug" for c in cases)
                generated = {
                    k: GeneratedAskWorldOutput.model_validate(v)
                    for k, v in fixture["generated"].items()
                }

                async def seeded(case):
                    return generated[case.scenario_id]

                deterministic = await evaluate_ask_world_model_cases(cases, seeded)
                judged = await teacher(db, setup, cases, generated, deterministic)
                decisions = {c["scenario_id"]: c for c in judged["case_results"]}
                rows = []
                for scenario, expected in fixture["labels"].items():
                    decision = decisions[scenario]
                    matched = (
                        decision["reference_verdict"] == "needs_edit"
                        if expected["label"] == "ref_wrong"
                        else decision["reference_verdict"] == "accept"
                        and decision["model_verdict"] == expected["label"]
                    )
                    rows.append(
                        {
                            "scenario_id": scenario,
                            "expected": expected,
                            "matched": matched,
                            "decision": decision,
                        }
                    )
                result = {
                    "matched": sum(row["matched"] for row in rows),
                    "total": len(rows),
                    "all_expected_matched": all(row["matched"] for row in rows),
                    "teacher": judged,
                    "rows": rows,
                    "human_validated": False,
                }
                save("selftest-result.json", result)
                print(
                    "teacher selftest",
                    result["matched"],
                    "/",
                    result["total"],
                    flush=True,
                )
                if not result["all_expected_matched"]:
                    raise RuntimeError(
                        "Teacher calibration mismatch; inspect original evidence"
                    )
            elif stage == "debug":
                assert read("selftest-result.json")["all_expected_matched"]
                cases = [c for c in load_ask_world_cases(DATASET) if c.split == "debug"]
                assert len(cases) == 34
                current = await build_project_llm_execution_snapshot(
                    db, setup["project_id"]
                )
                assert current == setup["snapshot"]
                async with open_project_llm_client(
                    db, setup["project_id"], timeout_override=900
                ) as client:
                    await db.commit()
                    gate = asyncio.Semaphore(2)
                    stopped = asyncio.Event()
                    generated = {}

                    async def generate(case):
                        async with gate:
                            if stopped.is_set():
                                return
                            event(
                                {
                                    "stage": stage,
                                    "case": case.scenario_id,
                                    "status": "pending",
                                }
                            )
                            try:
                                output = await AskWorldService()._generate(
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
                                generated[case.scenario_id] = output
                                event(
                                    {
                                        "stage": stage,
                                        "case": case.scenario_id,
                                        "status": "generated",
                                        "output": output.model_dump(mode="json"),
                                    }
                                )
                                save(
                                    "debug-generated.json",
                                    {
                                        k: v.model_dump(mode="json")
                                        for k, v in generated.items()
                                    },
                                )
                                print(
                                    "debug generated",
                                    len(generated),
                                    "/",
                                    len(cases),
                                    flush=True,
                                )
                            except BaseException as exc:
                                stopped.set()
                                event(
                                    {
                                        "stage": stage,
                                        "case": case.scenario_id,
                                        "status": "incomplete",
                                        "error_type": type(exc).__name__,
                                        "error": str(exc),
                                    }
                                )
                                raise

                    outcomes = await asyncio.gather(
                        *(generate(c) for c in cases), return_exceptions=True
                    )
                    if any(isinstance(r, BaseException) for r in outcomes) or len(
                        generated
                    ) != len(cases):
                        raise RuntimeError(
                            "Debug incomplete; preserve pending/unknown, do not replay"
                        )

                async def replay(case):
                    return generated[case.scenario_id]

                deterministic = await evaluate_ask_world_model_cases(cases, replay)
                save("debug-deterministic.json", deterministic)
            else:
                assert read("selftest-result.json")["all_expected_matched"]
                cases = [c for c in load_ask_world_cases(DATASET) if c.split == "debug"]
                generated = {
                    k: GeneratedAskWorldOutput.model_validate(v)
                    for k, v in read("debug-generated.json").items()
                }
                assert set(generated) == {c.scenario_id for c in cases}
                deterministic = read("debug-deterministic.json")
                judged = await teacher(db, setup, cases, generated, deterministic)
                save("debug-teacher.json", judged)
                print(
                    "debug teacher metrics",
                    json.dumps(judged["metrics"], ensure_ascii=False),
                    flush=True,
                )
        event({"stage": stage, "status": "complete"})
    except BaseException as exc:
        event(
            {
                "stage": stage,
                "status": "incomplete",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        raise
    finally:
        await manager.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
