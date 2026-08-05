from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

DEPLOY_ROOT = Path(__file__).parents[1]
SNAPSHOT_ID = "a" * 64
BACKUP_NAME = "20260102T030405Z.dump"


def _metadata(*, tag: str = "ai-writing-assist-postgres") -> tuple[str, str]:
    remote_directory = "/other-host/production/backups"
    dump_path = f"{remote_directory}/{BACKUP_NAME}"
    snapshot = json.dumps(
        [
            {
                "id": SNAPSHOT_ID,
                "tags": [tag],
                "paths": [dump_path, f"{dump_path}.sha256"],
            }
        ]
    )
    listing = "\n".join(
        json.dumps(item)
        for item in (
            {"struct_type": "snapshot", "id": SNAPSHOT_ID},
            {"struct_type": "node", "type": "file", "path": dump_path},
            {
                "struct_type": "node",
                "type": "file",
                "path": f"{dump_path}.sha256",
            },
        )
    )
    return snapshot, f"{listing}\n"


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    repo_root = tmp_path / "repo"
    deploy_root = repo_root / "deploy"
    shutil.copytree(DEPLOY_ROOT / "scripts", deploy_root / "scripts")
    environment_file = deploy_root / ".env.production"
    shutil.copy2(DEPLOY_ROOT / "tests" / "fixtures" / "closed-test.env", environment_file)
    environment_file.chmod(0o600)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    restic_log = tmp_path / "restic.log"
    snapshot_json, listing_json = _metadata()
    payload = b"rehydrated dump"
    checksum = f"{hashlib.sha256(payload).hexdigest()}  remote-name.dump\n"
    (fake_bin / "restic").write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_RESTIC_LOG"\n'
        'case "${FAKE_RESTIC_FAIL_AT:-}" in\n'
        '  snapshots) case " $* " in *" snapshots "*) exit 1 ;; esac ;;\n'
        '  listing) case " $* " in *" ls "*) exit 1 ;; esac ;;\n'
        '  dump) case " $* " in *" dump "*) exit 1 ;; esac ;;\n'
        "esac\n"
        'case " $* " in\n'
        '  *" snapshots "*) printf "%s" "$FAKE_RESTIC_SNAPSHOTS_JSON" ;;\n'
        '  *" ls "*) printf "%s" "$FAKE_RESTIC_LISTING_JSON" ;;\n'
        '  *" dump "*)\n'
        '    last=; for argument in "$@"; do last=$argument; done\n'
        '    case "$last" in\n'
        '      *.sha256) printf "%s" "$FAKE_RESTIC_CHECKSUM" ;;\n'
        '      *) printf "%s" "$FAKE_RESTIC_DUMP" ;;\n'
        "    esac ;;\n"
        "esac\n"
    )
    (fake_bin / "restic").chmod(0o755)
    environment = os.environ | {
        "ENV_FILE": str(environment_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_RESTIC_LOG": str(restic_log),
        "FAKE_RESTIC_SNAPSHOTS_JSON": snapshot_json,
        "FAKE_RESTIC_LISTING_JSON": listing_json,
        "FAKE_RESTIC_DUMP": payload.decode(),
        "FAKE_RESTIC_CHECKSUM": checksum,
    }
    return repo_root, environment, restic_log


def _run(
    repo_root: Path, environment: dict[str, str], *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "deploy/scripts/rehydrate_backup.sh", *arguments],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_invalid_arguments_fail_before_lock_environment_or_restic(tmp_path: Path) -> None:
    repo_root, environment, restic_log = _fixture(tmp_path)

    result = _run(repo_root, environment, "bad", "../unsafe.dump")

    assert result.returncode == 2
    assert result.stdout == ""
    assert not restic_log.exists()
    assert not (repo_root / "deploy" / "backups").exists()

    extra = _run(repo_root, environment, SNAPSHOT_ID, BACKUP_NAME, "unexpected")
    assert extra.returncode == 2
    assert extra.stdout == ""
    assert not restic_log.exists()


def test_rehydrates_only_an_exact_validated_pair_and_prints_its_path(
    tmp_path: Path,
) -> None:
    repo_root, environment, restic_log = _fixture(tmp_path)

    result = _run(repo_root, environment, SNAPSHOT_ID, BACKUP_NAME)

    dump_path = repo_root / "deploy" / "backups" / BACKUP_NAME
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{dump_path}\n"
    assert dump_path.read_bytes() == b"rehydrated dump"
    assert Path(f"{dump_path}.sha256").read_text().startswith(
        hashlib.sha256(b"rehydrated dump").hexdigest()
    )
    assert not list(dump_path.parent.glob(".rehydrate-*"))
    commands = restic_log.read_text()
    assert f"snapshots --json {SNAPSHOT_ID}" in commands
    assert f"ls --json {SNAPSHOT_ID}" in commands
    assert sum(line.startswith("dump ") for line in commands.splitlines()) == 2


def test_rehydrate_rejects_metadata_dump_checksum_and_existing_pair(
    tmp_path: Path,
) -> None:
    for case, override in (
        ("tag", {"FAKE_RESTIC_SNAPSHOTS_JSON": _metadata(tag="wrong")[0]}),
        (
            "snapshot-id",
            {
                "FAKE_RESTIC_SNAPSHOTS_JSON": json.dumps(
                    [
                        {
                            "id": "b" * 64,
                            "tags": ["ai-writing-assist-postgres"],
                            "paths": [
                                "/x/20260102T030405Z.dump",
                                "/x/20260102T030405Z.dump.sha256",
                            ],
                        }
                    ]
                )
            },
        ),
        ("metadata", {"FAKE_RESTIC_LISTING_JSON": "not-json\n"}),
        (
            "extra-file",
            {
                "FAKE_RESTIC_LISTING_JSON": _metadata()[1]
                + json.dumps(
                    {
                        "struct_type": "node",
                        "type": "file",
                        "path": "/other-host/production/backups/extra.dump",
                    }
                )
                + "\n"
            },
        ),
        ("dump", {"FAKE_RESTIC_FAIL_AT": "dump"}),
        ("checksum", {"FAKE_RESTIC_CHECKSUM": "0" * 64 + "  x\n"}),
    ):
        repo_root, environment, _restic_log = _fixture(tmp_path / case)
        result = _run(repo_root, environment | override, SNAPSHOT_ID, BACKUP_NAME)
        backup_dir = repo_root / "deploy" / "backups"
        assert result.returncode != 0
        assert result.stdout == ""
        assert not (backup_dir / BACKUP_NAME).exists()
        assert not Path(f"{backup_dir / BACKUP_NAME}.sha256").exists()
        assert not list(backup_dir.glob(".rehydrate-*"))

    repo_root, environment, restic_log = _fixture(tmp_path / "existing")
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir()
    existing = backup_dir / BACKUP_NAME
    existing.write_bytes(b"do not overwrite")
    result = _run(repo_root, environment, SNAPSHOT_ID, BACKUP_NAME)
    assert result.returncode != 0
    assert existing.read_bytes() == b"do not overwrite"
    assert not restic_log.exists()


def test_rehydrate_fails_closed_when_restic_is_unavailable(tmp_path: Path) -> None:
    repo_root, environment, _restic_log = _fixture(tmp_path)
    fake_bin = Path(environment["PATH"].split(os.pathsep, maxsplit=1)[0])
    (fake_bin / "restic").unlink()

    result = _run(
        repo_root,
        environment | {"PATH": f"{fake_bin}{os.pathsep}/usr/bin{os.pathsep}/bin"},
        SNAPSHOT_ID,
        BACKUP_NAME,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "restic is required" in result.stderr


def test_rehydrate_cleans_only_known_stale_staging_files(tmp_path: Path) -> None:
    repo_root, environment, _restic_log = _fixture(tmp_path)
    backup_dir = repo_root / "deploy" / "backups"
    backup_dir.mkdir()
    stale = backup_dir / ".rehydrate-dump-stage.previous"
    stale.write_bytes(b"stale")
    final_dump = backup_dir / "unrelated.dump"
    final_dump.write_bytes(b"keep")

    result = _run(repo_root, environment, SNAPSHOT_ID, BACKUP_NAME)

    assert result.returncode == 0, result.stderr
    assert not stale.exists()
    assert final_dump.read_bytes() == b"keep"
