"""Static contracts for repository-level security automation."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CODEQL_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/codeql.yml"
DEPENDABOT_CONFIG = REPOSITORY_ROOT / ".github/dependabot.yml"
CHECKOUT_SHA = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
CODEQL_SHA = "d1ba80a13dd99fba24a470575428917156a28b43"
CODEQL_SCHEDULE = "17 2 * * 0"
DEPENDABOT_SCHEDULES = {
    "github-actions": ("/", "monday", "02:10"),
    "uv": ("/backend", "tuesday", "02:20"),
    "npm": ("/frontend-console", "wednesday", "02:30"),
    "docker": (["/backend", "/frontend-console"], "thursday", "02:40"),
    "docker-compose": ("/deploy", "friday", "02:50"),
}


def _load_yaml(path: Path) -> dict[str, object]:
    """Preserve GitHub's YAML 1.2 ``on`` key despite PyYAML's YAML 1.1 resolver."""
    value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _workflow_uses(workflow: dict[str, object]) -> list[str]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    analyze = jobs["analyze"]
    assert isinstance(analyze, dict)
    steps = analyze["steps"]
    assert isinstance(steps, list)
    return [
        step["uses"]
        for step in steps
        if isinstance(step, dict) and "uses" in step
    ]


def test_codeql_workflow_uses_least_privilege_matrix_analysis() -> None:
    workflow = _load_yaml(CODEQL_WORKFLOW)

    assert workflow["name"] == "CodeQL"
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert "pull_request_target" not in triggers
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert triggers["push"] == {"branches": ["main"]}
    assert triggers["schedule"] == [{"cron": CODEQL_SCHEDULE}]
    assert triggers["workflow_dispatch"] == ""
    assert workflow["permissions"] == {}

    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency == {
        "group": "codeql-${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    }

    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"analyze"}
    analyze = jobs["analyze"]
    assert isinstance(analyze, dict)
    assert analyze["name"] == "CodeQL (${{ matrix.language }})"
    assert analyze["runs-on"] == "ubuntu-24.04"
    assert analyze["timeout-minutes"] == "30"
    assert analyze["permissions"] == {
        "actions": "read",
        "contents": "read",
        "packages": "read",
        "security-events": "write",
    }

    strategy = analyze["strategy"]
    assert isinstance(strategy, dict)
    assert strategy["fail-fast"] == "false"
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict)
    assert matrix == {
        "language": ["actions", "javascript-typescript", "python"],
        "build-mode": ["none"],
    }

    uses = _workflow_uses(workflow)
    assert uses == [
        f"actions/checkout@{CHECKOUT_SHA}",
        f"github/codeql-action/init@{CODEQL_SHA}",
        f"github/codeql-action/analyze@{CODEQL_SHA}",
    ]
    assert len(uses) == len(set(uses)) == 3
    for reference in uses:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference)

    workflow_text = CODEQL_WORKFLOW.read_text(encoding="utf-8")
    expected_action_lines = [
        f"uses: actions/checkout@{CHECKOUT_SHA} # v7.0.0",
        f"uses: github/codeql-action/init@{CODEQL_SHA} # v4.37.5",
        f"uses: github/codeql-action/analyze@{CODEQL_SHA} # v4.37.5",
    ]
    for expected_line in expected_action_lines:
        assert len(
            re.findall(rf"^\s*{re.escape(expected_line)}$", workflow_text, re.MULTILINE)
        ) == 1

    steps = analyze["steps"]
    assert isinstance(steps, list)
    init = next(step for step in steps if step.get("name") == "Initialize CodeQL")
    assert init["with"] == {
        "languages": "${{ matrix.language }}",
        "build-mode": "${{ matrix.build-mode }}",
        "queries": "security-extended",
    }
    analyze_step = next(
        step for step in steps if step.get("name") == "Analyze CodeQL database"
    )
    assert analyze_step["with"] == {"category": "/language:${{ matrix.language }}"}


def test_dependabot_updates_are_scoped_staggered_and_reviewable() -> None:
    config = _load_yaml(DEPENDABOT_CONFIG)

    assert config["version"] == "2"
    updates = config["updates"]
    assert isinstance(updates, list)
    assert len(updates) == len(DEPENDABOT_SCHEDULES)
    by_ecosystem = {entry["package-ecosystem"]: entry for entry in updates}
    assert set(by_ecosystem) == set(DEPENDABOT_SCHEDULES)

    observed_times: set[str] = set()
    for ecosystem, (directory, day, time) in DEPENDABOT_SCHEDULES.items():
        entry = by_ecosystem[ecosystem]
        assert (entry.get("directory") or entry.get("directories")) == directory
        assert entry["open-pull-requests-limit"] == "3"
        assert set(entry) == {
            "package-ecosystem",
            "directory" if isinstance(directory, str) else "directories",
            "schedule",
            "open-pull-requests-limit",
            "groups",
        }
        assert entry["schedule"] == {
            "interval": "weekly",
            "day": day,
            "time": time,
            "timezone": "Asia/Shanghai",
        }
        observed_times.add(time)
        assert entry["groups"] == {
            "minor-and-patch": {
                "patterns": ["*"],
                "update-types": ["minor", "patch"],
            }
        }

    assert len(observed_times) == len(DEPENDABOT_SCHEDULES)
