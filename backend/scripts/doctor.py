"""Read-only local environment diagnostics for development setup."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import get_settings  # noqa: E402
from infrastructure.llm.health import check_llm_health  # noqa: E402
from infrastructure.llm.redaction import redact_diagnostic  # noqa: E402
from shared.constants import TASK_MAX_HEARTBEAT_GAP  # noqa: E402

Status = str

STATUS_OK = "ok"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"
ALL_GROUPS = ("env", "ports", "docker", "api", "db", "llm_config")
SENSITIVE_KEY_PARTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASS")


@dataclass(frozen=True)
class CheckResult:
    """One machine-readable doctor check result."""

    name: str
    status: Status
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": redact_text(self.message),
            "details": sanitize_value(self.details),
        }


@dataclass(frozen=True)
class DoctorReport:
    """Complete doctor report grouped by subsystem."""

    status: Status
    checks: dict[str, list[CheckResult]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": {
                group: [item.as_dict() for item in results]
                for group, results in self.checks.items()
            },
        }


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse only literal KEY=VALUE pairs from an env file."""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def sanitize_url(value: str) -> str:
    """Hide passwords in URLs while preserving diagnostic host/db information."""

    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "<invalid url>"
    if not parts.netloc:
        return value

    username = parts.username or ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""

    if username:
        userinfo = quote(username, safe="")
        if parts.password is not None:
            userinfo += ":***"
        netloc = f"{userinfo}@{host}{port}"
    else:
        netloc = f"{host}{port}"

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def secret_values_for_redaction() -> list[str]:
    candidates: list[str] = []
    env_values = parse_env_file(ROOT / ".env")
    for source in (env_values, os.environ):
        for key, value in source.items():
            upper = key.upper()
            if not value or len(value) < 4:
                continue
            if any(part in upper for part in SENSITIVE_KEY_PARTS):
                candidates.append(value)
            if upper.endswith("_URL"):
                password = urlsplit(value).password
                if password and len(password) >= 4:
                    candidates.append(password)
    return sorted(set(candidates), key=len, reverse=True)


def redact_text(value: str) -> str:
    redacted = value
    for secret in secret_values_for_redaction():
        redacted = redacted.replace(secret, "<redacted>")
    return redact_diagnostic(redacted)


def sanitize_value(value: Any) -> Any:
    """Recursively remove secret-looking values from diagnostic output."""

    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            upper = str(key).upper()
            if upper == "MISSING_KEYS":
                clean[str(key)] = sanitize_value(item)
            elif any(part in upper for part in SENSITIVE_KEY_PARTS):
                clean[str(key)] = "<redacted>" if item else ""
            else:
                clean[str(key)] = sanitize_value(item)
        return clean
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_env(
    env_path: Path | None = None,
    example_path: Path | None = None,
) -> list[CheckResult]:
    env_path = env_path or ROOT / ".env"
    example_path = example_path or ROOT / ".env.example"
    env_values = parse_env_file(env_path)
    example_values = parse_env_file(example_path)
    results: list[CheckResult] = []

    if env_path.exists():
        results.append(
            CheckResult(
                name="env_file",
                status=STATUS_OK,
                message=".env exists",
                details={"path": display_path(env_path)},
            )
        )
    else:
        results.append(
            CheckResult(
                name="env_file",
                status=STATUS_WARNING,
                message=".env is missing; defaults will be used where available",
                details={"path": display_path(env_path)},
            )
        )

    if example_path.exists():
        missing_keys = sorted(set(example_values) - set(env_values))
        status = STATUS_OK if not missing_keys else STATUS_WARNING
        message = (
            ".env includes every .env.example key"
            if not missing_keys
            else ".env is missing keys from .env.example"
        )
        results.append(
            CheckResult(
                name="env_keys",
                status=status,
                message=message,
                details={
                    "example": display_path(example_path),
                    "missing_keys": missing_keys,
                },
            )
        )
    else:
        results.append(
            CheckResult(
                name="env_example",
                status=STATUS_UNKNOWN,
                message=".env.example not found; key comparison skipped",
                details={"path": display_path(example_path)},
            )
        )

    database_url = env_values.get("DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if database_url:
        results.append(
            CheckResult(
                name="database_url",
                status=STATUS_OK,
                message="DATABASE_URL is configured",
                details={"url": sanitize_url(database_url)},
            )
        )

    app_host = env_values.get("APP_HOST") or os.environ.get("APP_HOST", "")
    if app_host == "0.0.0.0":
        results.append(
            CheckResult(
                name="app_host",
                status=STATUS_WARNING,
                message="APP_HOST is 0.0.0.0; only use this for local dev exposure",
                details={"APP_HOST": app_host},
            )
        )

    return results


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 8,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def find_port_process(port: int) -> dict[str, Any]:
    if shutil.which("lsof") is None:
        return {"available": False, "reason": "lsof not found"}

    try:
        result = run_command(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc)}

    if result.returncode != 0 or not result.stdout.strip():
        return {"available": True, "processes": []}

    processes: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            processes.append({"command": parts[0], "pid": parts[1]})
    return {"available": True, "processes": processes}


