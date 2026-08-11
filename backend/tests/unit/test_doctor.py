from __future__ import annotations

import asyncio
import json

from infrastructure.llm.health import LLMHealthResult
from scripts import doctor


def test_env_key_comparison_does_not_leak_values(tmp_path):
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:example-secret@localhost/db",
                "LLM_API_KEY=example-secret",
                "LLM_MODEL=gpt-4o",
                "APP_HOST=127.0.0.1",
            ]
        ),
        encoding="utf-8",
    )
    env.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgresql://user:real-secret@localhost/db",
                "APP_HOST=0.0.0.0",
            ]
        ),
        encoding="utf-8",
    )

    results = doctor.check_env(env, example)
    payload = json.dumps([result.as_dict() for result in results], ensure_ascii=False)

    assert "real-secret" not in payload
    assert "example-secret" not in payload
    assert "postgresql://user:***@localhost/db" in payload
    assert "LLM_API_KEY" in payload
    assert any(result.name == "app_host" for result in results)


def test_sanitize_url_hides_password():
    sanitized = doctor.sanitize_url("postgresql://user:pass@host:5432/db")

    assert sanitized == "postgresql://user:***@host:5432/db"
    assert "pass" not in sanitized


def test_report_recursively_redacts_unregistered_secret_patterns(monkeypatch):
    monkeypatch.setattr(doctor, "secret_values_for_redaction", lambda: [])
    result = doctor.CheckResult(
        name="provider",
        status=doctor.STATUS_WARNING,
        message="request failed with Bearer top-secret-token",
        details={
            "nested": {
                "reason": "api_key=not-loaded-from-env",
                "items": ["https://user:password@example.test/v1?token=visible"],
            }
        },
    )

    payload = json.dumps(result.as_dict())

    assert "top-secret-token" not in payload
    assert "not-loaded-from-env" not in payload
    assert "password" not in payload
    assert "token=visible" not in payload


def test_docker_permission_denied_is_unknown(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")

    def fake_run_command(*args, **kwargs):
        stderr = "permission denied while trying to connect to the Docker daemon socket"
        return doctor.subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr=stderr,
        )

    monkeypatch.setattr(doctor, "run_command", fake_run_command)

    results = doctor.check_docker()

    assert results[0].status == doctor.STATUS_UNKNOWN
    assert "Docker daemon" in results[0].message


def test_lsof_missing_still_reports_port_status(monkeypatch):
    monkeypatch.setattr(doctor, "is_port_listening", lambda port: port == 8000)
    monkeypatch.setattr(
        doctor,
        "find_port_process",
        lambda port: {"available": False, "reason": "lsof not found"},
    )

    results = doctor.check_ports({8000: "backend API", 8080: "frontend console"})
    by_name = {result.name: result for result in results}

    assert by_name["port_8000"].status == doctor.STATUS_OK
    assert by_name["port_8000"].details["process"]["available"] is False
    assert by_name["port_8080"].status == doctor.STATUS_WARNING


def test_collect_db_counts_calculates_project_and_task_totals():
    values = iter([3, 1, 8, 2, 1, 5])

    counts = doctor.collect_db_counts(lambda sql: next(values))

    assert counts == {
        "projects": 3,
        "soft_deleted_projects": 1,
        "async_tasks": 8,
        "running_async_tasks": 2,
        "stale_running_async_tasks": 1,
        "orphan_task_meta": 5,
    }


def test_db_warning_codes_flags_pending_migration_and_stale_tasks():
    warnings = doctor.db_warning_codes(
        {
            "alembic_head": {"heads": ["head_revision"]},
            "alembic_current": "old_revision",
            "stale_running_async_tasks": 1,
            "orphan_task_meta": 0,
        }
    )

    assert warnings == [
        "alembic_current_not_at_head",
        "stale_running_async_tasks",
    ]


def test_json_output_contains_all_default_groups(monkeypatch, capsys):
    async def fake_build_report(include_llm: bool = False):
        checks = {
            group: [
                doctor.CheckResult(
                    name=f"{group}_check",
                    status=doctor.STATUS_OK,
                    message="ok",
                )
            ]
            for group in doctor.ALL_GROUPS
        }
        if include_llm:
            checks["llm_remote"] = [
                doctor.CheckResult(
                    name="llm_remote",
                    status=doctor.STATUS_OK,
                    message="ok",
                )
            ]
        return doctor.DoctorReport(status=doctor.STATUS_OK, checks=checks)

    monkeypatch.setattr(doctor, "build_report", fake_build_report)

    exit_code = asyncio.run(doctor.async_main(["--json"]))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == doctor.STATUS_OK
    assert set(doctor.ALL_GROUPS).issubset(payload["checks"])


def test_doctor_llm_remote_is_explicitly_environment_scoped(monkeypatch):
    async def fake_environment_health():
        return LLMHealthResult(
            ok=True,
            scope="environment",
            remote_check=True,
            message="LLM health check passed",
        )

    monkeypatch.setattr(
        doctor,
        "check_llm_environment_health",
        fake_environment_health,
    )

    results = asyncio.run(doctor.check_llm_remote())

    assert results[0].status == doctor.STATUS_OK
    assert "environment-level" in results[0].message.lower()
    assert results[0].details["scope"] == "environment"
    assert results[0].details["remote_check"] is True


def test_doctor_llm_config_uses_shell_override_before_env_file(
    monkeypatch,
    tmp_path,
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_API_KEY=file-key\n"
        "LLM_BASE_URL=https://file-provider.example/v1\n"
        "LLM_MODEL=file-model\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_API_KEY", "shell-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://shell-provider.example/v1")
    monkeypatch.setenv("LLM_MODEL", "")

    result = doctor.check_llm_config(env_file)[0]

    assert result.details["base_url_host"] == "shell-provider.example"
    assert "LLM_MODEL" in result.details["missing_or_placeholder"]
