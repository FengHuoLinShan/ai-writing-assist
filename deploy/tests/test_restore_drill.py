from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

DEPLOY_ROOT = Path(__file__).parents[1]


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, str], Path]:
    repo_root = tmp_path / "repo"
    scripts = repo_root / "deploy" / "scripts"
    shutil.copytree(DEPLOY_ROOT / "scripts", scripts)
    environment_file = repo_root / "deploy" / ".env.production"
    shutil.copy2(
        DEPLOY_ROOT / "tests" / "fixtures" / "closed-test.env",
        environment_file,
    )
    environment_file.chmod(0o600)
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir(mode=0o700)
    backup_path = backup_dir / "20260806T120000Z.dump"
    backup_path.write_bytes(b"isolated restore drill fixture")
    backup_path.chmod(0o600)
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    sidecar = Path(f"{backup_path}.sha256")
    sidecar.write_text(f"{digest}  {backup_path}\n", encoding="ascii")
    sidecar.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_DOCKER_LOG"\n'
        'case " $* " in\n'
        '  *" image inspect "*) exit 0 ;;\n'
        '  *" run --rm -i --pull never "*)\n'
        '    if [ "${FAKE_SWAP_ORIGINAL:-0}" = 1 ]; then\n'
        '      printf "attacker replacement" >"$FAKE_ORIGINAL_BACKUP"\n'
        '    fi\n'
        '    exit "${FAKE_ARCHIVE_STATUS:-0}" ;;\n'
        '  *" create --name "*)\n'
        '    test "${FAKE_CREATE_STATUS:-0}" = 0 || exit "$FAKE_CREATE_STATUS"\n'
        '    printf "fixture-container-id\\n"\n'
        '    exit 0 ;;\n'
        '  *" start fixture-container-id "*) exit 0 ;;\n'
        '  *" exec "*" pg_isready "*) exit 0 ;;\n'
        '  *" exec -i "*" pg_restore "*)\n'
        '    if [ "${FAKE_SIGNAL_STATUS:-}" = "term" ]; then\n'
        '      kill -TERM "$PPID"\n'
        '      exit 0\n'
        '    fi\n'
        '    cat >"$FAKE_RESTORE_INPUT"\n'
        '    exit "${FAKE_RESTORE_STATUS:-0}" ;;\n'
        '  *" exec "*" psql "*"SELECT 1"*) printf "1\\n"; exit 0 ;;\n'
        '  *" exec "*" psql "*"alembic_version"*)\n'
        '    printf "%s\\n" "${FAKE_ALEMBIC_REVISION:-20260805_task_novel_id}"\n'
        '    exit 0 ;;\n'
        '  *" exec "*" psql "*"to_regclass"*)\n'
        '    printf "%s\\n" "${FAKE_CRITICAL_TABLE_COUNT:-8}"\n'
        '    exit 0 ;;\n'
        '  *" rm -f "*) exit "${FAKE_CLEANUP_STATUS:-0}" ;;\n'
        '  *) exit 1 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ | {
        "ENV_FILE": str(environment_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
        "FAKE_ORIGINAL_BACKUP": str(backup_path),
        "FAKE_RESTORE_INPUT": str(tmp_path / "restore-input.dump"),
    }
    return repo_root, backup_path, environment, docker_log


def _run(
    repo_root: Path,
    backup_path: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "deploy/scripts/restore_drill.sh", str(backup_path)],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_restore_drill_success_is_isolated_read_only_and_sanitized(
    tmp_path: Path,
) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)
    before_dump = backup_path.read_bytes()
    before_sidecar = Path(f"{backup_path}.sha256").read_bytes()

    result = _run(repo_root, backup_path, environment)

    assert result.returncode == 0, result.stderr
    digest = hashlib.sha256(before_dump).hexdigest()
    assert f"sha256={digest}" in result.stdout
    assert "alembic_revision=20260805_task_novel_id" in result.stdout
    assert "critical_tables=8" in result.stdout
    assert "isolated restore drill fixture" not in result.stdout
    calls = docker_log.read_text(encoding="utf-8")
    assert "--network none" in calls
    assert "--read-only" in calls
    assert "--tmpfs /var/lib/postgresql/data:" in calls
    assert "--volume" not in calls
    assert " -v " not in f" {calls} "
    assert "--publish" not in calls
    assert "rm -f" in calls
    assert backup_path.read_bytes() == before_dump
    assert Path(f"{backup_path}.sha256").read_bytes() == before_sidecar
    assert not list(backup_path.parent.glob("restore-input-*.dump"))
    assert not list(backup_path.parent.glob("restore-input-*.dump.sha256"))


