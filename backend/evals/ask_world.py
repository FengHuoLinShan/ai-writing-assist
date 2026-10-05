"""Deterministic launch gate for the author-only Ask World evidence contract."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Awaitable, Callable
from pathlib import Path
from statistics import fmean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.metrics import precision_at_k
from modules.evidence.compilation.services.author_question_evidence import (
    compile_author_question_evidence,
)
from modules.world.llm_schemas import GeneratedAskWorldOutput
from modules.world.schemas import AskWorldQuestionRequest
from modules.world.services.worldbuilding.ask_world_retrieval import (
    MIN_RELEVANCE,
    ask_world_relevance,
)
from modules.world.services.worldbuilding.ask_world_service import (
    _ASK_WORLD_SYSTEM_PROMPT,
    AskWorldService,
)

DEFAULT_DATASET = (
    Path(__file__).resolve().parent / "datasets" / "baselines" / "ask-world-v1.jsonl"
)
MODEL_PROBE_DATASET = DEFAULT_DATASET.parent / "ask-world-model-probes-v1.jsonl"
ASK_WORLD_TEACHER_MODEL = "gpt-6.1-sol"
ASK_WORLD_TEACHER_REASONING_EFFORT = "high"
_HOLDOUT_RUNS = Path(__file__).resolve().parent / ".cache" / "ask-world-holdouts"
_ASK_WORLD_TEACHER_RUBRIC = """\
你是 Ask World 模型质量的替代教师，不是真人评审。只能依据每个 case 提供的问题、来源证据、
预期 answerability 和被评模型输出判断，不得使用外部知识。

先审参考标签：若 should_answer 与证据边界一致则 reference_verdict=accept；参考本身错误或
会奖励幻觉时 needs_edit；无法可靠裁定时 ambiguous。精确数量、日期、身份或因果没有被
证据直接提供时应拒答，即使证据提到相关主体或明确表示未知。互相冲突的来源允许回答，但必须并列呈现并
保留不确定性，不能替作者选择正典。

再逐条审模型输出。model_output.claims 带 claim_index，每条都要返回一次审查；拒答 case 的
claims 返回空数组：
- supported：该主张被它引用的来源直接支持。引用与主张不对应（如引用了别的事实的来源）、
  数量/日期/身份/地点/原因与来源不符，或需要常识补全时为 false。
- attribute_matched：该主张直接回答所问属性，或是同一主体/条件下有助理解答案的简短背景。
  例如问雨季举办原因，补充有来源的雨季起止日期可通过；问南桥长度，补充同源的桥面材料可通过。
  无关主体/属性、把“未知”包装成已知、用背景替代所问属性为 false；所有补充也须 supported。
再审整体：
- answerability_justified：作答或拒答与证据边界一致；作答须覆盖问题所问的全部具体属性，
  不能只有补充背景。拒答不可否认证据已明确提供的答案。
- answer_consistent：answer 中的作品事实须被 claims 支持且不与 claims 矛盾。
  uncertainty 可说明证据确实未给出的范围或限定，不必为这种证据范围说明新增作品事实主张；
  但不得否认来源标题、正文或 claims 已提供的信息。“旧版/新版”“修订”提供版本关系，
  不证明哪版为正典；可以说正典未定，不可以说没有版本信息。
  “从甲到乙需要两天”已提供该方向的到达用时，不得称单程还是往返不明；
  若证据未给行走/休息安排，可仅说明这一限定未给。泛泛免责声明不是保守表述的免责理由。
- conflict_presented：仅当 reference.source_conflict 为 true 时填写。所有冲突版本
  都被并列呈现且保留不确定性为 true；只呈现一版、泛泛写“存在不确定”或替作者选版
  为 false；其他 case 填 null。
