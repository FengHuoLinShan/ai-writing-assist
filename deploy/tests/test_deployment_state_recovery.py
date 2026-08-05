from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY_ROOT = Path(__file__).parents[1]


def _git(repo_root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _deployment_repo(tmp_path: Path) -> tuple[Path, str, str, dict[str, str], Path]:
    repo_root = tmp_path / "repo"
    shutil.copytree(DEPLOY_ROOT, repo_root / "deploy")
    _git(repo_root, "init", "-q")
    _git(repo_root, "config", "user.email", "deploy-tests@example.com")
    _git(repo_root, "config", "user.name", "Deployment Tests")
    migrations_dir = repo_root / "backend" / "alembic" / "versions"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "migration_a.py").write_text(
        'revision = "migration_a"\n'
        "down_revision = None\n"
    )
    (repo_root / "revision.txt").write_text("a\n")
    _git(repo_root, "add", "deploy", "backend", "revision.txt")
    _git(repo_root, "commit", "-qm", "release A")
    commit_a = _git(repo_root, "rev-parse", "HEAD")

    origin_root = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(origin_root)], check=True)
    _git(repo_root, "remote", "add", "origin", str(origin_root))
    _git(repo_root, "push", "-qu", "origin", "HEAD:main")

    (repo_root / "revision.txt").write_text("b\n")
    _git(repo_root, "add", "revision.txt")
    _git(repo_root, "commit", "-qm", "release B")
    commit_b = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "push", "origin", "HEAD:main")
    _git(repo_root, "fetch", "origin")

    deploy_root = repo_root / "deploy"
    environment_file = deploy_root / ".env.production"
    shutil.copy2(
        DEPLOY_ROOT / "tests" / "fixtures" / "closed-test.env", environment_file
    )
    environment_file.chmod(0o600)
    state_dir = deploy_root / ".state"
    state_dir.mkdir(mode=0o700)
    (state_dir / "current-release").write_text(f"{commit_a[:12]}\n")
    (state_dir / "current-commit").write_text(f"{commit_a}\n")
    _git(repo_root, "checkout", "--detach", "-q", commit_a)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    (fake_bin / "docker").write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_DOCKER_LOG"\n'
        'case " $* " in\n'
        '  *" exec -T -e PGCONNECT_TIMEOUT=5 postgres psql "*)\n'
        '    if test "${FAKE_MIGRATION_QUERY_STATUS:-0}" -ne 0; then\n'
        '      exit "$FAKE_MIGRATION_QUERY_STATUS"\n'
        "    fi\n"
        '    case " $* " in\n'
        '      *"alembic_version"*)\n'
        '        printf "%s\\n" "${FAKE_MIGRATION_REVISIONS:-migration_a}" ;;\n'
        '      *) printf "%s\\n" "${FAKE_PUBLIC_TABLE_COUNT:-1}" ;;\n'
        "    esac\n"
        "    exit 0 ;;\n"
        '  *" stop api worker frontend "*) exit "${FAKE_DOCKER_STOP_STATUS:-0}" ;;\n'
        '  *" build "*) exit "${FAKE_DOCKER_BUILD_STATUS:-0}" ;;\n'
        '  *" up -d postgres embedding "*) exit '
        '"${FAKE_DOCKER_DEPENDENCY_UP_STATUS:-0}" ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    (fake_bin / "docker").chmod(0o755)
    environment = os.environ | {
        "ENV_FILE": str(environment_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
    }
    return repo_root, commit_a, commit_b, environment, docker_log


def _run_script(
    repo_root: Path,
    script_name: str,
    arguments: list[str],
    environment: dict[str, str],
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", f"deploy/scripts/{script_name}", *arguments],
        cwd=repo_root,
        env=environment,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _assert_healthy_state(repo_root: Path, commit_a: str) -> None:
    state_dir = repo_root / "deploy" / ".state"
    assert (state_dir / "current-release").read_text() == f"{commit_a[:12]}\n"
    assert (state_dir / "current-commit").read_text() == f"{commit_a}\n"
    assert not (state_dir / "previous-release").exists()


def test_release_failure_restores_the_finalized_checkout_not_drifted_head(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)

    result = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_DOCKER_BUILD_STATUS": "1"},
    )

    assert result.returncode != 0
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    assert docker_log.exists(), result.stderr
    assert " stop api worker frontend" not in docker_log.read_text(encoding="utf-8")


def test_release_checkout_disables_local_git_hooks(tmp_path: Path) -> None:
    repo_root, commit_a, commit_b, environment, _docker_log = _deployment_repo(tmp_path)
    hook_marker = tmp_path / "post-checkout-ran"
    hook_path = repo_root / ".git" / "hooks" / "post-checkout"
    hook_path.write_text(f"#!/bin/sh\nprintf hook >{hook_marker}\n")
    hook_path.chmod(0o755)

    result = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_DOCKER_BUILD_STATUS": "1"},
    )

    assert result.returncode != 0
    assert not hook_marker.exists()
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)