def check_ports(ports: dict[int, str] | None = None) -> list[CheckResult]:
    ports = ports or {8000: "backend API", 8080: "frontend console", 5207: "PostgreSQL"}
    results: list[CheckResult] = []
    for port, purpose in ports.items():
        process = find_port_process(port)
        socket_listening = is_port_listening(port)
        lsof_listening = bool(process.get("processes"))
        listening = socket_listening or lsof_listening
        results.append(
            CheckResult(
                name=f"port_{port}",
                status=STATUS_OK if listening else STATUS_WARNING,
                message=(
                    f"{purpose} port {port} is listening"
                    if listening
                    else f"{purpose} port {port} is not listening"
                ),
                details={
                    "port": port,
                    "purpose": purpose,
                    "listening": listening,
                    "socket_listening": socket_listening,
                    "lsof_listening": lsof_listening,
                    "process": process,
                },
            )
        )
    return results


def _permission_denied(text: str) -> bool:
    lowered = text.lower()
    return "permission denied" in lowered or "docker daemon socket" in lowered


def check_docker() -> list[CheckResult]:
    if shutil.which("docker") is None:
        return [
            CheckResult(
                name="docker",
                status=STATUS_UNKNOWN,
                message="docker command not found",
            )
        ]

    try:
        inspect = run_command(["docker", "inspect", "ai-novel-db"], timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [
            CheckResult(
                name="ai_novel_db",
                status=STATUS_UNKNOWN,
                message="docker inspect could not run",
                details={"reason": redact_text(str(exc))},
            )
        ]

    combined = f"{inspect.stdout}\n{inspect.stderr}"
    if _permission_denied(combined):
        return [
            CheckResult(
                name="ai_novel_db",
                status=STATUS_UNKNOWN,
                message="Docker daemon is not readable from this environment",
                details={
                    "reason": redact_text(
                        inspect.stderr.strip() or inspect.stdout.strip()
                    )
                },
            )
        ]

    if inspect.returncode != 0:
        return [
            CheckResult(
                name="ai_novel_db",
                status=STATUS_WARNING,
                message="ai-novel-db container is not inspectable",
                details={"stderr": redact_text(inspect.stderr.strip())},
            )
        ]

    try:
        containers = json.loads(inspect.stdout)
        container = containers[0] if containers else {}
    except json.JSONDecodeError as exc:
        return [
            CheckResult(
                name="ai_novel_db",
                status=STATUS_UNKNOWN,
                message="docker inspect returned invalid JSON",
                details={"reason": str(exc)},
            )
        ]

    state = container.get("State", {})
    health = state.get("Health", {}).get("Status", "")
    labels = container.get("Config", {}).get("Labels", {}) or {}
    mounts = [
        {
            "type": mount.get("Type", ""),
            "name": mount.get("Name", ""),
            "source": mount.get("Source", ""),
            "destination": mount.get("Destination", ""),
        }
        for mount in container.get("Mounts", [])
    ]
    compose_ps = _docker_compose_ps()
    running = bool(state.get("Running"))
    status = STATUS_OK if running and health in {"healthy", ""} else STATUS_WARNING

    return [
        CheckResult(
            name="ai_novel_db",
            status=status,
            message=(
                "ai-novel-db container is running"
                if running
                else "ai-novel-db container is not running"
            ),
            details={
                "running": running,
                "health": health or "not_configured",
                "compose_project": labels.get("com.docker.compose.project", ""),
                "compose_service": labels.get("com.docker.compose.service", ""),
                "mounts": mounts,
                "compose_ps": compose_ps,
            },
        )
    ]


def _docker_compose_ps() -> dict[str, Any]:
    try:
        result = run_command(["docker", "compose", "ps"], cwd=REPO_ROOT, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": STATUS_UNKNOWN, "reason": str(exc)}
    combined = f"{result.stdout}\n{result.stderr}"
    if _permission_denied(combined):
        return {
            "status": STATUS_UNKNOWN,
            "reason": redact_text(result.stderr.strip() or result.stdout.strip()),
        }
    return {
        "status": STATUS_OK if result.returncode == 0 else STATUS_WARNING,
        "output": result.stdout.strip()[-2000:],
        "stderr": redact_text(result.stderr.strip())[-500:],
    }


def check_api(url: str = "http://localhost:8000/api/health") -> list[CheckResult]:
    try:
        with urlopen(url, timeout=3) as response:  # noqa: S310 - local URL only.
            body = response.read().decode("utf-8")
            payload = json.loads(body) if body else {}
            health_status = str(payload.get("status", "")).lower()
            if health_status == "healthy":
                return [
                    CheckResult(
                        name="api_health",
                        status=STATUS_OK,
                        message="Backend API reports healthy",
                        details=payload,
                    )
                ]
            return [
                CheckResult(
                    name="api_health",
                    status=STATUS_ERROR,
                    message="Backend API reports degraded",
                    details=payload,
                )
            ]
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        return [
            CheckResult(
                name="api_health",
                status=STATUS_ERROR,
                message=f"Backend API returned HTTP {exc.code}",
                details={"url": url, "body": body},
            )
        ]
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [
            CheckResult(
                name="api_health",
                status=STATUS_WARNING,
                message="Backend API is unreachable",
                details={"url": url, "reason": redact_text(str(exc))},
            )
        ]


def sync_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    return database_url


def _scalar(connection: Any, sql: str) -> Any:
    from sqlalchemy import text

    return connection.execute(text(sql)).scalar()


def collect_db_counts(execute_scalar: Callable[[str], Any]) -> dict[str, Any]:
    stale_running_sql = f"""
        SELECT count(*)
        FROM async_tasks
        WHERE status = 'running'
          AND (
            heartbeat_at IS NULL
            OR heartbeat_at < now() - interval '{int(TASK_MAX_HEARTBEAT_GAP)} seconds'
          )
    """
    return {
        "projects": int(
            execute_scalar("SELECT count(*) FROM projects WHERE deleted_at IS NULL") or 0
        ),
        "soft_deleted_projects": int(
            execute_scalar("SELECT count(*) FROM projects WHERE deleted_at IS NOT NULL")
            or 0
        ),
        "async_tasks": int(execute_scalar("SELECT count(*) FROM async_tasks") or 0),
        "running_async_tasks": int(
            execute_scalar("SELECT count(*) FROM async_tasks WHERE status = 'running'")
            or 0
        ),
        "stale_running_async_tasks": int(execute_scalar(stale_running_sql) or 0),
        "orphan_task_meta": int(
            execute_scalar(
                """
                SELECT count(*)
                FROM async_tasks t
                LEFT JOIN projects p ON p.id::text = t.meta->>'novel_id'
                WHERE t.meta->>'novel_id' IS NOT NULL
                  AND p.id IS NULL
                """
            )
            or 0
        ),
    }


def read_alembic_heads() -> dict[str, Any]:
    result = run_command(["alembic", "heads"], cwd=ROOT, timeout=8)
    if result.returncode != 0:
        return {
            "status": STATUS_UNKNOWN,
            "stderr": result.stderr.strip(),
            "stdout": result.stdout.strip(),
        }
    heads = [
        line.split()[0]
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("Rev:")
    ]
    return {"status": STATUS_OK, "heads": heads, "raw": result.stdout.strip()}


def db_warning_codes(details: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    alembic_head = details.get("alembic_head", {})
    heads = alembic_head.get("heads", []) if isinstance(alembic_head, dict) else []
    current = details.get("alembic_current")
    if heads and current and current not in heads:
        warnings.append("alembic_current_not_at_head")
    if details.get("stale_running_async_tasks", 0):
        warnings.append("stale_running_async_tasks")
    if details.get("orphan_task_meta", 0):
        warnings.append("orphan_task_meta")
    return warnings


def check_db() -> list[CheckResult]:
    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        return [
            CheckResult(
                name="db",
                status=STATUS_UNKNOWN,
                message="SQLAlchemy is not available",
                details={"reason": str(exc)},
            )
        ]

    settings = get_settings()
    database_url = sync_database_url(settings.database_url)
    details: dict[str, Any] = {
        "database_url": sanitize_url(database_url),
        "alembic_head": read_alembic_heads(),
    }

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            current = connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar()
            details["alembic_current"] = current or ""
            details.update(collect_db_counts(lambda sql: _scalar(connection, sql)))
    except Exception as exc:  # noqa: BLE001 - doctor must continue on any DB issue.
        return [
            CheckResult(
                name="db_summary",
                status=STATUS_WARNING,
                message="Database checks could not complete",
                details={**details, "reason": redact_text(str(exc))},
            )
        ]
    finally:
        if "engine" in locals():
            engine.dispose()

    warnings = db_warning_codes(details)
    details["warnings"] = warnings
    status = STATUS_WARNING if warnings else STATUS_OK
    message = "Database is queryable" if not warnings else "Database has warnings"
    return [
        CheckResult(
            name="db_summary",
            status=status,
            message=message,
            details=details,
        )
    ]


def _configured_value(env_values: dict[str, str], key: str, default: str = "") -> str:
    return env_values.get(key) or os.environ.get(key, default)


def check_llm_config(env_path: Path | None = None) -> list[CheckResult]:
    env_values = parse_env_file(env_path or ROOT / ".env")
    settings = get_settings()
    api_key = _configured_value(env_values, "LLM_API_KEY", settings.llm_api_key)
    base_url = _configured_value(env_values, "LLM_BASE_URL", settings.llm_base_url)
    model = _configured_value(env_values, "LLM_MODEL", settings.llm_model)
    proxy_url = _configured_value(env_values, "LLM_PROXY_URL", settings.llm_proxy_url)
    trust_env = _configured_value(
        env_values,
        "LLM_TRUST_ENV",
        str(settings.llm_trust_env).lower(),
    )

    missing: list[str] = []
    if not api_key or api_key.lower() in {"changeme", "your_api_key", "sk-xxx"}:
        missing.append("LLM_API_KEY")
    if not base_url:
        missing.append("LLM_BASE_URL")
    if not model:
        missing.append("LLM_MODEL")

    status = STATUS_OK if not missing else STATUS_WARNING
    return [
        CheckResult(
            name="llm_config",
            status=status,
            message=(
                "LLM local configuration is present"
                if not missing
                else "LLM local configuration is incomplete"
            ),
            details={
                "missing_or_placeholder": missing,
                "base_url_host": urlsplit(base_url).hostname or "",
                "model": model,
                "trust_env": trust_env,
                "proxy_configured": bool(proxy_url),
                "remote_check": "skipped; run with --llm to contact provider",
            },
        )
    ]


async def check_llm_remote() -> list[CheckResult]:
    try:
        result = await check_llm_health()
    except Exception as exc:  # noqa: BLE001 - doctor must not expose stack traces.
        return [
            CheckResult(
                name="llm_remote",
                status=STATUS_ERROR,
                message="Remote LLM health check failed before receiving a result",
                details={"reason": redact_text(str(exc))},
            )
        ]
    return [
        CheckResult(
            name="llm_remote",
            status=STATUS_OK if result.ok else STATUS_ERROR,
            message=(
                "Remote LLM health check passed"
                if result.ok
                else "Remote LLM health check failed"
            ),
            details=result.model_dump(),
        )
    ]


def compute_status(checks: dict[str, list[CheckResult]]) -> Status:
    statuses = [result.status for results in checks.values() for result in results]
    if STATUS_ERROR in statuses:
        return STATUS_ERROR
    if STATUS_WARNING in statuses:
        return STATUS_WARNING
    if statuses and all(status == STATUS_UNKNOWN for status in statuses):
        return STATUS_UNKNOWN
    return STATUS_OK


async def build_report(include_llm: bool = False) -> DoctorReport:
    checks: dict[str, list[CheckResult]] = {
        "env": check_env(),
        "ports": check_ports(),
        "docker": check_docker(),
        "api": check_api(),
        "db": check_db(),
        "llm_config": check_llm_config(),
    }
    if include_llm:
        checks["llm_remote"] = await check_llm_remote()
    for group in ALL_GROUPS:
        checks.setdefault(group, [])
    return DoctorReport(status=compute_status(checks), checks=checks)


def print_human(report: DoctorReport) -> None:
    print(f"Local Doctor: {report.status.upper()}")
    for group, results in report.checks.items():
        print(f"\n[{group}]")
        for result in results:
            print(f"  {result.status.upper():7} {result.name}: {result.message}")
            for key, value in result.as_dict()["details"].items():
                formatted = json.dumps(value, ensure_ascii=False, sort_keys=True)
                print(f"          {key}: {formatted}")


async def async_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print stable JSON output")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="also contact the configured remote LLM provider",
    )
    args = parser.parse_args(argv)

    report = await build_report(include_llm=args.llm)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 1 if report.status == STATUS_ERROR else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
