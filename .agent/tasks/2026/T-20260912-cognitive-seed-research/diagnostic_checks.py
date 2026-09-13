"""Exhaustive interventions on hand-defined mechanisms, never LLM quality scores."""

from hashlib import sha256
from itertools import combinations, product
import json
from pathlib import Path


CASES = tuple(product((False, True), repeat=3))
ORACLE_AND = (False, False, False, True, False, False, False, True)
ORACLE_INSUFFICIENT = (None, False, False, None, None, None, None, True)
EDITS = {
    "refresh_memory": "content",
    "refresh_retrieval": "retrieval",
    "expand_representation": "representation",
    "repair_interpreter": "interpreter",
    "select_revision": "revision",
    "select_story_time": "story_time",
    "respect_source_role": "source_role",
    "preserve_uncertainty": "certainty",
}


def pipeline(faults, edits, inputs, *, insufficient=False):
    """Re-run frozen source through local stages after changing selected mechanisms."""
    active = set(faults) - {EDITS[edit] for edit in edits}
    # Here each selected source has the indicated complete finite truth function.
    rule = "unknown" if insufficient else "and"
    if {"revision", "story_time", "source_role"} & active:
        rule = "seal"
    if "content" in active:
        rule = "seal"
    if "representation" in active and rule == "and":
        rule = "or"
    if "retrieval" in active:
        rule = "seal"
    if "interpreter" in active and rule == "and":
        rule = "or"
    if "certainty" in active and rule == "unknown":
        rule = "seal"

    red, low, guarantor = inputs
    if rule == "seal":
        return red
    if rule == "and":
        return low and guarantor
    if rule == "or":
        return low or guarantor
    # A source observation may be known even when its general rule is not.
    observations = {
        (True, True, True): True,
        (False, False, True): False,
        (False, True, False): False,
    }
    return observations.get(inputs)


def self_check(dataset):
    identifiers = [case["id"] for case in dataset["cases"]]
    assert len(identifiers) == len(set(identifiers)) == 11
    alternatives = [
        frozenset(items)
        for size in range(len(EDITS) + 1)
        for items in combinations(EDITS, size)
    ]
    results = []
    for case in dataset["cases"]:
        insufficient = "certainty" in case["faults"]
        oracle = ORACLE_INSUFFICIENT if insufficient else ORACLE_AND
        baseline = tuple(pipeline(case["faults"], (), x, insufficient=insufficient)
                         for x in CASES)
        minimal, successful = [], 0
        for edits in alternatives:
            outputs = tuple(pipeline(case["faults"], edits, x, insufficient=insufficient)
                            for x in CASES)
            if outputs == oracle:
                successful += 1
                if not any(found <= edits for found in minimal):
                    minimal.append(edits)
        expected = frozenset(case["expected_minimal_edits"])
        assert minimal == [expected], (case["id"], minimal)
        symptom = CASES.index((True, False, True))
        if case["faults"]:
            assert baseline[symptom] is True and oracle[symptom] is not True
        else:
            assert baseline == oracle
        schema_only = tuple(pipeline(case["faults"], ["expand_representation"], x,
                                     insufficient=insufficient) for x in CASES)
        results.append({
            "id": case["id"],
            "baseline_correct_inputs": sum(a is b for a, b in zip(baseline, oracle)),
            "baseline_response_to_shared_question": baseline[symptom],
            "minimum_successful_edits": [sorted(edits) for edits in minimal],
            "successful_edit_combinations": successful,
            "schema_only_restores_all_queries": schema_only == oracle,
        })

    compound_grids = {}
    for compound in dataset["cases"]:
        if len(compound["expected_minimal_edits"]) != 2:
            continue
        first, second = compound["expected_minimal_edits"]
        grid = {}
        for first_on, second_on in product((False, True), repeat=2):
            edits = ([first] if first_on else []) + ([second] if second_on else [])
            outputs = tuple(pipeline(compound["faults"], edits, x) for x in CASES)
            grid[f"{first}={first_on},{second}={second_on}"] = {
                "response_to_shared_question": outputs[CASES.index((True, False, True))],
                "correct_inputs": sum(a is b for a, b in zip(outputs, ORACLE_AND)),
            }
        assert [row["response_to_shared_question"] for row in grid.values()] == [True, True, True, False]
        assert [row["correct_inputs"] for row in grid.values()] == [4, 4, 4, 8]
        compound_grids[compound["id"]] = grid

    # Different internal causes can have identical observable answer functions.
    # One shared action bundle can repair both without resolving their identity.
    pair = dataset["cases"][:2]
    signatures = [tuple(pipeline(case["faults"], (), x) for x in CASES) for case in pair]
    assert signatures[0] == signatures[1]
    shared_minimal = []
    for edits in alternatives:
        if all(tuple(pipeline(case["faults"], edits, x) for x in CASES) == ORACLE_AND
               for case in pair):
            if not any(found <= edits for found in shared_minimal):
                shared_minimal.append(edits)
    assert shared_minimal == [frozenset(("refresh_memory", "refresh_retrieval"))]
    return {
        "experiment": dataset["version"],
        "mechanism_cases": len(results),
        "repair_subsets_per_case": len(alternatives),
        "main_intervention_query_evaluations": len(results) * len(alternatives) * len(CASES),
        "same_wrong_observable_cases": sum(bool(case["faults"]) for case in dataset["cases"]),
        "cases": results,
        "compound_failure_grids": compound_grids,
        "ambiguous_causes_shared_action": {
            "case_ids": [case["id"] for case in pair],
            "identical_answers_over_all_inputs": True,
            "minimal_shared_edits": [sorted(edits) for edits in shared_minimal],
        },
        "limitations": [
            "Mechanisms, diagnosis labels and intervention effects are hand-defined.",
            "The exhaustive repair oracle is evaluator-only, not an autonomous policy.",
            "Each trial replays frozen source; actual migration cost is not measured.",
            "Representation defect is a diagnostic negative case, not a strong baseline.",
            "No LLM, real manuscript, learned schema or user-quality evaluation occurred.",
        ],
    }


if __name__ == "__main__":
    source = Path(__file__).with_name("diagnostic-cases.json")
    result = self_check(json.loads(source.read_text()))
    result["dataset_sha256"] = sha256(source.read_bytes()).hexdigest()
    result["script_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
