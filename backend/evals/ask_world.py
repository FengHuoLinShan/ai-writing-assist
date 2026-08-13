"""Deterministic launch gate for the author-only Ask World evidence contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.metrics import precision_at_k
from modules.context.services.author_question_evidence import (
    compile_author_question_evidence,
)
from modules.world.services.worldbuilding.ask_world_retrieval import (
    MIN_RELEVANCE,
    ask_world_relevance,
)

DEFAULT_DATASET = (
    Path(__file__).resolve().parent / "datasets" / "baselines" / "ask-world-v1.jsonl"
)
THRESHOLDS: dict[str, tuple[Literal["eq", "gte", "lte"], float]] = {
    "source_hash_validity": ("eq", 1.0),
    "citation_open_rate": ("eq", 1.0),
    "p_at_5": ("gte", 0.8),
    "no_answer_false_positive_rate": ("lte", 0.05),
}


class AskWorldEvalSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1)
    kind: Literal["world_bible_page", "world_object", "manuscript"]
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    novel_id: str = Field(min_length=1)
    visibility: Literal["author", "reader", "role"]
    openable: bool
    open_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AskWorldEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^ask-[a-z0-9-]+$")
    novel_id: str = Field(min_length=1)
    question: str = Field(min_length=2)
    should_answer: bool
    relevant_source_keys: list[str]
    sources: list[AskWorldEvalSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_expected_answer(self) -> AskWorldEvalCase:
        if self.should_answer != bool(self.relevant_source_keys):
            raise ValueError("answerable cases require relevant_source_keys")
        if len({item.key for item in self.sources}) != len(self.sources):
            raise ValueError("source keys must be unique within a case")
        return self


def load_ask_world_cases(path: Path = DEFAULT_DATASET) -> list[AskWorldEvalCase]:
    cases: list[AskWorldEvalCase] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            cases.append(AskWorldEvalCase.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"invalid Ask World eval line {line_number}: {exc}") from exc
    return cases


def _passes(value: float, gate: tuple[str, float]) -> bool:
    operation, threshold = gate
    if operation == "eq":
        return value == threshold
    if operation == "gte":
        return value >= threshold
    return value <= threshold


def run_ask_world_eval(path: Path = DEFAULT_DATASET) -> dict[str, Any]:
    cases = load_ask_world_cases(path)
    failures: list[str] = []
    if len({case.scenario_id for case in cases}) != len(cases):
        failures.append("duplicate_scenario_id")
    answerable = [case for case in cases if case.should_answer]
    no_answer = [case for case in cases if not case.should_answer]
    if not answerable:
        failures.append("metric_unavailable:p_at_5")
    if not no_answer:
        failures.append("metric_unavailable:no_answer_false_positive_rate")

    precisions: list[float] = []
    false_answers = 0
    eligible_sources = 0
    valid_hashes = 0
    opened_citations = 0
    citations = 0
    case_results: list[dict[str, Any]] = []
    for case in cases:
        eligible = [
            source
            for source in case.sources
            if source.novel_id == case.novel_id and source.visibility == "author"
        ]
        valid_hashes += sum(
            source.source_hash
            == hashlib.sha256(source.content.encode("utf-8")).hexdigest()
            for source in eligible
        )
        eligible_sources += len(eligible)
        ranked: list[tuple[AskWorldEvalSource, float]] = []
        for source in eligible:
            score = ask_world_relevance(case.question, source.title, source.content)
            if score >= MIN_RELEVANCE:
                ranked.append((source, score))
        ranked.sort(key=lambda item: (-item[1], item[0].key))
        packet = compile_author_question_evidence(
            [
                {
                    "key": source.key,
                    "kind": source.kind,
                    "title": source.title,
                    "content": source.content,
                    "source_hash": source.source_hash,
                    "score": score,
                }
                for source, score in ranked
            ]
        )
        retrieved = [item["key"] for item in packet["included"]]
        by_key = {source.key: source for source in case.sources}
        citations += len(retrieved)
        opened_citations += sum(
            by_key[key].openable and by_key[key].open_hash == by_key[key].source_hash
            for key in retrieved
        )
        if case.should_answer:
            precisions.append(
                precision_at_k(retrieved, set(case.relevant_source_keys), 5)
            )
        elif retrieved:
            false_answers += 1
        case_results.append(
            {
                "scenario_id": case.scenario_id,
                "retrieved_source_keys": retrieved,
                "answered": bool(retrieved),
            }
        )

    values: dict[str, float | None] = {
        "source_hash_validity": (
            valid_hashes / eligible_sources if eligible_sources else None
        ),
        "citation_open_rate": opened_citations / citations if citations else None,
        "p_at_5": fmean(precisions) if precisions else None,
        "no_answer_false_positive_rate": (
            false_answers / len(no_answer) if no_answer else None
        ),
    }
    for name, gate in THRESHOLDS.items():
        value = values[name]
        if value is None:
            failures.append(f"metric_unavailable:{name}")
        elif not _passes(value, gate):
            failures.append(f"metric_failed:{name}")

    return {
        "dataset": path.name,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "quality_scope": "offline_evidence_ranking_and_dataset_integrity",
        "ready": not failures,
        "case_count": len(cases),
        "metrics": values,
        "thresholds": {
            name: {"operation": gate[0], "value": gate[1]}
            for name, gate in THRESHOLDS.items()
        },
        "case_results": case_results,
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.ask_world")
    parser.add_argument("dataset", type=Path, nargs="?", default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_ask_world_eval(args.dataset)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(args.output)
    else:
        print(text, end="")
    if not report["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