保管机构与存放地点是不同属性，可同时成立，不因出现两个来源或旧/新标题就视为冲突。
model_verdict 仅在以上各项全部通过时为 pass，否则 fail；证据或输出无法判断时 ambiguous。
每个 scenario_id 恰好返回一次，reason 用简短中文给出证据化理由。"""
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


AskWorldStratum = Literal[
    "single_source",
    "multi_source",
    "conflict",
    "near_miss",
    "scope_excluded",
    "injection_distractor",
]


class AskWorldEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^ask-[a-z0-9-]+$")
    novel_id: str = Field(min_length=1)
    question: str = Field(min_length=2)
    should_answer: bool
    relevant_source_keys: list[str]
    # True only when the relevant sources disagree; several complementary
    # sources are not a conflict.
    source_conflict: bool = False
    sources: list[AskWorldEvalSource] = Field(min_length=1)
    # Optional dataset design labels. Cases sharing source material share a family,
    # and a family never spans the debug and holdout splits.
    stratum: AskWorldStratum | None = None
    family: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$")
    split: Literal["debug", "holdout"] | None = None

    @model_validator(mode="after")
    def validate_expected_answer(self) -> AskWorldEvalCase:
        if self.should_answer != bool(self.relevant_source_keys):
            raise ValueError("answerable cases require relevant_source_keys")
        if len({item.key for item in self.sources}) != len(self.sources):
            raise ValueError("source keys must be unique within a case")
        if self.source_conflict and len(self.relevant_source_keys) < 2:
            raise ValueError("source conflicts require at least two relevant sources")
        if self.split is not None and self.family is None:
            raise ValueError("split cases require a source family")
        eligible_keys = {
            item.key
            for item in self.sources
            if item.novel_id == self.novel_id and item.visibility == "author"
        }
        if not set(self.relevant_source_keys) <= eligible_keys:
            raise ValueError("relevant sources must be author-visible case sources")
        return self


class AskWorldClaimReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_index: int = Field(ge=0)
    supported: bool
    attribute_matched: bool


class AskWorldTeacherDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^ask-[a-z0-9-]+$")
    reference_verdict: Literal["accept", "needs_edit", "ambiguous"]
    model_verdict: Literal["pass", "fail", "ambiguous"]
    answerability_justified: bool
    claims: list[AskWorldClaimReview]
    answer_consistent: bool
    conflict_presented: bool | None
    reason: str = Field(min_length=1, max_length=1000)


class AskWorldTeacherOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[AskWorldTeacherDecision] = Field(min_length=1)


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


ModelProbeGenerateFn = Callable[[AskWorldEvalCase], Awaitable[GeneratedAskWorldOutput]]
_SEMANTIC_DECIDED = frozenset({"pass", "fail"})
_SEMANTIC_REVIEWED = _SEMANTIC_DECIDED | {"ambiguous", "reference_disputed"}


def _author_sources(case: AskWorldEvalCase) -> list[AskWorldEvalSource]:
    return [
        source
        for source in case.sources
        if source.novel_id == case.novel_id and source.visibility == "author"
    ]


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _by_stratum(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[bool]] = {}
    for result in case_results:
        if result["stratum"] is not None:
            groups.setdefault(result["stratum"], []).append(
                result["deterministic_passed"]
            )
    return {
        name: {"case_count": len(passed), "deterministic_passed": sum(passed)}
        for name, passed in sorted(groups.items())
    }


def _semantic_unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


async def evaluate_ask_world_model_cases(
    cases: list[AskWorldEvalCase],
    generate: ModelProbeGenerateFn,
) -> dict[str, Any]:
    """Score answerability and cited source sets without creating a release gate.

    Citation precision/recall only say which sources were cited. They do not show
    that a claim is faithful to them; that needs the independent semantic review.
    """

    if not cases:
        raise ValueError("Ask World model probe dataset is empty")
    if any(
        source.source_hash != hashlib.sha256(source.content.encode("utf-8")).hexdigest()
        for case in cases
        for source in _author_sources(case)
    ):
        raise ValueError("Ask World model probe source hash mismatch")

    answerability_matches = 0
    no_answer_matches = 0
    no_answer_count = 0
    citation_precisions: list[float] = []
    citation_recalls: list[float] = []
    conflict_pair_matches = 0
    conflict_pair_count = 0
    passed_cases = 0
    case_results: list[dict[str, Any]] = []
    failure: dict[str, str] | None = None

    for case in cases:
        try:
            generated = await generate(case)
        except Exception as exc:
            failure = {"scenario_id": case.scenario_id, "error_type": type(exc).__name__}
            break
        cited = {key for claim in generated.claims for key in claim.citation_keys}
        relevant = set(case.relevant_source_keys)
        predicted_answer = not generated.no_answer
        answerability_match = predicted_answer == case.should_answer
        answerability_matches += answerability_match

        citation_precision: float | None = None
        citation_recall: float | None = None
        conflict_pair_match: bool | None = None
        if case.should_answer:
            citation_precision = len(cited & relevant) / len(cited) if cited else 0.0
            citation_recall = len(cited & relevant) / len(relevant)
            citation_precisions.append(citation_precision)
            citation_recalls.append(citation_recall)
            if case.source_conflict:
                conflict_pair_count += 1
                conflict_pair_match = relevant <= cited and bool(
                    generated.uncertainty.strip()
                )
                conflict_pair_matches += conflict_pair_match
            case_passed = bool(
                answerability_match
                and citation_precision == 1.0
                and citation_recall == 1.0
                and conflict_pair_match is not False
            )
        else:
            no_answer_count += 1
            no_answer_match = generated.no_answer and not cited
            no_answer_matches += no_answer_match
            case_passed = bool(answerability_match and no_answer_match)
        passed_cases += case_passed
        case_results.append(
            {
                "scenario_id": case.scenario_id,
                "stratum": case.stratum,
                "should_answer": case.should_answer,
                "predicted_answer": predicted_answer,
                "claim_count": len(generated.claims),
                "cited_source_keys": sorted(cited),
                "citation_precision": citation_precision,
                "citation_recall": citation_recall,
                "conflict_sources_covered": conflict_pair_match,
                "deterministic_passed": case_passed,
            }
        )

    count = len(cases)
    base = {
        "quality_scope": "model_answer_source_set_diagnostic",
        "blocking": False,
        "case_count": count,
        "case_results": case_results,
    }
    if failure is not None:
        return {
            **base,
            "complete": False,
            "status": "incomplete",
            "failure": {"stage": "generation", **failure},
            "metrics": None,
            "semantic_review": _semantic_unavailable("run_incomplete"),
        }
    return {
        **base,
        "complete": True,
        "status": "complete",
        "by_stratum": _by_stratum(case_results),
        "metrics": {
            "answerability_accuracy": answerability_matches / count,
            "no_answer_accuracy": _rate(no_answer_matches, no_answer_count),
            "citation_precision": (
                fmean(citation_precisions) if citation_precisions else None
            ),
            "citation_recall": fmean(citation_recalls) if citation_recalls else None,
            "conflict_source_coverage": _rate(conflict_pair_matches, conflict_pair_count),
            "deterministic_pass_rate": passed_cases / count,
        },
        "semantic_review": _semantic_unavailable("no_independent_review"),
    }


def _semantic_case_status(
    case: AskWorldEvalCase,
    result: dict[str, Any],
    decision: AskWorldTeacherDecision | None,
) -> tuple[str, list[str]]:
    """One case's semantic status; a review never overrides a deterministic failure."""

    if decision is None:
        return "unreviewed", []
    if decision.reference_verdict != "accept":
        return "reference_disputed", []
    if sorted(item.claim_index for item in decision.claims) != list(
        range(result["claim_count"])
    ):
        return "invalid_review", ["claim_review_coverage"]
    if decision.model_verdict == "ambiguous":
        return "ambiguous", []

    failed: list[str] = []
    if result["predicted_answer"] != case.should_answer:
        failed.append("answerability_mismatch")
    if case.source_conflict and not result["conflict_sources_covered"]:
        failed.append("conflict_sources_not_covered")
    reviewed: list[str] = []
    if not decision.answerability_justified:
        reviewed.append("answerability_unjustified")
    for claim in sorted(decision.claims, key=lambda item: item.claim_index):
        if not claim.supported:
            reviewed.append(f"claim_unsupported:{claim.claim_index}")
        if not claim.attribute_matched:
            reviewed.append(f"claim_attribute_mismatch:{claim.claim_index}")
    if not decision.answer_consistent:
        reviewed.append("answer_inconsistent")
    if case.source_conflict and decision.conflict_presented is not True:
        reviewed.append("conflict_not_presented")
    if decision.model_verdict == "pass" and reviewed:
        reviewed.append("reviewer_verdict_inconsistent")
    failed += reviewed
    if decision.model_verdict == "fail" and not failed:
        failed.append("reviewer_verdict_fail")
    return ("fail" if failed else "pass"), failed