def test_restore_drill_restores_validated_snapshot_after_source_path_swap(
    tmp_path: Path,
) -> None:
    repo_root, backup_path, environment, _docker_log = _fixture(tmp_path)
    expected = backup_path.read_bytes()
    restored_input = Path(environment["FAKE_RESTORE_INPUT"])

    result = _run(
        repo_root,
        backup_path,
        environment | {"FAKE_SWAP_ORIGINAL": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert backup_path.read_bytes() == b"attacker replacement"
    assert restored_input.read_bytes() == expected
    assert not list(backup_path.parent.glob("restore-input-*.dump"))


def test_restore_drill_cleans_container_after_restore_failure(tmp_path: Path) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)

    result = _run(
        repo_root,
        backup_path,
        environment | {"FAKE_RESTORE_STATUS": "1"},
    )

    assert result.returncode != 0
    calls = docker_log.read_text(encoding="utf-8")
    assert "pg_restore" in calls
    assert "rm -f" in calls


def test_restore_drill_fails_if_cleanup_cannot_remove_container(tmp_path: Path) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)

    result = _run(
        repo_root,
        backup_path,
        environment | {"FAKE_CLEANUP_STATUS": "1"},
    )

    assert result.returncode != 0
    assert "cleanup" in result.stderr.lower()
    assert "rm -f" in docker_log.read_text(encoding="utf-8")


def test_restore_drill_create_failure_does_not_remove_an_unowned_container(
    tmp_path: Path,
) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)

    result = _run(
        repo_root,
        backup_path,
        environment | {"FAKE_CREATE_STATUS": "1"},
    )

    assert result.returncode != 0
    calls = docker_log.read_text(encoding="utf-8")
    assert "create --name" in calls
    assert "rm -f" not in calls


def test_restore_drill_signal_path_is_nonzero_and_cleans_container(
    tmp_path: Path,
) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)

    result = _run(
        repo_root,
        backup_path,
        environment | {"FAKE_SIGNAL_STATUS": "term"},
    )

    assert result.returncode == 143
    calls = docker_log.read_text(encoding="utf-8")
    assert "pg_restore" in calls
    assert "rm -f" in calls


def test_restore_drill_rejects_unsafe_pair_before_docker(tmp_path: Path) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)
    backup_path.chmod(0o644)

    result = _run(repo_root, backup_path, environment)

    assert result.returncode != 0
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o644
    assert not docker_log.exists()


def test_restore_drill_rejects_checksum_mismatch_before_docker(tmp_path: Path) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)
    sidecar = Path(f"{backup_path}.sha256")
    sidecar.write_text(f"{'0' * 64}  {backup_path}\n", encoding="ascii")
    sidecar.chmod(0o600)

    result = _run(repo_root, backup_path, environment)

    assert result.returncode != 0
    assert "checksum" in result.stderr.lower()
    assert not docker_log.exists()


def test_restore_drill_rejects_hardlinked_dump_before_docker(tmp_path: Path) -> None:
    repo_root, backup_path, environment, docker_log = _fixture(tmp_path)
    os.link(backup_path, backup_path.parent / "second-link.dump")

    result = _run(repo_root, backup_path, environment)

    assert result.returncode != 0
    assert "regular file" in result.stderr.lower()
    assert not docker_log.exists()
