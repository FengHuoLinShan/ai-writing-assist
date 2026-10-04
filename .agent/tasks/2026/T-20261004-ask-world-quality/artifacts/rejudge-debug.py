"""Re-score the saved 28 synthetic generations; no DeepSeek or database access."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from evals.ask_world import (
    ASK_WORLD_TEACHER_MODEL,
    ASK_WORLD_TEACHER_REASONING_EFFORT,
    evaluate_ask_world_model_cases,
    evaluate_ask_world_teacher_calibration,
    load_ask_world_cases,
)
from evals.codex_executor import CodexStructuredExecutor
from modules.world.llm_schemas import GeneratedAskWorldOutput


async def main():
    artifact = Path("../.agent/tasks/2026/T-20261004-ask-world-quality/artifacts")
    source = artifact / "deepseek-debug-ledger.jsonl"
    old_dataset = Path("evals/datasets/baselines/ask-world-model-probes-v2.jsonl")
    dataset = old_dataset.with_name("ask-world-model-probes-v3.jsonl")
    expected_hash = hashlib.sha256(old_dataset.read_bytes()).hexdigest()
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    if len({row["scenario_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate ledger scenario")
    if any(row["dataset_sha256"] != expected_hash for row in rows):
        raise ValueError("Ledger is not bound to the archived v2 dataset")
    generated = {
        row["scenario_id"]: GeneratedAskWorldOutput.model_validate(row["generated"])
        for row in rows
    }
    original = {case.scenario_id: case for case in load_ask_world_cases(old_dataset)}
    debug = [case for case in load_ask_world_cases(dataset) if case.split == "debug"]
    selected = [case for case in debug if case.scenario_id in generated]
    if len(selected) != len(rows):
        raise ValueError("Ledger includes a non-debug or unknown scenario")
    for case in selected:
        before = original[case.scenario_id]
        if case.question != before.question or case.sources != before.sources:
            raise ValueError("Cannot replay generations against changed input evidence")

    async def generate(case):
        return generated[case.scenario_id]

    report = await evaluate_ask_world_model_cases(selected, generate)
    teacher = await evaluate_ask_world_teacher_calibration(
        selected,
        generated,
        report["case_results"],
        CodexStructuredExecutor(
            model=ASK_WORLD_TEACHER_MODEL,
            reasoning_effort=ASK_WORLD_TEACHER_REASONING_EFFORT,
            allowed_models=frozenset({ASK_WORLD_TEACHER_MODEL}),
            timeout_seconds=1200,
        ),
    )
    report["semantic_review"] = teacher.pop("semantic_review")
    report["teacher_calibration"] = teacher
    report.update(
        quality_scope="debug_generation_replay_with_revised_rubric",
        split="debug-replay",
        dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
        generation_dataset_sha256=expected_hash,
        generation_ledger_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        debug_generation_coverage={
            "available": len(selected),
            "required": len(debug),
            "missing_scenarios": sorted(
                case.scenario_id for case in debug if case.scenario_id not in generated
            ),
        },
        reference_correction={
            "ask-probe-archive-stale": "custodian and location are complementary"
        },
        human_validated=False,
    )
    Path(sys.argv[1]).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print("saved debug re-review; full v3 generation coverage remains explicit")


if __name__ == "__main__":
    asyncio.run(main())
