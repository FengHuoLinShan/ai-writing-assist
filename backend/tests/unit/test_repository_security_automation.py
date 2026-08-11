"""Static contracts for repository-level security automation."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CODEQL_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/codeql.yml"
DEPENDABOT_CONFIG = REPOSITORY_ROOT / ".github/dependabot.yml"
LICENSE_FILE = REPOSITORY_ROOT / "LICENSE"
SECURITY_POLICY = REPOSITORY_ROOT / "SECURITY.md"
THIRD_PARTY_LICENSES = REPOSITORY_ROOT / "THIRD_PARTY_LICENSES.md"
FRONTEND_PACKAGE = REPOSITORY_ROOT / "frontend-console/package.json"
PRODUCTION_IMAGE_CI_WORKFLOW = (
    REPOSITORY_ROOT / ".github/workflows/production-image-ci.yml"
)
SPLIT_WORKFLOW_CONTRACTS = {
    REPOSITORY_ROOT / ".github/workflows/backend-ci.yml": (
        "Backend CI",
        "backend-ci-${{ github.ref }}",
        ["backend-quality", "postgresql-critical"],
    ),
    REPOSITORY_ROOT / ".github/workflows/frontend-ci.yml": (
        "Frontend CI",
        "frontend-ci-${{ github.ref }}",
        [
            "frontend-unit-quality",
            "frontend-browser-smoke",
            "frontend-map-browser",
            "frontend-functional-browser",
        ],
    ),
    PRODUCTION_IMAGE_CI_WORKFLOW: (
        "Production Image CI",
        "production-image-ci-${{ github.ref }}",
        ["production-image-contract"],
    ),
}
AUTOMATION_WORKFLOWS = tuple(
    sorted((REPOSITORY_ROOT / ".github/workflows").glob("*.yml"))
)
ALLOWED_ACTIONS = {
    "actions/checkout",
    "actions/setup-node",
    "actions/upload-artifact",
    "aquasecurity/trivy-action",
    "astral-sh/setup-uv",
    "github/codeql-action/analyze",
    "github/codeql-action/init",
}
ACTION_LINE_PATTERN = re.compile(
    r"^\s*uses:\s+(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})"
    r"\s+#\s+(?P<version>v[0-9][0-9A-Za-z.\-]*)\s*$"
)
CODEQL_SCHEDULE = "17 2 * * 0"
DEPENDABOT_SCHEDULES = {
    "github-actions": ("/", "monday", "02:10"),
    "uv": ("/backend", "tuesday", "02:20"),
    "npm": ("/frontend-console", "wednesday", "02:30"),
    "docker": (["/backend", "/frontend-console"], "thursday", "02:40"),
    "docker-compose": ("/deploy", "friday", "02:50"),
}


def test_repository_license_and_private_security_reporting_policy_are_present() -> None:
    license_text = LICENSE_FILE.read_text(encoding="utf-8")
    policy = SECURITY_POLICY.read_text(encoding="utf-8")
    normalized_policy = " ".join(policy.split())

    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 FengHuoLinShan" in license_text
    assert "private vulnerability reporting" in normalized_policy
    assert "three business days" in normalized_policy
    assert "seven business days" in normalized_policy
    assert "Do not open a public issue" in normalized_policy
    assert "LLM API keys" in normalized_policy


def test_leaflet_runtime_license_and_exact_dependency_are_declared() -> None:
    notices = THIRD_PARTY_LICENSES.read_text(encoding="utf-8")
    package = json.loads(FRONTEND_PACKAGE.read_text(encoding="utf-8"))

    assert package["dependencies"]["leaflet"] == "1.9.4"
    assert "Leaflet | 1.9.4 | BSD-2-Clause" in notices
    assert "/licenses/leaflet-BSD-2-Clause.txt" in notices


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
    return [step["uses"] for step in steps if isinstance(step, dict) and "uses" in step]


def _action_name(step: dict[str, object]) -> str | None:
    reference = step.get("uses")
    if not isinstance(reference, str):
        return None
    return reference.partition("@")[0]


def _workflow_action_lines(path: Path) -> list[tuple[str, str, str]]:
    action_lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if "uses:" in line
    ]
    parsed: list[tuple[str, str, str]] = []
    for line in action_lines:
        match = ACTION_LINE_PATTERN.fullmatch(line)
        assert match is not None, f"unpinned or uncommented action in {path}: {line}"
        parsed.append((match["action"], match["sha"], match["version"]))
    return parsed


def test_ci_actions_are_allowlisted_fully_pinned_and_consistent() -> None:
    observed: dict[str, set[tuple[str, str]]] = {}

    for path in AUTOMATION_WORKFLOWS:
        parsed = _workflow_action_lines(path)
        assert parsed, path
        for action, sha, version in parsed:
            assert action in ALLOWED_ACTIONS
            family = "/".join(action.split("/")[:2])
            observed.setdefault(family, set()).add((sha, version))

    inconsistent = {
        family: sorted(references)
        for family, references in observed.items()
        if len(references) != 1
    }
    assert inconsistent == {}


def test_split_ci_workflows_keep_triggers_permissions_and_unique_concurrency() -> None:
    observed_groups: set[str] = set()

    for path, (
        name,
        concurrency_group,
        expected_jobs,
    ) in SPLIT_WORKFLOW_CONTRACTS.items():
        workflow = _load_yaml(path)
        assert workflow["name"] == name
        assert workflow["on"] == {
            "pull_request": "",
            "push": {"branches": ["main"]},
        }
        assert workflow["permissions"] == {"contents": "read"}
        assert workflow["concurrency"] == {
            "group": concurrency_group,
            "cancel-in-progress": "true",
        }
        jobs = workflow["jobs"]
        assert isinstance(jobs, dict)
        assert list(jobs) == expected_jobs
        observed_groups.add(concurrency_group)

    assert len(observed_groups) == len(SPLIT_WORKFLOW_CONTRACTS)


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
    assert [reference.partition("@")[0] for reference in uses] == [
        "actions/checkout",
        "github/codeql-action/init",
        "github/codeql-action/analyze",
    ]
    assert len(uses) == len(set(uses)) == 3
    for reference in uses:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", reference)

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
        expected_keys = {
            "package-ecosystem",
            "directory" if isinstance(directory, str) else "directories",
            "schedule",
            "open-pull-requests-limit",
            "groups",
        }
        if ecosystem == "docker":
            expected_keys.add("ignore")
        assert set(entry) == expected_keys
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
        if ecosystem == "docker":
            assert entry["ignore"] == [
                {
                    "dependency-name": "python",
                    "update-types": [
                        "version-update:semver-minor",
                        "version-update:semver-major",
                    ],
                },
                {
                    "dependency-name": "node",
                    "update-types": ["version-update:semver-major"],
                },
            ]

    assert len(observed_times) == len(DEPENDABOT_SCHEDULES)


def test_production_image_contract_emits_sboms_before_vulnerability_gates() -> None:
    workflow = _load_yaml(PRODUCTION_IMAGE_CI_WORKFLOW)

    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["production-image-contract"]
    assert isinstance(job, dict)
    assert job["name"] == "Production image contract"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "40"
    assert "permissions" not in job
    assert "continue-on-error" not in job

    steps = job["steps"]
    assert isinstance(steps, list)
    by_name = {
        step["name"]: step
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    }
    ordered_names = [step["name"] for step in steps if isinstance(step, dict)]
    assert ordered_names == [
        "Check out repository",
        "Build and smoke-test production images",
        "Create container SBOM artifact directory",
        "Generate backend image CycloneDX SBOM",
        "Generate frontend image CycloneDX SBOM",
        "Validate generated CycloneDX SBOMs",
        "Upload production image SBOMs",
        "Gate backend image fixable high and critical vulnerabilities",
        "Gate frontend image fixable high and critical vulnerabilities",
    ]
    assert by_name["Build and smoke-test production images"]["run"] == (
        "make test-production-images"
    )
    assert by_name["Create container SBOM artifact directory"]["run"] == (
        "mkdir -p .test-artifacts/container-sbom"
    )

    trivy_steps = [
        step
        for step in steps
        if isinstance(step, dict) and _action_name(step) == "aquasecurity/trivy-action"
    ]
    assert len(trivy_steps) == 4
    observed_trivy_uses = [
        step["uses"]
        for step in steps
        if isinstance(step, dict)
        and isinstance(step.get("uses"), str)
        and step["uses"].startswith("aquasecurity/trivy-action@")
    ]
    assert len(set(observed_trivy_uses)) == 1
    assert all(
        "continue-on-error" not in step for step in steps if isinstance(step, dict)
    )

    expected_sboms = (
        (
            "contract-smoke-backend:fixed-toolchain",
            ".test-artifacts/container-sbom/backend.cdx.json",
            {"version": "v0.73.0"},
        ),
        (
            "contract-smoke-frontend:fixed-toolchain",
            ".test-artifacts/container-sbom/frontend.cdx.json",
            {"skip-setup-trivy": "true"},
        ),
    )
    for step, (image_ref, output, setup) in zip(
        trivy_steps[:2], expected_sboms, strict=True
    ):
        assert step["with"] == {
            **setup,
            "scan-type": "image",
            "image-ref": image_ref,
            "format": "cyclonedx",
            "output": output,
            "scanners": "vuln",
            "vuln-type": "os,library",
            "exit-code": "0",
            "timeout": "10m",
        }

    for step, image_ref in zip(
        trivy_steps[2:],
        (
            "contract-smoke-backend:fixed-toolchain",
            "contract-smoke-frontend:fixed-toolchain",
        ),
        strict=True,
    ):
        assert step["with"] == {
            "skip-setup-trivy": "true",
            "scan-type": "image",
            "image-ref": image_ref,
            "format": "table",
            "scanners": "vuln",
            "vuln-type": "os,library",
            "severity": "HIGH,CRITICAL",
            "ignore-unfixed": "true",
            "exit-code": "1",
            "timeout": "10m",
        }

    validator = by_name["Validate generated CycloneDX SBOMs"]
    validator_script = validator["run"]
    assert "import json" in validator_script
    assert "backend.cdx.json" in validator_script
    assert "frontend.cdx.json" in validator_script
    assert 'document.get("bomFormat") != "CycloneDX"' in validator_script
    assert "not isinstance(components, list) or not components" in validator_script

    upload = by_name["Upload production image SBOMs"]
    assert _action_name(upload) == "actions/upload-artifact"
    assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", upload["uses"])
    assert upload["with"] == {
        "name": "production-image-sboms",
        "path": (
            ".test-artifacts/container-sbom/backend.cdx.json\n"
            ".test-artifacts/container-sbom/frontend.cdx.json\n"
        ),
        "if-no-files-found": "error",
        "include-hidden-files": "true",
        "retention-days": "14",
    }

    action_names = [
        action
        for action, _sha, _version in _workflow_action_lines(PRODUCTION_IMAGE_CI_WORKFLOW)
    ]
    assert action_names.count("aquasecurity/trivy-action") == 4
    assert action_names.count("actions/upload-artifact") == 1
