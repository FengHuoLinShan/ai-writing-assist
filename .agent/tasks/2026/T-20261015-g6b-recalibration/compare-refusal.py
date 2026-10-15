"""Frozen paired G6b development comparison; raw artifacts remain private."""

import asyncio
import hashlib
import json
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from core.config import get_settings
from core.database import DatabaseManager
from evals.ask_world import (
    _ASK_WORLD_SYSTEM_PROMPT,
    _ASK_WORLD_TEACHER_RUBRIC,
    AskWorldEvalCase,
    _author_sources,
    evaluate_ask_world_model_cases,
    evaluate_ask_world_teacher_calibration,
)
from evals.codex_executor import AskWorldCalibrationScope, CodexStructuredExecutor
from modules.project.facade import open_project_llm_client
from modules.world.llm_schemas import GeneratedAskWorldOutput
from modules.world.schemas import AskWorldQuestionRequest
from modules.world.services.worldbuilding.ask_world_service import AskWorldService

PRIVATE = Path("/Users/tywww/.codex/private/g6b-recalibration-20261015/refusal-v1")
LIVE = PRIVATE.parent / "live"
CAPTURE = Path(__file__).with_name("native-capture.py").resolve()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    return json.loads((PRIVATE / name).read_text())


def save(name, value):
    with (PRIVATE / name).open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())


def event(value):
    with (PRIVATE / "events.jsonl").open("a") as stream:
        stream.write(
            json.dumps(
                {"at": datetime.now(UTC).isoformat(), **value}, ensure_ascii=False
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def frozen_inputs():
    freeze = read("freeze.json")
    for name, expected in freeze["hashes"].items():
        assert sha((PRIVATE / name).read_bytes()) == expected, name
    for name, expected in freeze["old_protected"].items():
        assert sha(Path(name).read_bytes()) == expected, name
    fixture = read("cases.json")
    cases = [AskWorldEvalCase.model_validate(c) for c in fixture["new"]]
    original = AskWorldEvalCase.model_validate(fixture["original_failure"])
    assert len(cases) == 16 and sum(c.should_answer for c in cases) == 8
    return cases + [original]


async def deterministic(cases, outputs):
    async def replay(case):
        return outputs[case.scenario_id]

    return await evaluate_ask_world_model_cases(cases, replay)


async def main(stage):
    os.umask(0o077)
    assert stage in {"check", "baseline", "candidate", "judge-0", "judge-1"}
    cases = frozen_inputs()
    assert get_settings().database_url.endswith(":65195/agent_e2e_g6b_calibration")
    assert os.environ["CODEX_CLI_COMMAND"] == str(CAPTURE)
    setup = json.loads((LIVE / "setup-result-final.json").read_text())
    runtime = {
        "runner": sha(Path(__file__).read_bytes()),
        "executor": sha(Path("evals/codex_executor.py").read_bytes()),
        "rubric": sha(_ASK_WORLD_TEACHER_RUBRIC.encode()),
        "evaluator": sha(Path("evals/ask_world.py").read_bytes()),
        "capture": sha(CAPTURE.read_bytes()),
        "setup": sha((LIVE / "setup-result-final.json").read_bytes()),
    }
    if stage == "check":
        save("execution-freeze.json", runtime)
    else:
        assert runtime == read("execution-freeze.json"), "Runtime drift"
    if stage in {"baseline", "candidate"}:
        assert _ASK_WORLD_SYSTEM_PROMPT == read("prompts.json")[stage], "Prompt drift"
    before_calls = {p.parent.name for p in LIVE.glob("*/status.json")}
    save(
        stage + ".started.json",
        {
            "stage": stage,
            "runtime": runtime,
            "prompt_sha256": sha(_ASK_WORLD_SYSTEM_PROMPT.encode()),
        },
    )
    manager = DatabaseManager()
    manager.init()
    try:
        async with manager.session_factory() as db:
            await AskWorldCalibrationScope(
                db, setup["project_id"], setup["snapshot"]
            ).verify()
        if stage == "check":
            print(
                "Verified current owner/Project snapshot: Codex gpt-6-luna/max",
                flush=True,
            )
        elif stage in {"baseline", "candidate"}:
            gate = asyncio.Semaphore(2)
            stopped = asyncio.Event()

            async def generate(case, repetition):
                async with gate:
                    if stopped.is_set():
                        return
                    key = f"{stage}-r{repetition}-{case.scenario_id}"
                    event({"stage": stage, "key": key, "status": "pending"})
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
                        save(key + ".json", output.model_dump(mode="json"))
                        event({"stage": stage, "key": key, "status": "generated"})
                        print(key, "generated", flush=True)
                    except BaseException as exc:
                        stopped.set()
                        event(
                            {
                                "stage": stage,
                                "key": key,
                                "status": "incomplete",
                                "error_type": type(exc).__name__,
                            }
                        )
                        raise

            jobs = [(c, r) for r in range(2) for c in cases]
            random.Random(20261015).shuffle(jobs)
            outcomes = await asyncio.gather(
                *(generate(c, r) for c, r in jobs), return_exceptions=True
            )
            if any(isinstance(o, BaseException) for o in outcomes):
                raise RuntimeError(
                    "Comparison incomplete; preserve pending/unknown; no replay"
                )
            assert all(
                (PRIVATE / f"{stage}-r{r}-{c.scenario_id}.json").exists()
                for c, r in jobs
            )
        else:
            repetition = int(stage[-1])
            jobs = [(arm, c) for arm in ("baseline", "candidate") for c in cases]
            random.Random(20261015 + repetition).shuffle(jobs)
            blinded, outputs, mapping = [], {}, {}
            for index, (arm, case) in enumerate(jobs):
                key = f"ask-blind-{repetition}-{index:03d}"
                blinded.append(case.model_copy(update={"scenario_id": key}))
                outputs[key] = GeneratedAskWorldOutput.model_validate(
                    read(f"{arm}-r{repetition}-{case.scenario_id}.json")
                )
                mapping[key] = {
                    "arm": arm,
                    "repetition": repetition,
                    "scenario_id": case.scenario_id,
                }
            save(stage + "-mapping.json", mapping)
            result = await deterministic(blinded, outputs)
            save(stage + "-deterministic.json", result)
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
                    blinded, outputs, result["case_results"], executor
                )
            save(stage + "-result.json", judged)
            print(stage, json.dumps(judged["metrics"]), flush=True)
        event({"stage": stage, "status": "complete"})
        save(
            stage + ".complete.json",
            {
                "new_native_calls": sorted(
                    {p.parent.name for p in LIVE.glob("*/status.json")} - before_calls
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
