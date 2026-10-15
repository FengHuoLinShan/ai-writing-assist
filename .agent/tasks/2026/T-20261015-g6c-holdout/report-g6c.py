"""Offline G6c analysis; formulas are frozen before the first holdout call."""

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

P = Path("/Users/tywww/.codex/private/g6c-holdout-20261015")
OLD = Path("/Users/tywww/.codex/private/g6b-recalibration-20261015")
ROOT = Path(__file__).resolve().parents[4]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    frozen = read(P / "FREEZE_CONFIG.json")
    for name, expected in frozen["hashes"].items():
        assert sha(Path(name).read_bytes()) == expected, name
    cases = {
        c["scenario_id"]: c
        for c in [
            json.loads(l) for l in (P / "holdout-v1.jsonl").read_text().splitlines()
        ]
    }
    rows = []
    teacher_meta = []
    for batch in range(2):
        mapping = read(P / f"judge-{batch}-mapping.json")
        judged = read(P / f"judge-{batch}-result.json")
        teacher_meta.append(
            {
                k: judged[k]
                for k in (
                    "teacher_model",
                    "reasoning_effort",
                    "executor_hash",
                    "rubric_hash",
                    "metrics",
                    "disagreement_scenarios",
                )
            }
        )
        semantic = {
            r["scenario_id"]: r for r in judged["semantic_review"]["case_results"]
        }
        for d in judged["case_results"]:
            binding = mapping[d["scenario_id"]]
            case = cases[binding["scenario_id"]]
            path = P / f"{binding['arm']}-{binding['scenario_id']}.json"
            output = read(path)
            rows.append(
                {
                    **binding,
                    "family": case["family"],
                    "stratum": case["stratum"],
                    "should_answer": case["should_answer"],
                    "source_conflict": case["source_conflict"],
                    "no_answer": output["no_answer"],
                    "claim_count": len(output["claims"]),
                    "unsupported_claims": sum(not c["supported"] for c in d["claims"]),
                    "attribute_mismatches": sum(
                        not c["attribute_matched"] for c in d["claims"]
                    ),
                    "answer_consistent": d["answer_consistent"],
                    "answerability_justified": d["answerability_justified"],
                    "conflict_presented": d["conflict_presented"],
                    "reference_verdict": d["reference_verdict"],
                    "model_verdict": d["model_verdict"],
                    "semantic_status": semantic[d["scenario_id"]]["semantic_status"],
                    "output_sha256": sha(path.read_bytes()),
                    "decision_sha256": sha(
                        json.dumps(d, ensure_ascii=False, sort_keys=True).encode()
                    ),
                }
            )
    assert len(rows) == 64 and len({(r["arm"], r["scenario_id"]) for r in rows}) == 64
    summary = {}
    for arm in ("baseline", "candidate"):
        rr = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            "total": len(rr),
            "answerable": sum(r["should_answer"] for r in rr),
            "unanswerable": sum(not r["should_answer"] for r in rr),
            "over_refusals": sum(r["should_answer"] and r["no_answer"] for r in rr),
            "false_answers": sum(
                not r["should_answer"] and not r["no_answer"] for r in rr
            ),
            "unsupported_claims": sum(r["unsupported_claims"] for r in rr),
            "unsupported_outputs": sum(r["unsupported_claims"] > 0 for r in rr),
            "answer_inconsistencies": sum(not r["answer_consistent"] for r in rr),
            "conflict_failures": sum(
                r["source_conflict"] and r["conflict_presented"] is not True for r in rr
            ),
            "semantic_pass": sum(r["semantic_status"] == "pass" for r in rr),
            "reference_accepted": sum(r["reference_verdict"] == "accept" for r in rr),
            "ambiguous": sum(
                r["reference_verdict"] == "ambiguous"
                or r["model_verdict"] == "ambiguous"
                for r in rr
            ),
        }
    b, c = summary["baseline"], summary["candidate"]
    paired = []
    for sid, case in cases.items():
        rb = next(r for r in rows if r["arm"] == "baseline" and r["scenario_id"] == sid)
        rc = next(
            r for r in rows if r["arm"] == "candidate" and r["scenario_id"] == sid
        )
        paired.append(
            {
                "scenario_id": sid,
                "family": case["family"],
                "should_answer": case["should_answer"],
                "baseline_pass": rb["semantic_status"] == "pass",
                "candidate_pass": rc["semantic_status"] == "pass",
                "baseline_no_answer": rb["no_answer"],
                "candidate_no_answer": rc["no_answer"],
            }
        )
    wins = sum(
        r["should_answer"] and r["baseline_no_answer"] and not r["candidate_no_answer"]
        for r in paired
    )
    losses = sum(
        r["should_answer"] and not r["baseline_no_answer"] and r["candidate_no_answer"]
        for r in paired
    )
    n = wins + losses
    sign_p = (
        min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n)
        if n
        else None
    )
    native = []
    prompts = read(P / "prompts.json")
    for stage in ("run", "judge-0", "judge-1"):
        for cid in read(P / f"{stage}.complete.json")["new_native_calls"]:
            folder = OLD / "live" / cid
            status = read(folder / "status.json")
            request = (folder / "request.bin").read_bytes()
            args = status["argv"]
            binding = None
            if stage == "run":
                messages = json.loads(request)["messages"]
                arm = next(
                    a
                    for a, prompt in prompts.items()
                    if messages[0]["content"] == prompt
                )
                matching = [
                    sid
                    for sid, case in cases.items()
                    if any(
                        "<AUTHOR_QUESTION>\n"
                        + case["question"]
                        + "\n</AUTHOR_QUESTION>"
                        in m["content"]
                        for m in messages
                    )
                ]
                assert len(matching) == 1
                binding = {"arm": arm, "scenario_id": matching[0]}
                expected = {"model": "gpt-6-luna", "effort": "max"}
            else:
                # Also handles inventory overlap if teachers are launched concurrently.
                if (
                    '"scenario_id":"ask-g6c-blind-' + stage[-1] + "-"
                ).encode() not in request:
                    continue
                expected = {"model": "gpt-6.1-sol", "effort": "xhigh"}
            assert args[args.index("-m") + 1] == status["model"] == expected["model"]
            assert f'model_reasoning_effort="{expected["effort"]}"' in args
            assert all(
                canary not in request for canary in (b"KESTREL-6841", b"OSPREY-9253")
            )
            diag = (folder / "stdout.bin").read_bytes() + (
                folder / "stderr.bin"
            ).read_bytes()
            native.append(
                {
                    "stage": stage,
                    "call_id": cid,
                    "binding": binding,
                    "model": status["model"],
                    "reasoning_effort": status["reasoning_effort"],
                    "status": status["status"],
                    "exit_code": status.get("exit_code"),
                    "started_at": status["started_at"],
                    "finished_at": status.get("finished_at"),
                    "request_sha256": status["request_sha256"],
                    "model_argument_confirmed": True,
                    "effort_argument_confirmed": True,
                    "model_diagnostic_confirmed": f"model: {status['model']}".encode()
                    in diag
                    if "--json" not in args
                    else None,
                    "effort_diagnostic_confirmed": f"reasoning effort: {status['reasoning_effort']}".encode()
                    in diag
                    if "--json" not in args
                    else None,
                    "artifacts": {
                        f.name: sha(f.read_bytes())
                        for f in folder.iterdir()
                        if f.is_file()
                    },
                }
            )
    assert len({r["call_id"] for r in native}) == len(native)
    observed = {
        (r["binding"]["arm"], r["binding"]["scenario_id"])
        for r in native
        if r["binding"]
    }
    assert observed == {(a, sid) for a in ("baseline", "candidate") for sid in cases}
    acceptance = {
        "complete_decided_reference_accepted": all(
            r["reference_verdict"] == "accept" and r["model_verdict"] != "ambiguous"
            for r in rows
        ),
        "over_refusal_reduced": c["over_refusals"] < b["over_refusals"],
        "improvement_testable": b["over_refusals"] > 0,
        "candidate_over_refusal_at_most_5_percent": c["over_refusals"] / c["answerable"]
        <= 0.05,
        "no_hallucination_increase": all(
            c[k] == 0 and c[k] <= b[k]
            for k in ("false_answers", "unsupported_claims", "answer_inconsistencies")
        ),
        "conflict_handling_passed": c["conflict_failures"] == 0
        and c["conflict_failures"] <= b["conflict_failures"],
        "overall_quality_passed": c["semantic_pass"] / c["total"] >= 0.95
        and c["semantic_pass"] >= b["semantic_pass"],
        "native_complete": all(
            r["status"] == "native_exit" and r["exit_code"] == 0 for r in native
        ),
    }
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "G6c independent source-family holdout; one pass per arm; generation layer",
        "freeze_sha256": sha((P / "FREEZE_CONFIG.json").read_bytes()),
        "frozen_runtime": frozen["runtime"],
        "human_validated": False,
        "blocking": False,
        "summary": summary,
        "acceptance": acceptance,
        "frozen_acceptance_met": all(acceptance.values()),
        "paired_over_refusal": {
            "improved": wins,
            "regressed": losses,
            "exact_two_sided_sign_test_p": sign_p,
            "note": "Descriptive, not acceptance gate; only one answerable case per family. No population-rate guarantee.",
        },
        "paired_semantic": {
            "improved": sum(
                not r["baseline_pass"] and r["candidate_pass"] for r in paired
            ),
            "regressed": sum(
                r["baseline_pass"] and not r["candidate_pass"] for r in paired
            ),
        },
        "teacher": teacher_meta,
        "rows": rows,
        "paired_rows": paired,
        "native_calls": native,
        "native_call_count": len(native),
        "native_unknown": sum(r["status"] != "native_exit" for r in native),
        "native_nonzero": sum(r["exit_code"] != 0 for r in native),
        "old_protected_unchanged": True,
        "private_root": str(P),
        "limitations": [
            "Synthetic new-family holdout built after candidate was fixed; no independent human author review.",
            "16 families, one generation per case and arm; finite sample and correlated family pairs.",
            "Does not exercise retrieval/Evidence confirmation/knowledge review/citation opening/UI persistence.",
            "Holdout consumed; any further tuning must treat these results as development evidence.",
        ],
    }
    for path in (
        P / "result.json",
        Path(__file__).parent / "artifacts/holdout-ledger-v1.json",
    ):
        with path.open("x") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write("\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "summary",
                    "acceptance",
                    "frozen_acceptance_met",
                    "paired_over_refusal",
                    "paired_semantic",
                    "native_call_count",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