@pytest.mark.parametrize(
    ("environment_override", "expected"),
    [
        ({"FAKE_MIGRATION_REVISIONS": "unknown"}, "incompatible"),
        ({"FAKE_MIGRATION_QUERY_STATUS": "1"}, "Unable to read live Alembic revisions"),
    ],
)
def test_release_migration_preflight_rejects_before_checkout_or_service_work(
    tmp_path: Path, environment_override: dict[str, str], expected: str
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)

    result = _run_script(
        repo_root, "release.sh", [commit_b], environment | environment_override
    )

    assert result.returncode != 0
    assert expected in result.stderr
    if expected == "incompatible":
        assert "restore.sh <backup.dump> <target-sha>" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    docker_commands = docker_log.read_text(encoding="utf-8")
    assert " exec -T -e PGCONNECT_TIMEOUT=5 postgres psql " in f" {docker_commands} "
    assert " psql -w -X -qAt -v ON_ERROR_STOP=1 " in f" {docker_commands} "
    assert " build " not in f" {docker_commands} "
    assert " stop api worker frontend" not in docker_commands
    assert " pg_dump" not in docker_commands
    assert " migrate" not in docker_commands
    assert " up -d postgres embedding" not in docker_commands


def test_release_rejects_active_state_checkout_drift_before_database_work(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    _git(repo_root, "checkout", "--detach", "-q", commit_b)

    result = _run_script(repo_root, "release.sh", [commit_b], environment)

    assert result.returncode != 0
    assert "does not match the finalized active deployment state" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_b
    assert _assert_healthy_state(repo_root, commit_a) is None
    assert not docker_log.exists()


def test_first_release_requires_an_empty_live_database_before_checkout(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    state_dir = repo_root / "deploy" / ".state"
    (state_dir / "current-release").unlink()
    (state_dir / "current-commit").unlink()

    rejected = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_PUBLIC_TABLE_COUNT": "1"},
    )

    assert rejected.returncode != 0
    assert "state is absent but the live database is not empty" in rejected.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    assert " build " not in f" {docker_log.read_text(encoding='utf-8')} "

    docker_log.unlink()
    accepted_until_build = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_PUBLIC_TABLE_COUNT": "0", "FAKE_DOCKER_BUILD_STATUS": "1"},
    )

    assert accepted_until_build.returncode != 0
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    commands = docker_log.read_text(encoding="utf-8")
    assert " information_schema.tables " in commands
    assert " alembic_version " not in commands
    assert " build " in f" {commands} "


def test_first_release_query_failure_rejects_before_checkout_or_service_work(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    state_dir = repo_root / "deploy" / ".state"
    (state_dir / "current-release").unlink()
    (state_dir / "current-commit").unlink()

    result = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_MIGRATION_QUERY_STATUS": "1"},
    )

    assert result.returncode != 0
    assert "Unable to verify that the first-release database is empty" in result.stderr
    assert "will not start Postgres automatically" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    commands = docker_log.read_text(encoding="utf-8")
    assert " exec -T -e PGCONNECT_TIMEOUT=5 postgres psql " in f" {commands} "
    assert " psql -w -X -qAt -v ON_ERROR_STOP=1 " in f" {commands} "
    assert " build " not in f" {commands} "
    assert " stop api worker frontend" not in commands
    assert " pg_dump" not in commands
    assert " migrate" not in commands
    assert " up -d postgres embedding" not in commands


