"""Fail-closed aggregation for the sharded frontend functional browser gate.

Reads the classification and shard job results from the environment and
exits non-zero unless the observed combination is one of the accepted
outcomes in docs/plans/2026-10-04-ci-optimization.md: classification
success without browser need passes with the shard job skipped; browser
runs pass only when every shard job succeeded.
"""

from __future__ import annotations

import os
import sys

JOB_RESULTS = frozenset({"success", "failure", "cancelled", "skipped"})
SUITE_SHARD_PLAN = {
    "test:e2e:functional": ("[1,2]", "2"),
    "test:e2e:smoke": ("[1]", "1"),
}


def aggregate(
    *,
    classify_result: str,
    browser: str,
    browser_suite: str,
    shard_plan: str,
    shard_total: str,
    shard_result: str,
) -> tuple[bool, str]:
    unknown_results = {
        name: value
        for name, value in (
            ("classify_result", classify_result),
            ("shard_result", shard_result),
        )
        if value not in JOB_RESULTS
    }
    if unknown_results:
        return False, f"unknown job result(s): {unknown_results}"
    if browser not in {"true", "false"}:
        return False, f"invalid browser classification output: {browser!r}"
    expected = SUITE_SHARD_PLAN.get(browser_suite)
    if expected is None:
        return False, f"invalid browser_suite output: {browser_suite!r}"
    expected_plan, expected_total = expected
    if shard_plan != expected_plan or shard_total != expected_total:
        return False, (
            f"shard plan {shard_plan!r}/{shard_total!r} does not match "
            f"{browser_suite} expectation {expected_plan!r}/{expected_total!r}"
        )
    if classify_result != "success":
        return False, f"browser classification job result: {classify_result}"
    if browser == "false":
        if shard_result != "skipped":
            return False, (
                "browser gate not required but shard job was not skipped: "
                f"{shard_result}"
            )
        return True, "browser gate not required for this change"
    if shard_result != "success":
        return False, f"browser shard job result: {shard_result}"
    return True, "all required browser suites passed on every shard"


def main() -> int:
    passed, message = aggregate(
        classify_result=os.environ.get("CLASSIFY_RESULT", ""),
        browser=os.environ.get("BROWSER", ""),
        browser_suite=os.environ.get("BROWSER_SUITE", ""),
        shard_plan=os.environ.get("SHARD_PLAN", ""),
        shard_total=os.environ.get("SHARD_TOTAL", ""),
        shard_result=os.environ.get("SHARD_RESULT", ""),
    )
    print(message)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
