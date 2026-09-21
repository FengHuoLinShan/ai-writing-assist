from itertools import permutations

import pytest

from infrastructure.llm.collaboration_v2 import ready_items


@pytest.mark.parametrize(
    "order", list(permutations(("failed", "child", "leaf", "summary")))
)
def test_all_terminal_summary_survives_transitive_failure(order):
    rows = {
        "failed": {
            "key": "failed",
            "dependencies": [],
            "status": "failed",
            "dependency_policy": "all_succeeded",
        },
        "child": {
            "key": "child",
            "dependencies": ["failed"],
            "status": "pending",
            "dependency_policy": "all_succeeded",
        },
        "leaf": {
            "key": "leaf",
            "dependencies": ["child"],
            "status": "pending",
            "dependency_policy": "all_succeeded",
        },
        "summary": {
            "key": "summary",
            "dependencies": ["leaf"],
            "status": "pending",
            "dependency_policy": "all_terminal",
        },
    }
    assert ready_items([rows[key] for key in order]) == ["summary"]
    assert rows["child"]["status"] == rows["leaf"]["status"] == "blocked"