def test_release_rejects_partial_legacy_state_before_database_work(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    (repo_root / "deploy" / ".state" / "current-commit").unlink()

    result = _run_script(repo_root, "release.sh", [commit_b], environment)

    assert result.returncode != 0
    assert "incomplete" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    assert not docker_log.exists()


def test_release_and_restore_precheckout_guard_rejects_untracked_source(
    tmp_path: Path,
) -> None:
    for script_name in ("release.sh", "restore.sh"):
        repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(
            tmp_path / script_name
        )
        untracked_source = repo_root / "backend" / "untracked.py"
        untracked_source.parent.mkdir(exist_ok=True)
        untracked_source.write_text("untracked\n")

        arguments = [commit_b]
        if script_name == "restore.sh":
            arguments.insert(0, str(repo_root / "deploy" / "backups" / "missing.dump"))
        result = _run_script(repo_root, script_name, arguments, environment)

        assert result.returncode != 0
        assert "Deployment checkout is unsafe" in result.stderr
        assert _git(repo_root, "rev-parse", "HEAD") == commit_a
        _assert_healthy_state(repo_root, commit_a)
        assert not docker_log.exists()


def test_release_postcheckout_guard_rejects_target_time_drift(tmp_path: Path) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    fake_bin = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    real_git = shutil.which("git")
    assert real_git is not None
    drift_path = repo_root / ".target-time-drift"
    (repo_root / ".git" / "info" / "exclude").write_text(".target-time-drift\n")
    (fake_bin / "git").write_text(
        "#!/bin/sh\n"
        "checkout=false\n"
        "for argument in \"$@\"; do\n"
        "  test \"$argument\" = checkout && checkout=true\n"
        "done\n"
        "\"$FAKE_REAL_GIT\" \"$@\"\n"
        "status=$?\n"
        "if test \"$status\" -eq 0 && test \"$checkout\" = true; then\n"
        "  printf target-drift >\"$FAKE_GIT_DRIFT_PATH\"\n"
        "fi\n"
        "exit \"$status\"\n"
    )
    (fake_bin / "git").chmod(0o755)

    result = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment
        | {
            "FAKE_REAL_GIT": real_git,
            "FAKE_GIT_DRIFT_PATH": str(drift_path),
        },
    )

    assert result.returncode != 0
    assert "Deployment checkout is unsafe" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    commands = docker_log.read_text(encoding="utf-8")
    assert " exec -T -e PGCONNECT_TIMEOUT=5 postgres psql " in f" {commands} "
    assert " build " not in f" {commands} "
    assert " stop api worker frontend" not in commands


def test_restore_postcheckout_guard_rejects_target_time_drift(tmp_path: Path) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    backup_path = repo_root / "deploy" / "backups" / "fixture.dump"
    backup_path.parent.mkdir()
    backup_path.write_bytes(b"fixture backup")
    Path(f"{backup_path}.sha256").write_text(
        f"{hashlib.sha256(backup_path.read_bytes()).hexdigest()}\n"
    )
    fake_bin = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    real_git = shutil.which("git")
    assert real_git is not None
    drift_path = repo_root / ".target-time-drift"
    (repo_root / ".git" / "info" / "exclude").write_text(".target-time-drift\n")
    (fake_bin / "git").write_text(
        "#!/bin/sh\n"
        "checkout=false\n"
        "for argument in \"$@\"; do\n"
        "  test \"$argument\" = checkout && checkout=true\n"
        "done\n"
        "\"$FAKE_REAL_GIT\" \"$@\"\n"
        "status=$?\n"
        "if test \"$status\" -eq 0 && test \"$checkout\" = true; then\n"
        "  printf target-drift >\"$FAKE_GIT_DRIFT_PATH\"\n"
        "fi\n"
        "exit \"$status\"\n"
    )
    (fake_bin / "git").chmod(0o755)

    result = _run_script(
        repo_root,
        "restore.sh",
        [str(backup_path), commit_b],
        environment
        | {
            "FAKE_REAL_GIT": real_git,
            "FAKE_GIT_DRIFT_PATH": str(drift_path),
        },
    )

    assert result.returncode != 0
    assert "Deployment checkout is unsafe" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    assert not docker_log.exists()


