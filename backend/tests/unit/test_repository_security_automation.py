"""Static contracts for repository-level security automation."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CODEQL_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/codeql.yml"
DEPENDABOT_CONFIG = REPOSITORY_ROOT / ".github/dependabot.yml"
BACKEND_CI_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/backend-ci.yml"
CHECKOUT_SHA = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
TRIVY_ACTION_SHA = "ed142fd0673e97e23eac54620cfb913e5ce36c25"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
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
    return [step["uses"] for step in steps if isinstance(step, dict) and "uses" in step]


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
        assert (
            len(
                re.findall(
                    rf"^\s*{re.escape(expected_line)}$", workflow_text, re.MULTILINE
                )
            )
            == 1
        )

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


def test_production_image_contract_emits_sboms_before_vulnerability_gates() -> None:
    workflow = _load_yaml(BACKEND_CI_WORKFLOW)

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
        if isinstance(step, dict)
        and step.get("uses") == f"aquasecurity/trivy-action@{TRIVY_ACTION_SHA}"
    ]
    assert len(trivy_steps) == 4
    observed_trivy_uses = [
        step["uses"]
        for step in steps
        if isinstance(step, dict)
        and isinstance(step.get("uses"), str)
        and step["uses"].startswith("aquasecurity/trivy-action@")
    ]
    assert (
        observed_trivy_uses
        == [
            f"aquasecurity/trivy-action@{TRIVY_ACTION_SHA}",
        ]
        * 4
    )
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
    assert upload["uses"] == f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}"
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

    workflow_text = BACKEND_CI_WORKFLOW.read_text(encoding="utf-8")
    production_job_text = workflow_text.split(
        "\n  production-image-contract:\n", maxsplit=1
    )[1]
    trivy_action = f"uses: aquasecurity/trivy-action@{TRIVY_ACTION_SHA} # v0.36.0"
    upload_action = f"uses: actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v6.0.0"
    assert production_job_text.count(trivy_action) == 4
    assert production_job_text.count(upload_action) == 1
