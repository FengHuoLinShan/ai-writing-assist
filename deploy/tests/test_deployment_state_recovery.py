from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

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
    (repo_root / "revision.txt").write_text("a\n")
    _git(repo_root, "add", "deploy", "revision.txt")
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
    _git(repo_root, "checkout", "--detach", "-q", commit_b)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    (fake_bin / "docker").write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_DOCKER_LOG"\n'
        'case " $* " in\n'
        '  *" stop api worker frontend "*) exit "${FAKE_DOCKER_STOP_STATUS:-0}" ;;\n'
        '  *" build "*) exit "${FAKE_DOCKER_BUILD_STATUS:-0}" ;;\n'
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
    assert " stop api worker frontend" not in docker_log.read_text(encoding="utf-8")


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
    assert " stop api worker frontend" not in docker_commands
    assert " dropdb " not in f" {docker_commands} "
    assert " createdb " not in f" {docker_commands} "
    assert " --exit-on-error" not in docker_commands


def test_restore_rejects_symlinked_backup_directory_before_git_or_docker_work(
    tmp_path: Path,
) -> None:
    repo_root, _commit_a, commit_b, environment, docker_log = _deployment_repo(tmp_path)
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
    assert _git(repo_root, "rev-parse", "HEAD") == commit_b
    assert not docker_log.exists()


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
