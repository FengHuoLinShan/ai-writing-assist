"""Offline paired evaluation: frozen prefixes, blind review and honest costs.

No command in this module calls a provider or changes a project.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.metrics import cohens_kappa

DATA = Path(__file__).parent / "datasets" / "creative_forecast" / "families.json"
DIMENSIONS = ("supported", "timely", "actionable", "respects_goal", "low_disruption")
TOOLS = {"source_search", "workspace_read", "workspace_edit", "workspace_check"}
ARMS = {
    "A": "fixed_team",
    "B": "single_with_workspace",
    "C": "adaptive_with_workspace",
    "D": "adaptive_discussion_only",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def corpus():
    families = json.loads(DATA.read_text())
    if len(families) < 12 or len({item["mechanism"] for item in families}) != len(
        families
    ):
        raise ValueError("Need twelve independent causal story families")
    cases = []
    for family in families:
        for index in range(1, len(family["scenes"]) + 1):
            visible = "\n".join(family["scenes"][:index])
            cases.append(
                {
                    "id": f"{family['id']}-{index:02}",
                    "family": family["id"],
                    "split": family["split"],
                    "prefix": visible,
                    "source_manifest": {"synthetic-prose": digest(visible)},
                    "instruction": family["instruction"],
                    "quiet_or_weak": index in family["quiet_at"],
                    "evaluation_only": {
                        "mechanism": family["mechanism"],
                        "rubric_note": family["rubric_note"],
                    },
                    "provenance": "original_synthetic_v1",
                    "human_dataset_review": "not_run",
                }
            )
    if len(cases) < 120 or sum(item["quiet_or_weak"] for item in cases) < len(cases) / 3:
        raise ValueError(
            "Need 120 prefixes with at least one third quiet counterexamples"
        )
    return cases


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suite: Literal["creative", "forecast"] = "creative"
    case_id: str
    arm: Literal["A", "B", "C", "D"]
    capability: str
    code_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    profile_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    scope_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    tools: list[str]
    workspace: bool
    run_id: str
    provider_call_ids: list[str] = Field(default_factory=list)
    evidence_kind: Literal["real_gateway", "provider_stub", "fixture", "incomplete"]
    output: str = Field(max_length=100000)
    status: Literal["completed", "partial", "failed", "cancelled"]
    requests: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    tool_calls: int = Field(ge=0)
    audit_requests: int = Field(ge=0)
    repair_requests: int = Field(ge=0)
    unknown_usage: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)
    currency: str | None = None
    truncated: bool = False
    intervention: str | None = None

    @model_validator(mode="after")
    def accounting(self):
        if (
            self.evidence_kind == "real_gateway"
            and len(set(self.provider_call_ids)) < self.requests
        ):
            raise ValueError(
                "Every real request needs its gateway call receipt, including retries"
            )
        if self.audit_requests + self.repair_requests > self.requests:
            raise ValueError("Audit/repair calls must be included in total requests")
        if self.cost is not None and (
            not self.currency
            or self.unknown_usage
            or self.input_tokens is None
            or self.output_tokens is None
        ):
            raise ValueError(
                "Unknown usage cannot be reported as a complete monetary cost"
            )
        return self


def read_receipts(path):
    records = [
        Receipt.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    keys = [(row.suite, row.case_id, row.arm, row.capability) for row in records]
    if len(keys) != len(set(keys)):
        raise ValueError(
            "Duplicate paired result; retain failures under distinct experiment files"
        )
    known = {item["id"] for item in corpus()}
    if any(row.case_id not in known for row in records):
        raise ValueError("Unknown prefix")
    return records


def blind_export(records, output, *, seed):
    output.mkdir(parents=True, exist_ok=True)
    public, mapping = [], {}
    cases = {item["id"]: item for item in corpus()}
    shuffled = sorted(
        records, key=lambda row: digest([seed, row.case_id, row.arm, row.capability])
    )
    for row in shuffled:
        key = digest([seed, row.model_dump()])[:20]
        mapping[key] = row.model_dump()
        case = cases[row.case_id]
        public.append(
            {
                "response_id": key,
                "prefix": case["prefix"],
                "instruction": case["instruction"],
                "response": row.output,
                "completion": row.status,
                "intervention": row.intervention,
            }
        )
    private = output / "operator-only"
    private.mkdir(exist_ok=True)
    (private / "mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2)
    )
    columns = [
        "reviewer_id",
        "response_id",
        *DIMENSIONS,
        "repaired",
        "hard_constraints_kept",
        "new_severe_errors",
        "unsupported_strong_claims",
        "hard_boundary_violation",
        "author_corrections",
        "used_preparation",
        "reason",
    ]
    for reviewer in ("reviewer-1", "reviewer-2"):
        folder = output / reviewer
        folder.mkdir(exist_ok=True)
        with (folder / "scores.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(
                {"reviewer_id": reviewer, "response_id": value["response_id"]}
                for value in public
            )
        cards = "".join(
            "<article><h2>"
            + value["response_id"]
            + "</h2><h3>当时已读</h3><pre>"
            + html.escape(value["prefix"])
            + "</pre><p>明确意图："
            + html.escape(value["instruction"])
            + "</p><h3>待评结果</h3><pre>"
            + html.escape(value["response"])
            + "</pre><p>完成情况："
            + html.escape(value["completion"])
            + "</p></article>"
            for value in public
        )
        (folder / "review.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>独立盲评</title>'
            "<style>body{max-width:850px;margin:3rem auto;font:16px/1.7 sans-serif;"
            "padding:1rem}"
            "pre{white-space:pre-wrap}"
            "article{border-top:1px solid #bbb;padding:2rem 0}</style>"
            "<h1>独立评阅</h1><p>各维度填写 0、1、2。先独立评分；分歧保留。"
            "不得把猜中未来当作准确，也不得用总分抵消越权、强断言或未经确认的修改。</p>"
            + cards
        )
    return {
        "responses": len(public),
        "reviewers": 2,
        "human_review": "not_run",
        "mapping": "operator-only/mapping.json",
    }


def load_reviews(paths, mapping):
    reviews = defaultdict(list)
    for path in paths:
        with path.open(newline="") as file:
            for row in csv.DictReader(file):
                key, reviewer = row["response_id"], row["reviewer_id"].strip()
                if key not in mapping or not reviewer:
                    raise ValueError("Review is not bound to this blind package")
                if not any(row.get(field, "").strip() for field in DIMENSIONS):
                    continue
                scores = {field: int(row[field]) for field in DIMENSIONS}
                if (
                    any(value not in {0, 1, 2} for value in scores.values())
                    or not row.get("reason", "").strip()
                ):
                    raise ValueError(
                        "Each independent score needs all dimensions and a reason"
                    )
                flags = {
                    field: int(row[field])
                    for field in (
                        "repaired",
                        "hard_constraints_kept",
                        "new_severe_errors",
                        "unsupported_strong_claims",
                        "hard_boundary_violation",
                        "author_corrections",
                        "used_preparation",
                    )
                }
                if any(value < 0 for value in flags.values()) or any(
                    flags[field] not in {0, 1}
                    for field in (
                        "repaired",
                        "hard_constraints_kept",
                        "hard_boundary_violation",
                        "used_preparation",
                    )
                ):
                    raise ValueError("Invalid independent review outcome")
                if reviewer in {value["reviewer"] for value in reviews[key]}:
                    raise ValueError("Duplicate review by the same reviewer")
                reviews[key].append(
                    {"reviewer": reviewer, **scores, **flags, "reason": row["reason"]}
                )
    return reviews


def cluster_interval(values):
    # Resample whole story families; prefixes from one story are not independent.
    if len(values) < 4:
        return None
    rng, families = random.Random(20260920), sorted(values)
    draws = sorted(
        mean(mean(values[key]) for key in rng.choices(families, k=len(families)))
        for _ in range(2000)
    )
    return [draws[50], draws[1949]]


def report(mapping, reviews):
    cases = {item["id"]: item for item in corpus()}
    records = {key: Receipt.model_validate(value) for key, value in mapping.items()}
    groups, result = defaultdict(dict), {}
    for key, row in records.items():
        pair = (row.suite, row.capability, row.case_id)
        if row.arm in groups[pair]:
            raise ValueError("Duplicate paired arm")
        groups[pair][row.arm] = key
    for suite, capability in sorted(
        {(row.suite, row.capability) for row in records.values()}
    ):
        arm_names = (
            ARMS if suite == "creative" else {"A": "static_evidence", "B": "forecast"}
        )
        pairs = {
            case: arms
            for (kind, cap, case), arms in groups.items()
            if (kind, cap) == (suite, capability)
        }
        complete, fairness, failures = [], [], []
        for case, arms in pairs.items():
            if set(arms) != set(arm_names):
                failures.append([case, "missing_arm"])
                continue
            rows = [records[arms[arm]] for arm in arm_names]
            b = records[arms["B"]]
            c = records[arms["C"]] if suite == "creative" else b
            d = records[arms["D"]] if suite == "creative" else b
            if (
                len({row.profile_hash for row in rows}) != 1
                or len({row.scope_hash for row in rows}) != 1
                or len({row.code_sha for row in rows}) != 1
                or suite == "creative"
                and (
                    set(b.tools) != set(c.tools)
                    or not TOOLS <= set(b.tools)
                    or not b.workspace
                    or not c.workspace
                    or d.workspace
                )
            ):
                fairness.append(case)
                continue
            if any(len(reviews.get(key, [])) < 2 for key in arms.values()):
                failures.append([case, "independent_human_reviews_missing"])
                continue
            if any(
                row.status != "completed"
                or row.truncated
                or row.evidence_kind != "real_gateway"
                for row in rows
            ):
                failures.append([case, "nonreal_or_incomplete"])
                continue
            complete.append(case)
        arms_report = {}
        for arm in arm_names:
            keys = [arms[arm] for arms in pairs.values() if arm in arms]
            rows = [records[key] for key in keys]
            scores = [value for key in keys for value in reviews.get(key, [])]
            currencies = {row.currency for row in rows}
            paired_scores = [
                reviews[key][:2] for key in keys if len(reviews.get(key, [])) >= 2
            ]
            arms_report[arm] = {
                "runs": len(rows),
                "failures_retained": sum(row.status != "completed" for row in rows),
                "requests": sum(row.requests for row in rows),
                "tool_calls": sum(row.tool_calls for row in rows),
                "audit_requests": sum(row.audit_requests for row in rows),
                "repair_requests": sum(row.repair_requests for row in rows),
                "unknown_usage": sum(row.unknown_usage for row in rows),
                "input_tokens": sum(row.input_tokens for row in rows)
                if all(row.input_tokens is not None for row in rows)
                else None,
                "output_tokens": sum(row.output_tokens for row in rows)
                if all(row.output_tokens is not None for row in rows)
                else None,
                "cached_tokens": sum(row.cached_tokens for row in rows)
                if all(row.cached_tokens is not None for row in rows)
                else None,
                "cost": sum(row.cost for row in rows)
                if rows
                and all(row.cost is not None for row in rows)
                and len(currencies) == 1
                else None,
                "currency": next(iter(currencies)) if len(currencies) == 1 else None,
                "duration_ms": sum(row.duration_ms for row in rows),
                "rubric_mean": {
                    field: mean(value[field] for value in scores) if scores else None
                    for field in DIMENSIONS
                },
                "hard_boundary_violations": sum(
                    value["hard_boundary_violation"] for value in scores
                ),
                "new_severe_errors": sum(value["new_severe_errors"] for value in scores),
                "unsupported_strong_claims": sum(
                    value["unsupported_strong_claims"] for value in scores
                ),
                "constraint_failures": sum(
                    not value["hard_constraints_kept"] for value in scores
                ),
                "reviewer_agreement": {
                    field: cohens_kappa(
                        [str(pair[0][field]) for pair in paired_scores],
                        [str(pair[1][field]) for pair in paired_scores],
                    )
                    if paired_scores
                    else None
                    for field in DIMENSIONS
                },
            }
        comparisons = {}
        for treatment, baseline in (
            [("C", "B"), ("C", "D")] if suite == "creative" else [("B", "A")]
        ):
            differences, holdout = defaultdict(list), defaultdict(list)
            for case in complete:
                arms = pairs[case]

                def score(arm):
                    return mean(
                        mean(value[field] for field in DIMENSIONS)
                        for value in reviews[arms[arm]]
                    )

                delta = score(treatment) - score(baseline)
                differences[cases[case]["family"]].append(delta)
                if cases[case]["split"] == "holdout":
                    holdout[cases[case]["family"]].append(delta)
            comparisons[f"{treatment} minus {baseline}"] = {
                "paired_family_interval": cluster_interval(differences),
                "holdout_family_interval": cluster_interval(holdout),
                "holdout_families": len(holdout),
            }
        primary = "C minus B" if suite == "creative" else "B minus A"
        interval = comparisons[primary]["paired_family_interval"]
        hard_fail = any(
            arm[key]
            for arm in arms_report.values()
            for key in (
                "hard_boundary_violations",
                "new_severe_errors",
                "unsupported_strong_claims",
                "constraint_failures",
            )
        )
        complete_families = {cases[case]["family"] for case in complete}
        content_ready = (
            len(complete) >= 120
            and len(complete_families) >= 12
            and not failures
            and not fairness
            and not hard_fail
        )
        result[f"{suite}:{capability}"] = {
            "comparison": primary,
            "comparisons": comparisons,
            "paired_prefixes": len(complete),
            "independent_families": len(complete_families),
            "fairness_failures": fairness,
            "missing_or_failed": failures,
            "arms": arms_report,
            "paired_family_interval": interval,
            "content_gate": "ready_for_operator_review"
            if content_ready
            else "not_passed",
            "positive_increment_in_this_sample": bool(
                content_ready and interval and interval[0] > 0
            ),
            "automatic_release": (
                "requires_separate_engineering_gate_and_operator_approval"
            ),
        }
    return {
        "schema": "creative-forecast-eval-v1",
        "capabilities": result,
        "dataset_human_review": "not_run",
        "production_release": "not_run",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("corpus")
    build.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("blind")
    export.add_argument("--records", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--seed", required=True)
    summary = commands.add_parser("report")
    summary.add_argument("--mapping", type=Path, required=True)
    summary.add_argument("--reviews", type=Path, nargs="+", required=True)
    summary.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "corpus":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "\n".join(json.dumps(value, ensure_ascii=False) for value in corpus()) + "\n"
        )
    elif args.command == "blind":
        print(
            json.dumps(
                blind_export(read_receipts(args.records), args.output, seed=args.seed)
            )
        )
    else:
        mapping = json.loads(args.mapping.read_text())
        args.output.write_text(
            json.dumps(
                report(mapping, load_reviews(args.reviews, mapping)),
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
