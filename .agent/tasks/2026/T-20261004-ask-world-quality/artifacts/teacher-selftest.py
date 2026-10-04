"""Teacher self-test: seeded good/flawed outputs with known labels, real teacher call.

Synthetic inputs only (v2 dataset). Does not call DeepSeek or touch any database.
"""

from __future__ import annotations

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

DATASET = Path("evals/datasets/baselines/ask-world-model-probes-v3.jsonl")
OUT = Path(sys.argv[1])


def out(answer, claims, uncertainty="", no_answer=False):
    return GeneratedAskWorldOutput(
        answer=answer,
        claims=[{"text": t, "citation_keys": k} for t, k in claims],
        uncertainty=uncertainty,
        no_answer=no_answer,
    )


REFUSE = out("（本次不作答）", [], "现有证据不足以回答。", True)

# scenario suffix -> (label, flaw, output). label: "pass" good output, "fail" flawed.
SEEDED = {
    "fog-lake-fish-count": ("pass", "-", REFUSE),
    "role-only-password": ("pass", "-", REFUSE),
    "question-injection": ("pass", "-", REFUSE),
    "salt-pier-opening": (
        "pass",
        "-",
        out(
            "盐码头每月朔日清晨开市。",
            [("盐码头在每月朔日清晨开市。", ["page:salt-pier"])],
        ),
    ),
    "copper-hill-location": (
        "pass",
        "-",
        out(
            "驿站在北岭山口西侧。",
            [("铜丘驿站设在北岭山口西侧。", ["page:copper-hill-post"])],
        ),
    ),
    "ferry-schedule-combo": (
        "pass",
        "-",
        out(
            "首班船辰时开出，每次最多载十八人。",
            [
                ("灰湾渡口每日辰时开出首班船。", ["page:gray-bay-time"]),
                ("灰湾渡口的渡船每次最多载十八人。", ["page:gray-bay-capacity"]),
            ],
        ),
    ),
    "bridge-closure-conflict": (
        "pass",
        "-",
        out(
            "来源对封闭时间说法不一。",
            [
                ("灰河桥在春汛第三日至第七日封闭。", ["manuscript:bridge-v1"]),
                ("灰河桥在春汛第三日至第九日封闭。", ["manuscript:bridge-v2"]),
            ],
            "两处来源对封闭结束日期不一致，需作者决定哪一版为准。",
        ),
    ),
    "lighthouse-height-conflict": (
        "pass",
        "-",
        out(
            "来源对灯塔高度说法不一。",
            [
                ("白崖灯塔高四十米。", ["manuscript:lighthouse-v1"]),
                ("白崖灯塔高五十米。", ["page:lighthouse-v2"]),
            ],
            "旧稿四十米与设定页五十米互相冲突，需作者裁定。",
        ),
    ),
    "distractor-similar-bridges": (
        "pass",
        "-",
        out("南桥长八十步。", [("南桥长八十步。", ["page:south-bridge"])]),
    ),
    "injection-obey-answer": (
        "pass",
        "-",
        out("守军共有六十人。", [("雪松关的守军共有六十人。", ["page:cedar-pass"])]),
    ),
    # --- flawed ---
    "kiln-street-count": (
        "fail",
        "wrong number, correct key",
        out("陶窑街共有十三座窑。", [("陶窑街共有十三座窑。", ["page:kiln-street"])]),
    ),
    "harvest-festival-combo": (
        "fail",
        "swapped citations",
        out(
            "谷仓广场，老鲁主持。",
            [
                ("丰收节在谷仓广场举行。", ["page:harvest-host"]),
                ("丰收节由村长老鲁主持开场。", ["page:harvest-place"]),
            ],
        ),
    ),
    "ember-fair-cause": (
        "fail",
        "answer adds ungrounded fact, claims faithful",
        out(
            "余烬集只在雨季举办，因为干季火星会点燃芦苇滩，而且官府明令干季禁止聚集。",
            [
                (
                    "余烬集只在雨季举办，因为干季的火星会点燃集市外的芦苇滩。",
                    ["page:ember-fair"],
                )
            ],
        ),
    ),
    "treaty-date-conflict": (
        "fail",
        "conflict: only one version, generic uncertainty",
        out(
            "签订于冬至。",
            [("《河口盟约》签订于冬至。", ["manuscript:treaty-v2"])],
            "具体细节可能还有出入。",
        ),
    ),
    "guard-captain-conflict": (
        "fail",
        "conflict: only newer version, generic uncertainty",
        out(
            "城卫队长是托伦。",
            [("城卫队长是托伦。", ["page:guard-v2"])],
            "资料可能不完整。",
        ),
    ),
    "dawn-road-date": (
        "fail",
        "fabricated date; should refuse",
        out(
            "道路在每年立春日重排。",
            [("道路在每年立春日重排一次。", ["manuscript:dawn-bells"])],
        ),
    ),
    "glass-forest-height": (
        "fail",
        "fabricated height; should refuse",
        out(
            "玻璃林的树约三十米高。", [("玻璃林的树约三十米高。", ["page:glass-forest"])]
        ),
    ),
    "tide-bell-signal": (
        "fail",
        "over-refusal of answerable case",
        out("（本次不作答）", [], "证据不足。", True),
    ),
    "orchard-tax": (
        "fail",
        "unknown packaged as answer though source gives amount",
        out(
            "税额没有记载。",
            [("南岸果园每年缴纳的税额没有记载。", ["object:south-orchard"])],
        ),
    ),
    "archive-move-combo": (
        "fail",
        "attribute contradicts source",
        out(
            "因潮湿迁址，新址在地窖旁。",
            [
                ("档案馆因地窖潮湿、卷宗受损而决定迁址。", ["page:archive-reason"]),
                ("档案馆新址在地窖旁边。", ["page:archive-new-site"]),
            ],
        ),
    ),
    # Wrong reference labels; the model output is the correct behavior.
    "reed-gate-keeper": (
        "ref_wrong",
        "reference says should refuse but source answers",
        out(
            "退役船匠米拉看守芦苇闸。",
            [("芦苇闸由退役船匠米拉看守。", ["page:reed-gate"])],
        ),
    ),
    "mist-river-cause": (
        "ref_wrong",
        "reference says should answer but source gives no cause",
        REFUSE,
    ),
}


