"""Verify the actual tracked dev, production and CI initializer environments."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "MINIO_APP_ACCESS_KEY",
    "MINIO_APP_SECRET_KEY",
    "MINIO_BACKUP_ACCESS_KEY",
    "MINIO_BACKUP_SECRET_KEY",
    "MAP_ATLAS_S3_BUCKET",
    "WORLD_OBJECT_S3_BUCKET",
}


def test_every_tracked_yaml_initializer_caller_has_a_separate_backup_identity():
    paths = subprocess.check_output(
        ["git", "ls-files", "*.yml", "*.yaml"], cwd=ROOT, text=True
    ).splitlines()
    callers = {}
    for relative in paths:
        text = (ROOT / relative).read_text()
        if "init-minio.sh" not in text:
            continue
        config = yaml.safe_load(text)
        for name, service in config.get("services", {}).items():
            if "init-minio.sh" in str(service):
                callers[f"{relative}:{name}"] = service["environment"]
        for job_name, job in config.get("jobs", {}).items():
            for step in job.get("steps", []):
                run = step.get("run", "").replace("\\\n", " ")
                for line in run.splitlines():
                    if "init-minio.sh" not in line:
                        continue
                    inline = dict(
                        token.split("=", 1)
                        for token in shlex.split(line)
                        if "=" in token and not token.startswith("--")
                    )
                    callers[f"{relative}:{job_name}:{step['name']}"] = (
                        config.get("env", {})
                        | job.get("env", {})
                        | step.get("env", {})
                        | inline
                    )
    assert "docker-compose.yml:minio-init" in callers
    assert "deploy/compose.production.yml:minio-init" in callers
    assert any(
        name.startswith(".github/workflows/frontend-ci.yml:") for name in callers
    )
    for caller, environment in callers.items():
        assert REQUIRED <= environment.keys(), (caller, REQUIRED - environment.keys())
        assert all(environment[key] for key in REQUIRED), caller
        assert environment["MINIO_BACKUP_ACCESS_KEY"] not in {
            environment["MINIO_ROOT_USER"],
            environment["MINIO_APP_ACCESS_KEY"],
        }, caller
        assert environment["MINIO_BACKUP_SECRET_KEY"] not in {
            environment["MINIO_ROOT_PASSWORD"],
            environment["MINIO_APP_SECRET_KEY"],
        }, caller
