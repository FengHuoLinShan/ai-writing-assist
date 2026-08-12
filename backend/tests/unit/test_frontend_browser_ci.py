"""Static contract for the automated frontend browser regression."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/frontend-ci.yml"
POSTGRES_IMAGE = (
    "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:"
    "7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38"
)
WORKFLOW_DATABASE_PASSWORD = "${{ github.run_id }}"


def _load_workflow() -> dict[str, object]:
    value = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def _assert_pinned_action(step: dict[str, object], action: str) -> None:
    reference = step.get("uses")
    assert isinstance(reference, str)
    assert re.fullmatch(rf"{re.escape(action)}@[0-9a-f]{{40}}", reference)


def _assert_action_step(
    step: dict[str, object],
    action: str,
    expected_without_uses: dict[str, object],
) -> None:
    _assert_pinned_action(step, action)
    assert {key: value for key, value in step.items() if key != "uses"} == (
        expected_without_uses
    )


def test_frontend_functional_browser_is_the_only_pinned_browser_ci_job() -> None:
    workflow = _load_workflow()

    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert list(jobs) == [
        "frontend-unit-quality",
        "frontend-functional-browser",
    ]
    job = jobs["frontend-functional-browser"]
    assert isinstance(job, dict)
    assert job["name"] == "Frontend functional browser"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "30"
    assert "permissions" not in job
    assert "continue-on-error" not in job

    services = job["services"]
    assert isinstance(services, dict)
    health_options = (
        '--health-cmd "pg_isready -U postgres -d ai_writing_functional_browser_e2e_test" '
        "--health-interval 5s --health-timeout 5s --health-retries 12"
    )
    assert services == {
        "postgres": {
            "image": POSTGRES_IMAGE,
            "env": {
                "POSTGRES_DB": "ai_writing_functional_browser_e2e_test",
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": WORKFLOW_DATABASE_PASSWORD,
            },
            "ports": ["5432:5432"],
            "options": health_options,
        }
    }
    assert job["env"] == {
        "DATABASE_URL": (
            f"postgresql+asyncpg://postgres:{WORKFLOW_DATABASE_PASSWORD}"
            "@127.0.0.1:5432/ai_writing_functional_browser_e2e_test"
        ),
        "PW_REUSE_EXISTING_SERVER": "0",
        "BACKEND_PORT": "8000",
        "FRONTEND_PORT": "8080",
        "CI": "true",
    }

    steps = job["steps"]
    assert isinstance(steps, list)
    assert [step["name"] for step in steps if isinstance(step, dict)] == [
        "Check out repository",
        "Install uv and Python",
        "Install Node.js",
        "Install locked backend dependencies",
        "Install locked frontend dependencies",
        "Install Chromium for Playwright",
        "Run frontend functional browser",
        "Upload frontend functional browser diagnostics",
    ]
    by_name = {step["name"]: step for step in steps if isinstance(step, dict)}
    _assert_pinned_action(by_name["Check out repository"], "actions/checkout")
    _assert_action_step(
        by_name["Install uv and Python"],
        "astral-sh/setup-uv",
        {
            "name": "Install uv and Python",
            "with": {
                "version": "0.11.28",
                "python-version": "3.14.6",
                "enable-cache": "true",
                "prune-cache": "true",
                "cache-dependency-glob": "backend/uv.lock",
            },
        },
    )
    _assert_action_step(
        by_name["Install Node.js"],
        "actions/setup-node",
        {
            "name": "Install Node.js",
            "with": {
                "node-version-file": "frontend-console/.node-version",
                "cache": "npm",
                "cache-dependency-path": "frontend-console/package-lock.json",
            },
        },
    )
    assert by_name["Install locked backend dependencies"]["run"] == (
        "uv sync --project backend --locked --extra ci"
    )
    assert by_name["Install locked frontend dependencies"]["run"] == (
        "npm --prefix frontend-console ci"
    )
    assert by_name["Install Chromium for Playwright"]["run"] == (
        "npm --prefix frontend-console exec playwright -- install --with-deps chromium"
    )
    assert by_name["Run frontend functional browser"]["run"] == (
        "uv run --project backend --locked --extra ci -- "
        "npm --prefix frontend-console run test:e2e:functional -- --workers=1 --retries=0"
    )
    _assert_action_step(
        by_name["Upload frontend functional browser diagnostics"],
        "actions/upload-artifact",
        {
            "name": "Upload frontend functional browser diagnostics",
            "if": "failure()",
            "with": {
                "name": "frontend-functional-browser-diagnostics",
                "path": "frontend-console/test-results",
                "if-no-files-found": "ignore",
                "include-hidden-files": "true",
                "retention-days": "14",
            },
        },
    )
