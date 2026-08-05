from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

DEPLOY_ROOT = Path(__file__).parents[1]


def _backup_fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    repo_root = tmp_path / "repo"
    deploy_root = repo_root / "deploy"
    scripts = deploy_root / "scripts"
    shutil.copytree(DEPLOY_ROOT / "scripts", scripts)
    environment_file = deploy_root / ".env.production"
    shutil.copy2(
        DEPLOY_ROOT / "tests" / "fixtures" / "closed-test.env", environment_file
    )
    environment_file.chmod(0o600)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    (fake_bin / "docker").write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_DOCKER_LOG"\n'
        'case " $* " in\n'
        '  *" image inspect "*) exit "${FAKE_IMAGE_INSPECT_STATUS:-0}" ;;\n'
        '  *" pull "*) exit "${FAKE_IMAGE_PULL_STATUS:-0}" ;;\n'
        "  *' pg_isready '*) exit 0 ;;\n"
        "  *' pg_dump '*)\n"
        "    printf 'fixture dump bytes'\n"
        '    test "${FAKE_PG_DUMP_FAIL:-0}" != 1 ;;\n'
        '  *" pg_restore "*) exit "${FAKE_PG_RESTORE_FAIL:-0}" ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    (fake_bin / "restic").write_text(
        "#!/bin/sh\n"
        'test "${FAKE_RESTIC_FAIL:-0}" != 1 || exit 1\n'
        'case "${FAKE_RESTIC_FAIL_AT:-}" in\n'
        '  snapshots) case " $* " in *" snapshots "*) exit 1 ;; esac ;;\n'
        '  backup) case " $* " in *" backup "*) exit 1 ;; esac ;;\n'
        '  forget) case " $* " in *" forget "*) exit 1 ;; esac ;;\n'
        "esac\n"
    )
    (fake_bin / "curl").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "date").write_text("#!/bin/sh\nprintf '%s\\n' \"${FAKE_TIMESTAMP}\"\n")
    for command in fake_bin.iterdir():
        command.chmod(0o755)

    environment = os.environ | {
        "ENV_FILE": str(deploy_root / ".env.production"),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
        "FAKE_TIMESTAMP": "20260102T030405Z",
    }
    return repo_root, environment, docker_log


def _run_backup(
    repo_root: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "deploy/scripts/backup.sh"],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_failed_pg_dump_cleans_current_and_stale_staging_files(tmp_path: Path) -> None:
    repo_root, environment, _docker_log = _backup_fixture(tmp_path)
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir()
    stale = backup_dir / ".backup-stage.stale"
    stale.write_bytes(b"stale")
    legacy = backup_dir / "old.dump.partial"
    legacy.write_bytes(b"legacy")

    result = _run_backup(repo_root, environment | {"FAKE_PG_DUMP_FAIL": "1"})

    final_dump = backup_dir / "20260102T030405Z.dump"
    assert result.returncode != 0
    assert result.stdout == ""
    assert not final_dump.exists()
    assert not Path(f"{final_dump}.sha256").exists()
    assert not stale.exists()
    assert not legacy.exists()
    assert not list(backup_dir.glob(".backup-stage.*"))
    assert not list(backup_dir.glob("*.dump.partial"))


def test_symlinked_backup_directory_fails_before_docker_or_staging(
    tmp_path: Path,
) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)
    backup_dir = repo_root / "deploy" / "backups"
    outside = tmp_path / "outside-backups"
    outside.mkdir()
    backup_dir.symlink_to(outside, target_is_directory=True)

    result = _run_backup(repo_root, environment)

    assert result.returncode != 0
    assert result.stdout == ""
    assert "Private directory is unsafe." in result.stderr
    assert not docker_log.exists()
    assert not list(outside.iterdir())


def test_permissive_owner_backup_directory_is_repaired_before_backup(
    tmp_path: Path,
) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir(mode=0o755)
    backup_dir.chmod(0o755)

    result = _run_backup(repo_root, environment | {"FAKE_RESTIC_FAIL": "1"})

    assert result.returncode != 0
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert "pg_dump" in docker_log.read_text(encoding="utf-8")


def test_failed_checksum_computation_cleans_unpublished_pair_and_staging(
    tmp_path: Path,
) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)
    fake_bin = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    fake_sha256sum = fake_bin / "sha256sum"
    fake_sha256sum.write_text("#!/bin/sh\nexit 1\n")
    fake_sha256sum.chmod(0o755)

    result = _run_backup(repo_root, environment)

    backup_dir = repo_root / "deploy" / "backups"
    final_dump = backup_dir / "20260102T030405Z.dump"
    assert result.returncode != 0
    assert result.stdout == ""
    assert "pg_dump" in docker_log.read_text(encoding="utf-8")
    assert "pg_restore" in docker_log.read_text(encoding="utf-8")
    assert not final_dump.exists()
    assert not Path(f"{final_dump}.sha256").exists()
    assert not list(backup_dir.glob(".backup-stage.*"))
    assert not list(backup_dir.glob(".backup-checksum-stage.*"))


