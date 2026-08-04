"""Static contract for the automated frontend browser smoke workflow."""

from __future__ import annotations

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/backend-ci.yml"
CHECKOUT_SHA = "9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
SETUP_UV_SHA = "08807647e7069bb48b6ef5acd8ec9567f424441b"
SETUP_NODE_SHA = "249970729cb0ef3589644e2896645e5dc5ba9c38"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
POSTGRES_IMAGE = (
    "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:"
    "7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38"
)


def _load_workflow() -> dict[str, object]:
    value = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(value, dict)
    return value


def test_frontend_browser_smoke_is_a_pinned_ci_job() -> None:
    workflow = _load_workflow()

    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert list(jobs) == [
        "backend-quality",
        "postgresql-critical",
        "frontend-unit-quality",
        "frontend-browser-smoke",
        "frontend-map-browser",
        "production-image-contract",
    ]
    job = jobs["frontend-browser-smoke"]
    assert isinstance(job, dict)
    assert job["name"] == "Frontend browser smoke"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "25"
    assert "permissions" not in job
    assert "continue-on-error" not in job

    services = job["services"]
    assert isinstance(services, dict)
    health_options = (
        '--health-cmd "pg_isready -U postgres -d ai_writing_browser_e2e_test" '
        "--health-interval 5s --health-timeout 5s --health-retries 12"
    )
    assert services == {
        "postgres": {
            "image": POSTGRES_IMAGE,
            "env": {
                "POSTGRES_DB": "ai_writing_browser_e2e_test",
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": "postgres",
            },
            "ports": ["5432:5432"],
            "options": health_options,
        }
    }
    assert job["env"] == {
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_writing_browser_e2e_test",
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
        "Run frontend browser smoke",
        "Upload frontend browser smoke diagnostics",
    ]
    by_name = {step["name"]: step for step in steps if isinstance(step, dict)}
    assert by_name["Check out repository"]["uses"] == f"actions/checkout@{CHECKOUT_SHA}"
    assert by_name["Install uv and Python"] == {
        "name": "Install uv and Python",
        "uses": f"astral-sh/setup-uv@{SETUP_UV_SHA}",
        "with": {
            "version": "0.11.28",
            "python-version": "3.12.13",
            "enable-cache": "true",
            "cache-dependency-glob": "backend/uv.lock",
        },
    }
    assert by_name["Install Node.js"] == {
        "name": "Install Node.js",
        "uses": f"actions/setup-node@{SETUP_NODE_SHA}",
        "with": {
            "node-version-file": "frontend-console/.node-version",
            "cache": "npm",
            "cache-dependency-path": "frontend-console/package-lock.json",
        },
    }
    assert by_name["Install locked backend dependencies"]["run"] == (
        "uv sync --project backend --locked --extra ci"
    )
    assert by_name["Install locked frontend dependencies"]["run"] == (
        "npm --prefix frontend-console ci"
    )
    assert by_name["Install Chromium for Playwright"]["run"] == (
        "npm --prefix frontend-console exec playwright -- install --with-deps chromium"
    )
    assert by_name["Run frontend browser smoke"]["run"] == (
        "uv run --project backend --locked --extra ci -- "
        "npm --prefix frontend-console run test:e2e:smoke"
    )
    assert by_name["Upload frontend browser smoke diagnostics"] == {
        "name": "Upload frontend browser smoke diagnostics",
        "if": "failure()",
        "uses": f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}",
        "with": {
            "name": "frontend-browser-smoke-diagnostics",
            "path": "frontend-console/test-results",
            "if-no-files-found": "ignore",
            "include-hidden-files": "true",
            "retention-days": "14",
        },
    }


def test_frontend_map_browser_is_a_pinned_ci_job() -> None:
    workflow = _load_workflow()

    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert list(jobs) == [
        "backend-quality",
        "postgresql-critical",
        "frontend-unit-quality",
        "frontend-browser-smoke",
        "frontend-map-browser",
        "production-image-contract",
    ]
    job = jobs["frontend-map-browser"]
    assert isinstance(job, dict)
    assert job["name"] == "Frontend map browser"
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "25"
    assert "permissions" not in job
    assert "continue-on-error" not in job

    services = job["services"]
    assert isinstance(services, dict)
    health_options = (
        '--health-cmd "pg_isready -U postgres -d ai_writing_map_browser_e2e_test" '
        "--health-interval 5s --health-timeout 5s --health-retries 12"
    )
    assert services == {
        "postgres": {
            "image": POSTGRES_IMAGE,
            "env": {
                "POSTGRES_DB": "ai_writing_map_browser_e2e_test",
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": "postgres",
            },
            "ports": ["5432:5432"],
            "options": health_options,
        }
    }
    assert job["env"] == {
        "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_writing_map_browser_e2e_test",
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
        "Run frontend map browser",
        "Upload frontend map browser diagnostics",
    ]
    by_name = {step["name"]: step for step in steps if isinstance(step, dict)}
    assert by_name["Check out repository"]["uses"] == f"actions/checkout@{CHECKOUT_SHA}"
    assert by_name["Install uv and Python"] == {
        "name": "Install uv and Python",
        "uses": f"astral-sh/setup-uv@{SETUP_UV_SHA}",
        "with": {
            "version": "0.11.28",
            "python-version": "3.12.13",
            "enable-cache": "true",
            "cache-dependency-glob": "backend/uv.lock",
        },
    }
    assert by_name["Install Node.js"] == {
        "name": "Install Node.js",
        "uses": f"actions/setup-node@{SETUP_NODE_SHA}",
        "with": {
            "node-version-file": "frontend-console/.node-version",
            "cache": "npm",
            "cache-dependency-path": "frontend-console/package-lock.json",
        },
    }
    assert by_name["Install locked backend dependencies"]["run"] == (
        "uv sync --project backend --locked --extra ci"
    )
    assert by_name["Install locked frontend dependencies"]["run"] == (
        "npm --prefix frontend-console ci"
    )
    assert by_name["Install Chromium for Playwright"]["run"] == (
        "npm --prefix frontend-console exec playwright -- install --with-deps chromium"
    )
    assert by_name["Run frontend map browser"]["run"] == (
        "uv run --project backend --locked --extra ci -- "
        "npm --prefix frontend-console run test:e2e:map"
    )
    assert by_name["Upload frontend map browser diagnostics"] == {
        "name": "Upload frontend map browser diagnostics",
        "if": "failure()",
        "uses": f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}",
        "with": {
            "name": "frontend-map-browser-diagnostics",
            "path": "frontend-console/test-results",
            "if-no-files-found": "ignore",
            "include-hidden-files": "true",
            "retention-days": "14",
        },
    }