def summarize_ask_world_semantic_review(
    cases: list[AskWorldEvalCase],
    deterministic_results: list[dict[str, Any]],
    decisions: list[AskWorldTeacherDecision],
    reviewer: dict[str, Any],
) -> dict[str, Any]:
    """Aggregate independent per-claim reviews into a semantic result.

    A case passes only when the review accepts every check and the deterministic
    prerequisites (answerability, conflict source coverage) also hold. Cases
    without a valid review stay visible and keep the aggregate unavailable.
    """

    results = {str(item["scenario_id"]): item for item in deterministic_results}
    by_case = {decision.scenario_id: decision for decision in decisions}
    statuses: Counter[str] = Counter()
    case_results: list[dict[str, Any]] = []
    claims = supported = matched = 0
    conflicts = presented = 0
    justified = consistent = decided = 0
    for case in cases:
        decision = by_case.get(case.scenario_id)
        status, failed = _semantic_case_status(case, results[case.scenario_id], decision)
        statuses[status] += 1
        case_results.append(
            {
                "scenario_id": case.scenario_id,
                "stratum": case.stratum,
                "semantic_status": status,
                "failed_checks": failed,
            }
        )
        if decision is None or status not in _SEMANTIC_DECIDED:
            continue
        decided += 1
        justified += decision.answerability_justified
        consistent += decision.answer_consistent
        claims += len(decision.claims)
        supported += sum(item.supported for item in decision.claims)
        matched += sum(item.attribute_matched for item in decision.claims)
        if case.source_conflict:
            conflicts += 1
            presented += decision.conflict_presented is True

    reviewed = sum(statuses[name] for name in _SEMANTIC_REVIEWED)
    available = reviewed == len(cases)
    return {
        "available": available,
        **({} if available else {"reason": "incomplete_review_coverage"}),
        "reviewer": reviewer,
        "coverage": {
            "case_count": len(cases),
            "valid_review_count": reviewed,
            "decided_case_count": decided,
            "status_counts": dict(sorted(statuses.items())),
        },
        "metrics": {
            # Ambiguous or disputed-reference cases count as not passed.
            "semantic_pass_rate": (
                _rate(statuses["pass"], len(cases)) if available else None
            ),
            "claim_support_rate": _rate(supported, claims),
            "claim_attribute_match_rate": _rate(matched, claims),
            "conflict_presentation_rate": _rate(presented, conflicts),
            "answer_consistency_rate": _rate(consistent, decided),
            "answerability_justification_rate": _rate(justified, decided),
        },
        "case_results": case_results,
    }


