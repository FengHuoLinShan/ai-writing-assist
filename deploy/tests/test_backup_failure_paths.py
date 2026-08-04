from __future__ import annotations

import hashlib
import os
import shutil
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
        "  *' pg_isready '*) exit 0 ;;\n"
        "  *' pg_dump '*) printf 'fixture dump bytes'; test \"${FAKE_PG_DUMP_FAIL:-0}\" != 1 ;;\n"
        "  *' pg_restore '*) exit 0 ;;\n"
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
    repo_root: Path, environment: dict[str, str], *, fail_second_mv: bool = False
) -> subprocess.CompletedProcess[str]:
    subprocess_environment = environment.copy()
    fake_mv = (
        Path(subprocess_environment["PATH"].split(os.pathsep, maxsplit=1)[0]) / "mv"
    )
    if fail_second_mv:
        real_mv = shutil.which("mv")
        assert real_mv is not None
        subprocess_environment["FAKE_MV_COUNTER"] = str(repo_root / ".fake-mv-count")
        subprocess_environment["FAKE_REAL_MV"] = real_mv
        fake_mv.write_text(
            "#!/bin/sh\n"
            "count=0\n"
            'if [ -f "$FAKE_MV_COUNTER" ]; then count=$(cat "$FAKE_MV_COUNTER"); fi\n'
            "count=$((count + 1))\n"
            'printf "%s\\n" "$count" >"$FAKE_MV_COUNTER"\n'
            'if [ "$count" -eq 2 ]; then exit 1; fi\n'
            'exec "$FAKE_REAL_MV" "$@"\n'
        )
        fake_mv.chmod(0o755)

    try:
        return subprocess.run(
            ["/bin/sh", "deploy/scripts/backup.sh"],
            cwd=repo_root,
            env=subprocess_environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        if fail_second_mv:
            fake_mv.unlink()


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


def test_failed_checksum_publish_cleans_the_just_published_half_pair(
    tmp_path: Path,
) -> None:
    repo_root, environment, _docker_log = _backup_fixture(tmp_path)

    result = _run_backup(repo_root, environment, fail_second_mv=True)

    backup_dir = repo_root / "deploy" / "backups"
    final_dump = backup_dir / "20260102T030405Z.dump"
    assert result.returncode != 0
    assert result.stdout == ""
    assert (repo_root / ".fake-mv-count").read_text() == "2\n"
    assert not final_dump.exists()
    assert not Path(f"{final_dump}.sha256").exists()
    assert not list(backup_dir.glob(".backup-stage.*"))
    assert not list(backup_dir.glob(".backup-checksum-stage.*"))


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
