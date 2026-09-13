"""Exact synthetic counterexamples; not an LLM or novel-comprehension benchmark."""

from hashlib import sha256
from itertools import permutations, product
import json
from pathlib import Path


CASES = tuple(product((False, True), repeat=3))  # red seal, low tide, guarantor
ALL_RULES = frozenset(range(1 << len(CASES)))


def answer(rule, case):
    return bool(rule & (1 << CASES.index(case)))


def encode_rule(predicate):
    return sum(1 << index for index, case in enumerate(CASES) if predicate(*case))


SEAL_RULE = encode_rule(lambda red, low, guarantor: red)
CONDITIONAL_RULE = encode_rule(lambda red, low, guarantor: low and guarantor)


def consistent(observations):
    candidates = ALL_RULES
    for case, result in observations:
        candidates = frozenset(
            rule for rule in candidates if answer(rule, case) == result
        )
    return candidates


def self_check():
    early = (
        ((True, True, True), True),
        ((False, False, True), False),
        ((False, True, False), False),
    )
    later = (((True, False, True), False), ((False, True, True), True))
    before, after = consistent(early), consistent(early + later)
    assert SEAL_RULE in before and CONDITIONAL_RULE in before
    assert len(before) == 32 and len(after) == 8
    assert SEAL_RULE not in after and CONDITIONAL_RULE in after
    undecided = [case for case in CASES if len({answer(r, case) for r in after}) > 1]
    assert len(undecided) == 3

    # Exact, lossless updates commute in this fixed-rule, noiseless toy world.
    final_states = {consistent(order) for order in permutations(early + later)}
    assert len(final_states) == 1 and next(iter(final_states)) == after

    # A fixed generic table and a bit vector represent the same finite functions.
    # This does not assert equal token costs or equal LLM usability.
    equivalent_queries = 0
    for rule in ALL_RULES:
        table = [dict(red=r, low=l, guarantor=g, permit=answer(rule, (r, l, g)))
                 for r, l, g in CASES]
        for case in CASES:
            row = next(row for row in table
                       if (row["red"], row["low"], row["guarantor"]) == case)
            assert row["permit"] == answer(rule, case)
            equivalent_queries += 1
    assert equivalent_queries == 2048

    # Same query, different story times and manuscript revisions.
    case = (True, False, True)
    revisions = {
        "original": ((0, SEAL_RULE),),
        "story_change": ((0, SEAL_RULE), (4, CONDITIONAL_RULE)),
        "retcon": ((0, CONDITIONAL_RULE),),
    }

    def historical_answer(revision, story_time):
        applicable = [rule for start, rule in revisions[revision] if start <= story_time]
        return answer(applicable[-1], case)

    timeline = {
        "original_at_time_2": historical_answer("original", 2),
        "story_change_at_time_2": historical_answer("story_change", 2),
        "story_change_at_time_6": historical_answer("story_change", 6),
        "retcon_at_time_2": historical_answer("retcon", 2),
        "archived_original_at_time_2": historical_answer("original", 2),
    }
    assert list(timeline.values()) == [True, True, False, False, True]
    return {
        "experiment": "exact-counterexamples-v1",
        "method": "exhaustive enumeration and assertions; no model calls",
        "rule_space": "all 256 Boolean functions over 3 observable Boolean inputs",
        "identifiability": {
            "early_distinct_observations": len(early),
            "early_consistent_rules": len(before),
            "later_total_distinct_observations": len(early + later),
            "later_consistent_rules": len(after),
            "still_undecided_inputs": undecided,
        },
        "order_control": {"orders_checked": 120, "distinct_final_states": len(final_states)},
        "encoding_control": {"rules_checked": 256, "equivalent_queries": equivalent_queries},
        "version_time_control": timeline,
        "limitations": [
            "Features and hypothesis space are hand-specified, not discovered.",
            "Exact enumeration is lossless and ignores compute or context limits.",
            "No probabilistic prior or noisy evidence is modeled.",
            "No conclusion about LLM quality, schema discovery or literary value follows.",
        ],
    }


if __name__ == "__main__":
    result = self_check()
    result["script_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