async def evaluate_ask_world_teacher_calibration(
    cases: list[AskWorldEvalCase],
    generated: dict[str, GeneratedAskWorldOutput],
    deterministic_results: list[dict[str, Any]],
    executor: Any,
) -> dict[str, Any]:
    """Use one pinned surrogate teacher pass without mutating human-review fields."""

    payload = []
    for case in cases:
        output = generated.get(case.scenario_id)
        if output is None:
            raise ValueError(f"missing generated output: {case.scenario_id}")
        payload.append(
            {
                "scenario_id": case.scenario_id,
                "question": case.question,
                "reference": {
                    "should_answer": case.should_answer,
                    "relevant_source_keys": case.relevant_source_keys,
                    "source_conflict": case.source_conflict,
                },
                "sources": [
                    {
                        "key": source.key,
                        "kind": source.kind,
                        "title": source.title,
                        "content": source.content,
                    }
                    for source in _author_sources(case)
                ],
                "model_output": {
                    "answer": output.answer,
                    "uncertainty": output.uncertainty,
                    "no_answer": output.no_answer,
                    "claims": [
                        {
                            "claim_index": index,
                            "text": claim.text,
                            "citation_keys": claim.citation_keys,
                        }
                        for index, claim in enumerate(output.claims)
                    ],
                },
            }
        )
    teacher = await executor.generate_structured(
        _ASK_WORLD_TEACHER_RUBRIC
        + "\n\n<CASES>\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n</CASES>",
        AskWorldTeacherOutput,
        step_name="eval.ask_world.teacher_calibration",
    )
    expected_ids = {case.scenario_id for case in cases}
    returned_ids = [decision.scenario_id for decision in teacher.decisions]
    if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
        raise ValueError("Ask World teacher decisions do not match requested scenarios")

    meta = executor.meta
    rubric_hash = hashlib.sha256(_ASK_WORLD_TEACHER_RUBRIC.encode("utf-8")).hexdigest()
    semantic = summarize_ask_world_semantic_review(
        cases,
        deterministic_results,
        teacher.decisions,
        {
            "kind": "surrogate_teacher",
            "human_validated": False,
            "model": meta.model,
            "reasoning_effort": meta.reasoning_effort,
            "executor_hash": meta.executor_hash,
            "rubric_hash": rubric_hash,
        },
    )
    deterministic = {
        str(item["scenario_id"]): bool(item["deterministic_passed"])
        for item in deterministic_results
    }
    status = {
        item["scenario_id"]: item["semantic_status"] for item in semantic["case_results"]
    }
    comparable = sorted(
        scenario for scenario, value in status.items() if value in _SEMANTIC_DECIDED
    )
    disagreements = [
        scenario
        for scenario in comparable
        if (status[scenario] == "pass") != deterministic[scenario]
    ]
    return {
        "kind": "surrogate_teacher",
        "human_validated": False,
        "blocking": False,
        "teacher_model": meta.model,
        "reasoning_effort": meta.reasoning_effort,
        "executor_hash": meta.executor_hash,
        "rubric_hash": rubric_hash,
        "metrics": {
            "reference_acceptance_rate": sum(
                decision.reference_verdict == "accept" for decision in teacher.decisions
            )
            / len(cases),
            "deterministic_teacher_agreement": _rate(
                len(comparable) - len(disagreements), len(comparable)
            ),
            "ambiguous_count": sum(
                item.reference_verdict == "ambiguous" or item.model_verdict == "ambiguous"
                for item in teacher.decisions
            ),
        },
        "disagreement_scenarios": disagreements,
        "case_results": [
            decision.model_dump(mode="json")
            for decision in sorted(
                teacher.decisions,
                key=lambda item: item.scenario_id,
            )
        ],
        "semantic_review": semantic,
    }


