from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PUBLISHER = Path(__file__).parents[1] / "scripts" / "backup_pair_publish.py"
BACKUP_NAME = "20260102T030405Z.dump"


def _staging(directory: Path) -> tuple[Path, Path]:
    dump = directory / ".rehydrate-dump-stage.fixture"
    sidecar = directory / ".rehydrate-checksum-stage.fixture"
    dump.write_bytes(b"dump bytes")
    sidecar.write_bytes(b"checksum bytes")
    return dump, sidecar


def _run(directory: Path, dump: Path, sidecar: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PUBLISHER),
            "publish",
            str(directory),
            str(dump),
            str(sidecar),
            BACKUP_NAME,
        ],
        capture_output=True,
        text=True,
    )


def test_publish_links_a_complete_pair_then_removes_only_its_staging_files(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o700)
    dump, sidecar = _staging(backup_dir)

    result = _run(backup_dir, dump, sidecar)

    final_dump = backup_dir / BACKUP_NAME
    final_sidecar = Path(f"{final_dump}.sha256")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert final_dump.read_bytes() == b"dump bytes"
    assert final_sidecar.read_bytes() == b"checksum bytes"
    assert not dump.exists()
    assert not sidecar.exists()


def test_publish_preserves_preexisting_first_final_and_leaves_staging_for_adapter_cleanup(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o700)
    dump, sidecar = _staging(backup_dir)
    final_sidecar = backup_dir / f"{BACKUP_NAME}.sha256"
    final_sidecar.write_bytes(b"other writer sidecar")

    result = _run(backup_dir, dump, sidecar)

    assert result.returncode != 0
    assert result.stdout == ""
    assert final_sidecar.read_bytes() == b"other writer sidecar"
    assert not (backup_dir / BACKUP_NAME).exists()
    assert dump.exists()
    assert sidecar.exists()


def test_publish_removes_only_its_first_link_when_second_final_already_exists(
    tmp_path: Path,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o700)
    dump, sidecar = _staging(backup_dir)
    final_dump = backup_dir / BACKUP_NAME
    final_dump.write_bytes(b"other writer dump")

    result = _run(backup_dir, dump, sidecar)

    final_sidecar = Path(f"{final_dump}.sha256")
    assert result.returncode != 0
    assert result.stdout == ""
    assert final_dump.read_bytes() == b"other writer dump"
    assert not final_sidecar.exists()
    assert dump.exists()
    assert sidecar.exists()