def test_archive_verifier_failure_cleans_the_unpublished_backup(tmp_path: Path) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)

    result = _run_backup(repo_root, environment | {"FAKE_PG_RESTORE_FAIL": "1"})

    backup_dir = repo_root / "deploy" / "backups"
    assert result.returncode != 0
    assert result.stdout == ""
    assert "run --rm --pull never" in docker_log.read_text(encoding="utf-8")
    assert not (backup_dir / "20260102T030405Z.dump").exists()
    assert not Path(f"{backup_dir / '20260102T030405Z.dump'}.sha256").exists()


def test_archive_verifier_pulls_only_when_the_pinned_image_is_missing(
    tmp_path: Path,
) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)

    result = _run_backup(
        repo_root,
        environment
        | {
            "FAKE_IMAGE_INSPECT_STATUS": "1",
            "FAKE_RESTIC_FAIL_AT": "snapshots",
        },
    )

    assert result.returncode != 0
    command_lines = docker_log.read_text(encoding="utf-8").splitlines()
    inspect = next(
        index for index, line in enumerate(command_lines) if "image inspect" in line
    )
    pull = next(
        index for index, line in enumerate(command_lines) if line.startswith("pull ")
    )
    archive = next(
        index
        for index, line in enumerate(command_lines)
        if "run --rm --pull never" in line
    )
    assert inspect < pull < archive


def test_archive_verifier_does_not_pull_an_inspected_cached_image(
    tmp_path: Path,
) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)

    result = _run_backup(repo_root, environment)

    assert result.returncode == 0, result.stderr
    command_lines = docker_log.read_text(encoding="utf-8").splitlines()
    assert any("image inspect" in line for line in command_lines)
    assert any("run --rm --pull never" in line for line in command_lines)
    assert not any(line.startswith("pull ") for line in command_lines)


def test_archive_verifier_fails_closed_when_the_missing_image_cannot_be_pulled(
    tmp_path: Path,
) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)

    result = _run_backup(
        repo_root,
        environment
        | {"FAKE_IMAGE_INSPECT_STATUS": "1", "FAKE_IMAGE_PULL_STATUS": "1"},
    )

    assert result.returncode != 0
    assert result.stdout == ""
    commands = docker_log.read_text(encoding="utf-8")
    assert "image inspect" in commands
    assert "pull" in commands
    assert "run --rm --pull never" not in commands


def test_remote_failure_keeps_completed_pair_and_prunes_old_local_pair(
    tmp_path: Path,
) -> None:
    for failure_point in ("snapshots", "backup", "forget"):
        repo_root, environment, _docker_log = _backup_fixture(tmp_path / failure_point)
        backup_dir = repo_root / "deploy" / "backups"
        backup_dir.mkdir()
        old_dump = backup_dir / "old.dump"
        old_sidecar = Path(f"{old_dump}.sha256")
        old_dump.write_bytes(b"old")
        old_sidecar.write_text(f"{hashlib.sha256(b'old').hexdigest()}  {old_dump}\n")
        old_time = time.time() - 40 * 24 * 60 * 60
        os.utime(old_dump, (old_time, old_time))
        os.utime(old_sidecar, (old_time, old_time))

        result = _run_backup(
            repo_root, environment | {"FAKE_RESTIC_FAIL_AT": failure_point}
        )

        final_dump = backup_dir / "20260102T030405Z.dump"
        sidecar = Path(f"{final_dump}.sha256")
        assert result.returncode != 0
        assert result.stdout == ""
        assert final_dump.read_bytes() == b"fixture dump bytes"
        assert sidecar.read_text().startswith(
            hashlib.sha256(final_dump.read_bytes()).hexdigest()
        )
        assert not old_dump.exists()
        assert not old_sidecar.exists()


def test_same_timestamp_collision_preserves_published_pair(tmp_path: Path) -> None:
    repo_root, environment, docker_log = _backup_fixture(tmp_path)
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir()
    final_dump = backup_dir / "20260102T030405Z.dump"
    sidecar = Path(f"{final_dump}.sha256")
    final_dump.write_bytes(b"published dump")
    sidecar.write_bytes(b"published sidecar\n")

    result = _run_backup(repo_root, environment)

    assert result.returncode != 0
    assert final_dump.read_bytes() == b"published dump"
    assert sidecar.read_bytes() == b"published sidecar\n"
    assert not docker_log.exists() or "pg_dump" not in docker_log.read_text(
        encoding="utf-8"
    )