def _code_provenance() -> dict[str, Any]:
    """Git revision and a hash of uncommitted work, so a report names its code."""

    root = Path(__file__).resolve().parents[2]

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            ["git", *args], cwd=root, stderr=subprocess.DEVNULL
        )

    try:
        revision = git("rev-parse", "HEAD").decode().strip()
        patch = git("diff", "HEAD", "--binary")
        untracked = [
            name
            for name in git("ls-files", "--others", "--exclude-standard", "-z")
            .decode()
            .split("\0")
            if name
        ]
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "git_dirty": None, "working_tree_sha256": None}
    digest = hashlib.sha256(patch)
    for name in untracked:
        digest.update(name.encode("utf-8") + b"\0")
        try:
            digest.update((root / name).read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    dirty = bool(patch or untracked)
    return {
        "git_commit": revision,
        "git_dirty": dirty,
        "working_tree_sha256": digest.hexdigest() if dirty else None,
    }


def _holdout_material_sha(cases: list[AskWorldEvalCase]) -> str:
    """Identify reserved model inputs independently of debug edits or gold labels."""

    packets = [
        {
            "question": case.question,
            "sources": sorted(
                (
                    source.model_dump(
                        include={"key", "kind", "title", "content", "source_hash"}
                    )
                    for source in _author_sources(case)
                ),
                key=lambda source: source["key"],
            ),
        }
        for case in cases
        if case.split == "holdout"
    ]
    encoded = sorted(
        json.dumps(packet, ensure_ascii=False, sort_keys=True) for packet in packets
    )
    return hashlib.sha256(json.dumps(encoded, ensure_ascii=False).encode()).hexdigest()


def _validate_holdout_freeze(path: Path, freeze_config: Path | None) -> dict[str, Any]:
    """Require completed debug review and self-test before any holdout model access."""

    if freeze_config is None:
        raise ValueError(
            "holdout requires --freeze-config after debug and teacher self-test"
        )
    from evals.codex_executor import CodexStructuredExecutor

    config = json.loads(freeze_config.read_text(encoding="utf-8"))
    executor_hash = CodexStructuredExecutor(
        model=ASK_WORLD_TEACHER_MODEL,
        reasoning_effort=ASK_WORLD_TEACHER_REASONING_EFFORT,
        allowed_models=frozenset({ASK_WORLD_TEACHER_MODEL}),
    ).meta.executor_hash
    expected = {
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "holdout_material_sha256": _holdout_material_sha(load_ask_world_cases(path)),
        "system_prompt_sha256": hashlib.sha256(
            _ASK_WORLD_SYSTEM_PROMPT.encode()
        ).hexdigest(),
        "rubric_sha256": hashlib.sha256(_ASK_WORLD_TEACHER_RUBRIC.encode()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "teacher_model": ASK_WORLD_TEACHER_MODEL,
        "teacher_reasoning_effort": ASK_WORLD_TEACHER_REASONING_EFFORT,
        "teacher_executor_hash": executor_hash,
    }
    if not config.get("review_ready") or any(
        config.get(k) != v for k, v in expected.items()
    ):
        raise ValueError(
            "holdout freeze does not match the dataset, runner, prompt or rubric"
        )
    root = Path(__file__).resolve().parents[2]
    evidence = {}
    for name in ("debug_report", "teacher_selftest"):
        evidence_path = root / config[name]["path"]
        content = evidence_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != config[name]["sha256"]:
            raise ValueError(f"holdout freeze {name} evidence changed")
        evidence[name] = json.loads(content)
    debug = evidence["debug_report"]
    debug_ids = {
        case.scenario_id for case in load_ask_world_cases(path) if case.split == "debug"
    }
    if (
        not debug.get("complete")
        or debug.get("split") != "debug"
        or debug.get("case_count") != len(debug_ids)
        or len(debug.get("case_results", [])) != len(debug_ids)
        or debug.get("dataset_sha256") != expected["dataset_sha256"]
        or debug.get("provenance", {}).get("system_prompt_sha256")
        != expected["system_prompt_sha256"]
        or not config.get("system_under_test")
        or debug.get("system_under_test") != config["system_under_test"]
        or {row["scenario_id"] for row in debug["case_results"]} != debug_ids
        or not debug.get("semantic_review", {}).get("available")
        or debug.get("teacher_calibration", {}).get("rubric_hash")
        != expected["rubric_sha256"]
        or debug.get("teacher_calibration", {}).get("teacher_model")
        != ASK_WORLD_TEACHER_MODEL
        or debug.get("teacher_calibration", {}).get("reasoning_effort")
        != ASK_WORLD_TEACHER_REASONING_EFFORT
        or debug.get("teacher_calibration", {}).get("executor_hash") != executor_hash
        or debug.get("teacher_calibration", {})
        .get("metrics", {})
        .get("reference_acceptance_rate")
        != 1.0
        or debug.get("teacher_calibration", {}).get("metrics", {}).get("ambiguous_count")
        != 0
        or not evidence["teacher_selftest"].get("all_expected_matched")
        or evidence["teacher_selftest"].get("dataset_sha256")
        != expected["dataset_sha256"]
        or evidence["teacher_selftest"].get("teacher", {}).get("rubric_hash")
        != expected["rubric_sha256"]
        or evidence["teacher_selftest"].get("teacher", {}).get("teacher_model")
        != ASK_WORLD_TEACHER_MODEL
        or evidence["teacher_selftest"].get("teacher", {}).get("reasoning_effort")
        != ASK_WORLD_TEACHER_REASONING_EFFORT
        or evidence["teacher_selftest"].get("teacher", {}).get("executor_hash")
        != executor_hash
    ):
        raise ValueError(
            "holdout requires complete matching debug review and passing self-test"
        )
    return config


async def run_ask_world_model_probe_eval(
    novel_id: str,
    path: Path = MODEL_PROBE_DATASET,
    *,
    teacher_model: str | None = None,
    teacher_reasoning_effort: str | None = None,
    split: str | None = None,
    ledger: Path | None = None,
    freeze_config: Path | None = None,
) -> dict[str, Any]:
    """Run the committed probes against one explicitly selected project model."""

    from core.database import DatabaseManager
    from modules.project.facade import open_project_llm_client

    cases = load_ask_world_cases(path)
    if split is None and any(case.split == "holdout" for case in cases):
        raise ValueError(
            "partitioned probe datasets require --split; holdout cannot run implicitly"
        )
    if split is not None:
        cases = [case for case in cases if case.split == split]
        if not cases:
            raise ValueError(f"Ask World probe dataset has no {split} cases")
    if teacher_model is not None and teacher_model != ASK_WORLD_TEACHER_MODEL:
        raise ValueError(f"Ask World teacher model must be {ASK_WORLD_TEACHER_MODEL}")
    if teacher_model is not None and (
        teacher_reasoning_effort != ASK_WORLD_TEACHER_REASONING_EFFORT
    ):
        raise ValueError(
            "Ask World teacher reasoning effort must be "
            f"{ASK_WORLD_TEACHER_REASONING_EFFORT}"
        )
    if teacher_model is None and teacher_reasoning_effort is not None:
        raise ValueError("teacher reasoning effort requires a teacher model")
    frozen = None
    if split == "holdout":
        frozen = _validate_holdout_freeze(path, freeze_config)
        if teacher_model != ASK_WORLD_TEACHER_MODEL:
            raise ValueError("holdout requires the frozen teacher")
        assert freeze_config is not None
        _HOLDOUT_RUNS.mkdir(parents=True, exist_ok=True)
        marker = _HOLDOUT_RUNS / (frozen["holdout_material_sha256"] + ".json")
        try:
            with marker.open("x", encoding="utf-8") as handle:
                json.dump(
                    {
                        "dataset_sha256": frozen["dataset_sha256"],
                        "holdout_material_sha256": frozen["holdout_material_sha256"],
                        "rubric_sha256": frozen["rubric_sha256"],
                    },
                    handle,
                )
        except FileExistsError as exc:
            raise ValueError(
                "holdout already started; only offline review/replay is allowed"
            ) from exc
    generated: dict[str, GeneratedAskWorldOutput] = {}
    manager = DatabaseManager()
    manager.init()
    try:
        async with manager.session_factory() as db:
            if manager.engine.dialect.name == "postgresql":
                from sqlalchemy import text

                await db.execute(text("SET TRANSACTION READ ONLY"))
            async with open_project_llm_client(
                db,
                novel_id,
                timeout_override=1800,
            ) as client:
                service = AskWorldService()
                model = str(client.model_name)
                profile = client.profile_summary
                if frozen is not None and frozen.get("system_under_test") != {
                    "provider_id": profile.get("provider_id"),
                    "model": model,
                    "profile_hash": hashlib.sha256(
                        json.dumps(profile, sort_keys=True).encode()
                    ).hexdigest(),
                }:
                    raise ValueError(
                        "holdout project model/profile differs from frozen debug"
                    )
                await db.commit()
                if db.in_transaction():
                    raise RuntimeError(
                        "Ask World model probes require a clean checkpoint"
                    )

                async def generate(case: AskWorldEvalCase) -> GeneratedAskWorldOutput:
                    sources = [
                        source.model_dump(mode="json") for source in _author_sources(case)
                    ]
                    result = await service._generate(
                        client,
                        AskWorldQuestionRequest(
                            novel_id=novel_id,
                            question=case.question,
                        ),
                        sources,
                        model=model,
                    )
                    generated[case.scenario_id] = result
                    return result

                report = await evaluate_ask_world_model_cases(cases, generate)
                report.update(
                    {
                        "dataset": path.name,
                        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "split": split,
                        "provenance": {
                            **_code_provenance(),
                            "system_prompt_sha256": hashlib.sha256(
                                _ASK_WORLD_SYSTEM_PROMPT.encode("utf-8")
                            ).hexdigest(),
                        },
                        "system_under_test": {
                            "provider_id": profile.get("provider_id"),
                            "model": model,
                            "profile_hash": hashlib.sha256(
                                json.dumps(profile, sort_keys=True).encode("utf-8")
                            ).hexdigest(),
                        },
                    }
                )
    finally:
        await manager.close()
    if ledger is not None:
        _write_generation_ledger(ledger, report, generated)
    if teacher_model is not None and report["complete"]:
        from evals.codex_executor import CodexStructuredExecutor

        try:
            teacher = await evaluate_ask_world_teacher_calibration(
                cases,
                generated,
                report["case_results"],
                CodexStructuredExecutor(
                    model=teacher_model,
                    reasoning_effort=teacher_reasoning_effort,
                    allowed_models=frozenset({ASK_WORLD_TEACHER_MODEL}),
                    attempts=1 if split == "holdout" else 2,
                ),
            )
        except Exception as exc:
            # Keep the paid generation results, but never record the run as complete.
            report.update(
                {
                    "complete": False,
                    "status": "incomplete",
                    "failure": {
                        "stage": "teacher_calibration",
                        "error_type": type(exc).__name__,
                    },
                    "teacher_calibration": {
                        "kind": "surrogate_teacher",
                        "human_validated": False,
                        "blocking": False,
                        "status": "failed",
                    },
                    "semantic_review": _semantic_unavailable("teacher_failed"),
                }
            )
        else:
            report["semantic_review"] = teacher.pop("semantic_review")
            report["teacher_calibration"] = teacher
    return report


def _write_generation_ledger(
    path: Path,
    report: dict[str, Any],
    generated: dict[str, GeneratedAskWorldOutput],
) -> None:
    """Keep each case's model output so a human can review it against the dataset.

    The report itself stores no generated text. The probe evidence is synthetic, so
    the ledger may travel with task evidence; for any non-synthetic dataset keep it
    in a private directory outside the repository.
    """

    rows = [
        json.dumps(
            {
                "scenario_id": scenario_id,
                "dataset_sha256": report.get("dataset_sha256"),
                "model": report.get("system_under_test", {}).get("model"),
                "generated": output.model_dump(mode="json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for scenario_id, output in generated.items()
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(row + "\n" for row in rows), encoding="utf-8")
    temporary.replace(path)


def _write_report(path: Path, report: dict[str, Any]) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.ask_world")
    parser.add_argument("dataset", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model-probes", action="store_true")
    parser.add_argument("--novel-id")
    parser.add_argument("--split", choices=("debug", "holdout"))
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--freeze-config", type=Path)
    parser.add_argument("--teacher-model", choices=(ASK_WORLD_TEACHER_MODEL,))
    parser.add_argument(
        "--teacher-reasoning-effort",
        choices=(ASK_WORLD_TEACHER_REASONING_EFFORT,),
    )
    args = parser.parse_args()
    if args.model_probes:
        if not args.novel_id:
            parser.error("--model-probes requires --novel-id")
        if args.output:
            # Replace any earlier report so an interrupted paid run cannot be
            # mistaken for the previous complete result.
            _write_report(
                args.output,
                {"blocking": False, "complete": False, "status": "running"},
            )
        try:
            report = asyncio.run(
                run_ask_world_model_probe_eval(
                    args.novel_id,
                    args.dataset or MODEL_PROBE_DATASET,
                    teacher_model=args.teacher_model,
                    teacher_reasoning_effort=args.teacher_reasoning_effort,
                    split=args.split,
                    ledger=args.ledger,
                    freeze_config=args.freeze_config,
                )
            )
        except BaseException as exc:
            if args.output:
                _write_report(
                    args.output,
                    {
                        "blocking": False,
                        "complete": False,
                        "error_type": type(exc).__name__,
                        "status": "aborted",
                    },
                )
            raise
    else:
        report = run_ask_world_eval(args.dataset or DEFAULT_DATASET)
    if args.output:
        _write_report(args.output, report)
    else:
        print(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            end="",
        )
    if args.model_probes:
        if not report["complete"]:
            raise SystemExit(2)
    elif not report["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