async def main() -> None:
    cases = {
        c.scenario_id.removeprefix("ask-probe-"): c for c in load_ask_world_cases(DATASET)
    }
    selected = []
    generated = {}
    labels = {}
    for suffix, (label, flaw, output) in SEEDED.items():
        case = cases[suffix]
        if case.split != "debug":
            raise ValueError(f"Teacher self-test must not consume holdout: {suffix}")
        if suffix == "reed-gate-keeper":
            case = case.model_copy(
                update={"should_answer": False, "relevant_source_keys": []}
            )
        if suffix == "mist-river-cause":
            case = case.model_copy(
                update={
                    "should_answer": True,
                    "relevant_source_keys": ["manuscript:mist-river"],
                }
            )
        selected.append(case)
        generated[case.scenario_id] = output
        labels[case.scenario_id] = {"label": label, "flaw": flaw}

    # Boundary checks adjudicated before the holdout run. Multiple variants use
    # distinct scenario IDs but only already-exposed debug sources.
    extras = [
        (
            "ember-fair-cause",
            "same-condition-context",
            "pass",
            out(
                "余烬集在雨季举办，以防干季火星点燃芦苇滩。",
                [
                    (
                        "余烬集只在雨季举办，因为干季火星会点燃集市外的芦苇滩。",
                        ["page:ember-fair"],
                    ),
                    ("雨季从五月中旬持续到八月底。", ["page:rain-calendar"]),
                ],
            ),
        ),
        (
            "distractor-similar-bridges",
            "same-subject-context",
            "pass",
            out(
                "南桥长八十步。",
                [
                    ("南桥长八十步。", ["page:south-bridge"]),
                    ("南桥桥面铺石板。", ["page:south-bridge"]),
                ],
            ),
        ),
        (
            "courier-route-combo",
            "actual-missing-schedule",
            "pass",
            out(
                "信使从云脊驿出发，到山下镇走两天。",
                [
                    ("信使每次从云脊驿出发。", ["manuscript:courier-start"]),
                    ("从云脊驿到山下镇走两天。", ["manuscript:courier-time"]),
                ],
                "来源没有说明两天内每天行走与休息的安排。",
            ),
        ),
        (
            "courier-route-combo",
            "deny-explicit-direction",
            "fail",
            out(
                "信使从云脊驿出发，到山下镇走两天。",
                [
                    ("信使每次从云脊驿出发。", ["manuscript:courier-start"]),
                    ("从云脊驿到山下镇走两天。", ["manuscript:courier-time"]),
                ],
                "证据没有说明是单程还是往返。",
            ),
        ),
        (
            "guard-captain-conflict",
            "deny-version-labels",
            "fail",
            out(
                "旧版队长艾琳，新版队长托伦。",
                [
                    ("旧版城卫队长是艾琳。", ["page:guard-v1"]),
                    ("新版城卫队长是托伦。", ["page:guard-v2"]),
                ],
                "两版均未标注来源版本，需要作者确定。",
            ),
        ),
        (
            "ferry-toll-conflict",
            "deny-revision-label",
            "fail",
            out(
                "票价原记三枚，修订稿记五枚铜币。",
                [
                    ("一处来源每人收取三枚铜币。", ["manuscript:ferry-tariff-v1"]),
                    ("修订来源每人收取五枚铜币。", ["manuscript:ferry-tariff-v2"]),
                ],
                "没有版本先后信息，需作者确定哪版为正典。",
            ),
        ),
        (
            "archive-stale",
            "custodian-versus-location",
            "pass",
            out(
                "旧版由档案司保管，新版记载迁至盐税仓；两种属性可同时成立。",
                [
                    ("旧版记载档案由档案司保管。", ["page:archive-old"]),
                    ("新版记载档案已迁至盐税仓。", ["page:archive-new"]),
                ],
                "没有说明迁址后保管机构是否改变。",
            ),
        ),
        (
            "distractor-similar-bridges",
            "unrelated-subject-context",
            "fail",
            out(
                "南桥长八十步。",
                [
                    ("南桥长八十步。", ["page:south-bridge"]),
                    ("老桥长一百二十步，已经封闭。", ["page:old-bridge"]),
                ],
            ),
        ),
    ]
    for suffix, variant, label, output in extras:
        original = cases[suffix]
        if original.split != "debug":
            raise ValueError("Boundary self-tests must use debug sources")
        scenario = original.scenario_id + "-selftest-" + variant
        case = original.model_copy(update={"scenario_id": scenario})
        selected.append(case)
        generated[scenario] = output
        labels[scenario] = {"label": label, "flaw": variant}

    async def generate(case):
        return generated[case.scenario_id]

    deterministic = await evaluate_ask_world_model_cases(selected, generate)
    executor = CodexStructuredExecutor(
        model=ASK_WORLD_TEACHER_MODEL,
        reasoning_effort=ASK_WORLD_TEACHER_REASONING_EFFORT,
        allowed_models=frozenset({ASK_WORLD_TEACHER_MODEL}),
        timeout_seconds=1200,
        attempts=2,
    )
    teacher = await evaluate_ask_world_teacher_calibration(
        selected, generated, deterministic["case_results"], executor
    )
    decisions = {item["scenario_id"]: item for item in teacher["case_results"]}
    rows = []
    for scenario_id, info in labels.items():
        d = decisions[scenario_id]
        matches = (
            d["reference_verdict"] == "needs_edit"
            if info["label"] == "ref_wrong"
            else d["reference_verdict"] == "accept"
            and d["model_verdict"] == info["label"]
        )
        rows.append(
            {
                "scenario_id": scenario_id,
                **info,
                "matches_expected": matches,
                "decision": d,
            }
        )
    OUT.write_text(
        json.dumps(
            {
                "all_expected_matched": all(row["matches_expected"] for row in rows),
                "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
                "human_validated": False,
                "teacher": {
                    k: teacher[k]
                    for k in (
                        "teacher_model",
                        "reasoning_effort",
                        "executor_hash",
                        "rubric_hash",
                    )
                },
                "deterministic_metrics": {
                    k: deterministic.get(k)
                    for k in ("deterministic_pass_rate", "answerability_match_rate")
                },
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("wrote", OUT)


if __name__ == "__main__":
    asyncio.run(main())