def test_restore_cancellation_restores_finalized_checkout_without_replacing_database(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    backup_path = repo_root / "deploy" / "backups" / "fixture.dump"
    backup_path.parent.mkdir()
    backup_path.write_bytes(b"fixture backup")
    checksum_path = Path(f"{backup_path}.sha256")
    checksum_path.write_text(
        f"{hashlib.sha256(backup_path.read_bytes()).hexdigest()}\n"
    )

    result = _run_script(
        repo_root,
        "restore.sh",
        [str(backup_path), commit_b],
        environment,
        input_text="not-confirmed\n",
    )

    assert result.returncode != 0
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    docker_commands = docker_log.read_text(encoding="utf-8")
    assert "run --rm --pull never" in docker_commands
    assert "--network none" in docker_commands
    assert "--entrypoint pg_restore" in docker_commands
    assert "exec -T postgres pg_restore" not in docker_commands
    assert " up -d postgres " not in docker_commands
    assert " stop api worker frontend" not in docker_commands
    assert " dropdb " not in f" {docker_commands} "
    assert " createdb " not in f" {docker_commands} "
    assert " --exit-on-error" not in docker_commands


def test_restore_rejects_symlinked_backup_directory_before_git_or_docker_work(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    backup_dir = repo_root / "deploy" / "backups"
    outside = tmp_path / "outside-backups"
    outside.mkdir()
    backup_path = outside / "fixture.dump"
    backup_path.write_bytes(b"fixture backup")
    Path(f"{backup_path}.sha256").write_text(
        f"{hashlib.sha256(backup_path.read_bytes()).hexdigest()}\n"
    )
    backup_dir.symlink_to(outside, target_is_directory=True)

    result = _run_script(
        repo_root,
        "restore.sh",
        [str(backup_dir / "fixture.dump"), commit_b],
        environment,
    )

    assert result.returncode != 0
    assert "Private directory is unsafe." in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    assert not docker_log.exists()


def test_restore_target_environment_validation_failure_restores_finalized_checkout(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    _git(repo_root, "checkout", "--detach", "-q", commit_b)
    target_validator = repo_root / "deploy" / "scripts" / "validate_env.py"
    target_validator.write_text(
        "import sys\n"
        "print('TARGET_VALIDATOR_REJECTED', file=sys.stderr)\n"
        "raise SystemExit(1)\n"
    )
    _git(repo_root, "add", "deploy/scripts/validate_env.py")
    _git(repo_root, "commit", "-qm", "target validator rejects")
    target_commit = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "push", "origin", "HEAD:main")
    _git(repo_root, "fetch", "origin")
    _git(repo_root, "checkout", "--detach", "-q", commit_a)

    backup_path = repo_root / "deploy" / "backups" / "fixture.dump"
    backup_path.parent.mkdir()
    backup_path.write_bytes(b"fixture backup")
    Path(f"{backup_path}.sha256").write_text(
        f"{hashlib.sha256(backup_path.read_bytes()).hexdigest()}\n"
    )

    result = _run_script(
        repo_root,
        "restore.sh",
        [str(backup_path), target_commit],
        environment,
    )

    assert result.returncode != 0
    assert "TARGET_VALIDATOR_REJECTED" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    assert not docker_log.exists()


def test_release_rejects_target_without_deployment_state_contract_before_build(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    _git(repo_root, "checkout", "--detach", "-q", commit_b)
    (repo_root / "deploy" / "deployment-state-contract.version").unlink()
    _git(repo_root, "add", "-u", "deploy/deployment-state-contract.version")
    _git(repo_root, "commit", "-qm", "target state contract missing")
    target_commit = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "push", "origin", "HEAD:main")
    _git(repo_root, "fetch", "origin")
    _git(repo_root, "checkout", "--detach", "-q", commit_a)

    result = _run_script(repo_root, "release.sh", [target_commit], environment)

    assert result.returncode != 0
    assert "valid deployment state contract" in result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    commands = docker_log.read_text(encoding="utf-8")
    assert " exec -T -e PGCONNECT_TIMEOUT=5 postgres psql " in f" {commands} "
    assert " build " not in f" {commands} "
    assert " stop api worker frontend" not in commands


def test_release_quiesce_failure_blocks_backup_migration_and_target_start(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)

    result = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_DOCKER_STOP_STATUS": "1"},
    )

    assert result.returncode != 0
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    docker_commands = docker_log.read_text(encoding="utf-8")
    assert docker_commands.count(" stop api worker frontend") == 1
    assert " up -d postgres embedding" not in docker_commands
    assert " pg_dump" not in docker_commands
    assert " migrate" not in docker_commands
    assert " up -d api worker frontend" not in docker_commands


def test_release_dependency_reconciliation_failure_keeps_applications_quiesced(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)

    result = _run_script(
        repo_root,
        "release.sh",
        [commit_b],
        environment | {"FAKE_DOCKER_DEPENDENCY_UP_STATUS": "1"},
    )

    assert result.returncode != 0
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    docker_commands = docker_log.read_text(encoding="utf-8")
    assert docker_commands.count(" stop api worker frontend") == 1
    assert docker_commands.index(" stop api worker frontend") < docker_commands.index(
        " up -d postgres embedding"
    )
    assert " pg_dump" not in docker_commands
    assert " migrate" not in docker_commands
    assert " up -d api worker frontend" not in docker_commands


def test_restore_quiesce_failure_blocks_safety_backup_and_database_replacement(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
    backup_path = repo_root / "deploy" / "backups" / "fixture.dump"
    backup_path.parent.mkdir()
    backup_path.write_bytes(b"fixture backup")
    checksum_path = Path(f"{backup_path}.sha256")
    checksum_path.write_text(
        f"{hashlib.sha256(backup_path.read_bytes()).hexdigest()}\n"
    )

    result = _run_script(
        repo_root,
        "restore.sh",
        [str(backup_path), commit_b],
        environment | {"FAKE_DOCKER_STOP_STATUS": "1"},
        input_text="RESTORE_PRODUCTION_BACKUP\n",
    )

    assert result.returncode != 0
    assert _git(repo_root, "rev-parse", "HEAD") == commit_a
    _assert_healthy_state(repo_root, commit_a)
    docker_commands = docker_log.read_text(encoding="utf-8")
    assert docker_commands.count(" stop api worker frontend") == 1
    assert " pg_dump" not in docker_commands
    assert " dropdb " not in f" {docker_commands} "
    assert " createdb " not in f" {docker_commands} "
    assert " --exit-on-error" not in docker_commands
    assert " migrate" not in docker_commands


def _resolve_active_commit(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/sh",
            "-c",
            '. "$0"; resolve_active_deployment_commit',
            "deploy/scripts/common.sh",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _load_release_id(repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/sh",
            "-c",
            '. "$0"; load_release_id; printf "%s\\n" "$RELEASE_ID"',
            "deploy/scripts/common.sh",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _write_state(repo_root: Path, release: str | None, commit: str | None) -> None:
    state_dir = repo_root / "deploy" / ".state"
    for state_name in ("current-release", "current-commit"):
        state_path = state_dir / state_name
        if state_path.exists() or state_path.is_symlink():
            state_path.unlink()
    if release is not None:
        (state_dir / "current-release").write_text(release)
    if commit is not None:
        (state_dir / "current-commit").write_text(commit)


def _write_manifest(
    repo_root: Path,
    current_commit: str,
    previous_commit: str,
    *,
    operation_id: str = "a" * 32,
) -> None:
    deploy_root = repo_root / "deploy"
    backup_dir = deploy_root / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    backup_dir.chmod(0o700)
    backup_path = backup_dir / "manifest.dump"
    backup_path.write_bytes(b"manifest backup")
    state_path = deploy_root / ".state" / "deployment-state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "operation_id": operation_id,
                "operation": "release",
                "current_commit": current_commit,
                "previous_commit": previous_commit,
                "backup_path": str(backup_path),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    state_path.chmod(0o600)


def test_resolve_active_deployment_commit_validates_finalized_state(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(
        tmp_path
    )

    valid = _resolve_active_commit(repo_root)

    assert valid.returncode == 0, valid.stderr
    assert valid.stdout == f"{commit_a}\n"

    _write_state(repo_root, None, None)
    first_release = _resolve_active_commit(repo_root)
    assert first_release.returncode == 0, first_release.stderr
    assert first_release.stdout == _git(repo_root, "rev-parse", "HEAD") + "\n"

    _write_state(repo_root, commit_a[:12] + "\n", None)
    incomplete = _resolve_active_commit(repo_root)
    assert incomplete.returncode != 0
    assert incomplete.stdout == ""

    _write_state(repo_root, commit_a[:12] + "\nextra\n", commit_a + "\n")
    multiline = _resolve_active_commit(repo_root)
    assert multiline.returncode != 0
    assert multiline.stdout == ""

    _write_state(repo_root, "a" * 11 + "\n", commit_a + "\n")
    bad_length = _resolve_active_commit(repo_root)
    assert bad_length.returncode != 0
    assert bad_length.stdout == ""

    _write_state(repo_root, "g" * 12 + "\n", commit_a + "\n")
    bad_release = _resolve_active_commit(repo_root)
    assert bad_release.returncode != 0
    assert bad_release.stdout == ""

    _write_state(repo_root, commit_a[:12] + "\n", "f" * 40 + "\n")
    unresolved = _resolve_active_commit(repo_root)
    assert unresolved.returncode != 0
    assert unresolved.stdout == ""

    _write_state(repo_root, "0" * 12 + "\n", commit_a + "\n")
    prefix_mismatch = _resolve_active_commit(repo_root)
    assert prefix_mismatch.returncode != 0
    assert prefix_mismatch.stdout == ""

    (repo_root / "revision.txt").write_text("unreachable\n")
    _git(repo_root, "add", "revision.txt")
    _git(repo_root, "commit", "-qm", "unreachable")
    unreachable_commit = _git(repo_root, "rev-parse", "HEAD")
    _write_state(repo_root, unreachable_commit[:12] + "\n", unreachable_commit + "\n")
    unreachable = _resolve_active_commit(repo_root)
    assert unreachable.returncode != 0
    assert unreachable.stdout == ""


def test_manifest_precedes_legacy_state_and_malformed_manifest_has_no_fallback(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    _git(repo_root, "checkout", "--detach", "-q", commit_b)
    _write_manifest(repo_root, commit_b, commit_a)

    preferred = _resolve_active_commit(repo_root)

    assert preferred.returncode == 0, preferred.stderr
    assert preferred.stdout == f"{commit_b}\n"

    state_path = repo_root / "deploy" / ".state" / "deployment-state.json"
    state_path.write_text("{}")
    state_path.chmod(0o600)
    malformed = _resolve_active_commit(repo_root)

    assert malformed.returncode != 0
    assert malformed.stdout == ""

    state_path.unlink()
    outside = tmp_path / "outside-manifest"
    outside.write_text("{}")
    state_path.symlink_to(outside)
    symlinked = _resolve_active_commit(repo_root)

    assert symlinked.returncode != 0
    assert symlinked.stdout == ""


def test_exact_manifest_nonce_prevents_cleanup_rollback(tmp_path: Path) -> None:
    repo_root, commit_a, commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    _write_manifest(repo_root, commit_b, commit_a, operation_id="d" * 32)
    driver = repo_root / "deploy" / "scripts" / "cleanup-decision.sh"
    driver.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        '. "$SCRIPT_DIR/common.sh"\n'
        'TARGET_COMMIT=$1\n'
        'OPERATION_ID=$2\n'
        "DEPLOYMENT_COMMITTED=false\n"
        "DEPLOYMENT_STATE_WRITE_FAILED=false\n"
        'if [ "$DEPLOYMENT_COMMITTED" != "true" ] \\\n'
        '    && [ "$DEPLOYMENT_STATE_WRITE_FAILED" != "true" ] \\\n'
        '    && deployment_state_matches "$TARGET_COMMIT" "$OPERATION_ID"; then\n'
        "    DEPLOYMENT_COMMITTED=true\n"
        "fi\n"
        'printf "%s\\n" "$DEPLOYMENT_COMMITTED"\n'
    )
    driver.chmod(0o700)

    exact = subprocess.run(
        ["/bin/sh", str(driver), commit_b, "d" * 32],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    different_nonce = subprocess.run(
        ["/bin/sh", str(driver), commit_b, "e" * 32],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert exact.returncode == 0, exact.stderr
    assert exact.stdout == "true\n"
    assert different_nonce.returncode == 0, different_nonce.stderr
    assert different_nonce.stdout == "false\n"


def test_resolve_active_deployment_commit_rejects_symlinked_state(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(
        tmp_path
    )
    state_dir = repo_root / "deploy" / ".state"
    release_path = state_dir / "current-release"
    release_path.unlink()
    outside = tmp_path / "outside-release"
    outside.write_text(f"{commit_a[:12]}\n")
    release_path.symlink_to(outside)

    result = _resolve_active_commit(repo_root)

    assert result.returncode != 0
    assert result.stdout == ""


def test_load_release_id_uses_finalized_state_instead_of_drifted_head(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    _git(repo_root, "checkout", "--detach", "-q", commit_b)

    result = _load_release_id(repo_root)

    assert result.returncode == 0, result.stderr
    assert _git(repo_root, "rev-parse", "HEAD") == commit_b
    assert result.stdout == f"{commit_a[:12]}\n"


def test_load_release_id_uses_reachable_first_release_head_without_creating_state(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    state_dir = repo_root / "deploy" / ".state"
    shutil.rmtree(state_dir)

    result = _load_release_id(repo_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{commit_a[:12]}\n"
    assert not state_dir.exists()
    assert not state_dir.is_symlink()


def test_load_release_id_uses_reachable_first_release_head_with_empty_state_directory(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    state_dir = repo_root / "deploy" / ".state"
    _write_state(repo_root, None, None)
    lock_path = state_dir / "production-operation.lock"
    lock_path.write_text("held elsewhere")
    state_dir.chmod(0o700)

    result = _load_release_id(repo_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{commit_a[:12]}\n"
    assert state_dir.is_dir()
    assert lock_path.is_file()
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700


def test_load_release_id_rejects_invalid_finalized_state_pair(tmp_path: Path) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    invalid_pairs = (
        (commit_a[:12] + "\n", None),
        ("a" * 11 + "\n", commit_a + "\n"),
        ("0" * 12 + "\n", commit_a + "\n"),
    )

    for release, commit in invalid_pairs:
        _write_state(repo_root, release, commit)

        result = _load_release_id(repo_root)

        assert result.returncode != 0
        assert result.stdout == ""

    release_path = repo_root / "deploy" / ".state" / "current-release"
    release_path.unlink()
    outside_release = tmp_path / "outside-release"
    outside_release.write_text(f"{commit_a[:12]}\n")
    release_path.symlink_to(outside_release)

    symlinked_pair = _load_release_id(repo_root)

    assert symlinked_pair.returncode != 0
    assert symlinked_pair.stdout == ""


def test_load_release_id_rejects_symlinked_state_directory(tmp_path: Path) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    state_dir = repo_root / "deploy" / ".state"
    outside = tmp_path / "outside-state"
    outside.mkdir(mode=0o700)
    (outside / "current-release").write_text(f"{commit_a[:12]}\n")
    (outside / "current-commit").write_text(f"{commit_a}\n")
    shutil.rmtree(state_dir)
    state_dir.symlink_to(outside, target_is_directory=True)

    result = _load_release_id(repo_root)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Private directory is unsafe." in result.stderr


def test_load_release_id_normalizes_present_private_state_directory(
    tmp_path: Path,
) -> None:
    repo_root, commit_a, _commit_b, _environment, _docker_log = _deployment_repo(tmp_path)
    state_dir = repo_root / "deploy" / ".state"
    state_dir.chmod(0o755)

    result = _load_release_id(repo_root)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{commit_a[:12]}\n"
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700


def test_load_release_id_rejects_unreachable_first_release_head(tmp_path: Path) -> None:
    repo_root = _deployment_repo(tmp_path)[0]
    state_dir = repo_root / "deploy" / ".state"
    shutil.rmtree(state_dir)
    (repo_root / "revision.txt").write_text("unreachable\n")
    _git(repo_root, "add", "revision.txt")
    _git(repo_root, "commit", "-qm", "unreachable")

    result = _load_release_id(repo_root)

    assert result.returncode != 0
    assert result.stdout == ""
