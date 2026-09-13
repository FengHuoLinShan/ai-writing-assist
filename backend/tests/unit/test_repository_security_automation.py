"""Static contracts for repository-level security automation."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CODEQL_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/codeql.yml"
DEPENDABOT_CONFIG = REPOSITORY_ROOT / ".github/dependabot.yml"
LICENSE_FILE = REPOSITORY_ROOT / "LICENSE"
SECURITY_POLICY = REPOSITORY_ROOT / "SECURITY.md"
PRODUCTION_IMAGE_CI_WORKFLOW = (
    REPOSITORY_ROOT / ".github/workflows/production-image-ci.yml"
)
SPLIT_WORKFLOW_CONTRACTS = {
    REPOSITORY_ROOT / ".github/workflows/backend-ci.yml": {
        "backend-quality", "postgresql-critical",
    },
    REPOSITORY_ROOT / ".github/workflows/frontend-ci.yml": {
        "frontend-unit-quality", "frontend-functional-browser",
    },
    PRODUCTION_IMAGE_CI_WORKFLOW: {"production-image-contract"},
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

    for path, expected_jobs in SPLIT_WORKFLOW_CONTRACTS.items():
        workflow = _load_yaml(path)
        assert workflow["on"] == {
            "pull_request": "",
            "push": {"branches": ["main"]},
        }
        assert workflow["permissions"] == {"contents": "read"}
        assert workflow["concurrency"]["cancel-in-progress"] == "true"
        concurrency_group = workflow["concurrency"]["group"]
        jobs = workflow["jobs"]
        assert isinstance(jobs, dict)
        assert set(expected_jobs) <= set(jobs)
        observed_groups.add(concurrency_group)

    assert len(observed_groups) == len(SPLIT_WORKFLOW_CONTRACTS)


def test_frontend_browser_gate_keeps_its_independent_risk_contract() -> None:
    workflow = _load_yaml(REPOSITORY_ROOT / ".github/workflows/frontend-ci.yml")
    job = workflow["jobs"]["frontend-functional-browser"]

    postgres = job["services"]["postgres"]
    database_name = postgres["env"]["POSTGRES_DB"]
    assert "agent_e2e" in database_name
    assert job["env"]["DATABASE_URL"].endswith(f"/{database_name}")
    assert job["env"]["PW_REUSE_EXISTING_SERVER"] == "0"
    assert job["env"]["WORLD_OBJECT_S3_BUCKET"] == "ai-writing-assist-world-objects"

    steps = {step["name"]: step for step in job["steps"]}
    assert steps["Start local object storage"]["run"] == (
        "docker compose up --detach --wait minio"
    )
    assert steps["Initialize private object buckets"]["run"] == (
        "docker compose run --rm --no-deps minio-init"
    )
    assert steps["Run frontend functional browser"]["run"].endswith(
        'npm --prefix frontend-console run "$BROWSER_SUITE" -- --workers=1 --retries=0'
    )
    assert steps["Run frontend functional browser"]["env"]["BROWSER_SUITE"] == (
        "${{ steps.changes.outputs.browser_suite }}"
    )
    assert steps[
        "Run assistant behavior with its isolated synthetic model harness"
    ]["run"].endswith(
        "npm --prefix frontend-console run test:e2e:assistant -- --workers=1 --retries=0"
    )
    assert steps["Upload frontend functional browser diagnostics"]["if"] == (
        "failure() && steps.changes.outputs.browser == 'true'"
    )


def test_frontend_unit_gate_lints_before_tests_without_duplicate_build() -> None:
    workflow = _load_yaml(REPOSITORY_ROOT / ".github/workflows/frontend-ci.yml")
    steps = workflow["jobs"]["frontend-unit-quality"]["steps"]
    commands = [step.get("run") for step in steps]

    lint_index = commands.index("npm run lint")
    assert lint_index < commands.index("npm test")
    assert "npm run build" not in commands


def test_ask_world_report_is_written_to_the_uploaded_backend_path() -> None:
    workflow = _load_yaml(REPOSITORY_ROOT / ".github/workflows/backend-ci.yml")
    steps = {step["name"]: step for step in workflow["jobs"]["backend-quality"]["steps"]}

    ask_world = steps["Ask World offline launch gate (non-blocking diagnostic)"]
    assert ask_world["run"].endswith("OUTPUT=evals/artifacts/ask-world-gate.json")
    assert steps["Upload Ask World gate report"]["with"]["path"] == (
        "backend/evals/artifacts/ask-world-gate.json"
    )


def test_codeql_workflow_uses_least_privilege_matrix_analysis() -> None:
    workflow = _load_yaml(CODEQL_WORKFLOW)

    assert workflow["name"] == "CodeQL"
    triggers = workflow["on"]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"pull_request", "push", "schedule", "workflow_dispatch"}
    assert "pull_request_target" not in triggers
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert triggers["push"] == {"branches": ["main"]}
    assert triggers["schedule"] and all("cron" in entry for entry in triggers["schedule"])
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


def test_dependabot_keeps_ecosystems_and_major_upgrades_reviewable() -> None:
    config = _load_yaml(DEPENDABOT_CONFIG)
    assert config["version"] == "2"
    by_ecosystem = {entry["package-ecosystem"]: entry for entry in config["updates"]}
    assert {"github-actions", "uv", "npm", "docker", "docker-compose"} <= set(
        by_ecosystem
    )
    for entry in by_ecosystem.values():
        assert entry.get("directory") or entry.get("directories")
        assert entry["schedule"]["interval"] in {"daily", "weekly", "monthly"}
        for group in entry.get("groups", {}).values():
            assert set(group["update-types"]) <= {"minor", "patch"}
            assert group["update-types"]


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
        "Classify CI changes",
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


def test_ci_selection_keeps_required_jobs_and_fails_closed() -> None:
    gates = {
        "backend-quality": "backend",
        "postgresql-critical": "postgresql",
        "frontend-unit-quality": "frontend",
        "frontend-functional-browser": "browser",
        "production-image-contract": "images",
    }
    for path in SPLIT_WORKFLOW_CONTRACTS:
        for job_id, job in _load_yaml(path)["jobs"].items():
            assert "if" not in job
            steps = job["steps"]
            assert steps[0]["with"]["fetch-depth"] == "0"
            classify = steps[1]
            assert classify == {
                "name": "Classify CI changes",
                "id": "changes",
                "working-directory": "${{ github.workspace }}",
                "run": "python3 scripts/classify_ci_changes.py",
            }
            for step in steps[2:]:
                if step["name"] == "Check repository secret hygiene":
                    assert "if" not in step
                else:
                    assert (
                        f"steps.changes.outputs.{gates[job_id]} == 'true'" in step["if"]
                    )
                    assert "continue-on-error" not in step or "Ask World" in step["name"]
                if "Ask World" in step["name"]:
                    assert "github.event_name == 'push'" in step["if"]
