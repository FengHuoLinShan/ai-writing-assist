import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path


DEPLOY_ROOT = Path(__file__).parents[1]
COMMON_SCRIPT = DEPLOY_ROOT / "scripts" / "common.sh"


def _run_checksum_verification(backup_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            "-c",
            '. "$0"; verify_backup_checksum "$1"',
            str(COMMON_SCRIPT),
            str(backup_path),
        ],
        capture_output=True,
        text=True,
    )


def _run_sha256_digest(backup_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "sh",
            "-c",
            '. "$0"; sha256_digest "$1"',
            str(COMMON_SCRIPT),
            str(backup_path),
        ],
        capture_output=True,
        text=True,
    )


def _write_checksum(backup_path: Path, contents: str) -> Path:
    checksum_path = Path(f"{backup_path}.sha256")
    checksum_path.write_text(contents)
    return checksum_path


def test_backup_checksum_accepts_matching_digest_without_trusting_sidecar_path(
    tmp_path: Path,
) -> None:
    backup_path = tmp_path / "selected.dump"
    backup_path.write_bytes(b"known backup contents")
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    _write_checksum(backup_path, f"{digest}  not-the-selected-backup.dump\n")

    result = _run_checksum_verification(backup_path)

    assert result.returncode == 0, result.stderr


def test_sha256_digest_requires_a_supported_command_and_valid_output(tmp_path: Path) -> None:
    backup_path = tmp_path / "selected.dump"
    backup_path.write_bytes(b"known backup contents")
    expected_digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()

    normal = _run_sha256_digest(backup_path)
    assert normal.returncode == 0, normal.stderr
    assert normal.stdout == f"{expected_digest}\n"

    awk_only_bin = tmp_path / "awk-only-bin"
    awk_only_bin.mkdir()
    awk_path = shutil.which("awk")
    assert awk_path is not None
    (awk_only_bin / "awk").symlink_to(awk_path)
    unavailable = subprocess.run(
        [
            "sh",
            "-c",
            '. "$0"; PATH="$1"; export PATH; sha256_digest "$2"',
            str(COMMON_SCRIPT),
            str(awk_only_bin),
            str(backup_path),
        ],
        capture_output=True,
        text=True,
    )

    assert unavailable.returncode != 0
    assert unavailable.stderr.strip()


def test_backup_checksum_refuses_missing_symlink_malformed_multiple_and_mismatch(
    tmp_path: Path,
) -> None:
    backup_path = tmp_path / "selected.dump"
    backup_path.write_bytes(b"known backup contents")
    valid_digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    checksum_path = Path(f"{backup_path}.sha256")

    missing = _run_checksum_verification(backup_path)
    assert missing.returncode != 0

    target = tmp_path / "checksum-target"
    target.write_text(f"{valid_digest}  selected.dump\n")
    checksum_path.symlink_to(target)
    symlink = _run_checksum_verification(backup_path)
    assert symlink.returncode != 0
    checksum_path.unlink()

    for contents in (
        "",
        "not-a-digest  selected.dump\n",
        f"{valid_digest}  selected.dump\n{valid_digest}  selected.dump\n",
        f"{'0' * 64}  selected.dump\n",
    ):
        _write_checksum(backup_path, contents)
        result = _run_checksum_verification(backup_path)
        assert result.returncode != 0, contents


def test_shared_health_wait_requires_api_frontend_and_worker(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >>\"$FAKE_DOCKER_LOG\"\n"
        "case \" $* \" in\n"
        "  *' exec -T api '*) exit 0 ;;\n"
        "  *' exec -T frontend '*) exit 0 ;;\n"
        "  *' exec -T worker '*) test \"$FAKE_WORKER_HEALTH\" != fail ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n"
    )
    fake_docker.chmod(0o755)
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n")
    fake_sleep.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
    }

    result = subprocess.run(
        ["sh", "-c", '. "$0"; wait_for_application_health', str(COMMON_SCRIPT)],
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    calls = docker_log.read_text()
    assert "exec -T api python -c" in calls
    assert "exec -T frontend sh -ec" in calls
    assert "exec -T worker python -c" in calls
    assert "run_worker.py" in calls

    failed_worker = subprocess.run(
        ["sh", "-c", '. "$0"; wait_for_application_health', str(COMMON_SCRIPT)],
        capture_output=True,
        text=True,
        env=environment | {"FAKE_WORKER_HEALTH": "fail"},
    )

    assert failed_worker.returncode != 0


def test_runtime_auth_mode_is_shared_by_api_and_worker() -> None:
    compose = (DEPLOY_ROOT / "compose.production.yml").read_text()
    runtime_section, api_and_services = compose.split("x-api-environment:", maxsplit=1)

    assert "AUTH_MODE: ${AUTH_MODE:?Choose AUTH_MODE" in runtime_section
    assert "environment: *api-environment" in api_and_services
    assert "environment: *runtime-environment" in api_and_services


def test_release_only_accepts_commits_reachable_from_origin_main() -> None:
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text()

    assert 'if [ "${#RELEASE_REF}" -ne 40 ]; then' in release_script
    assert 'git -C "$REPO_ROOT" fetch --prune origin' in release_script
    assert (
        'git -C "$REPO_ROOT" merge-base --is-ancestor "$TARGET_COMMIT" origin/main'
    ) in release_script
    assert "umask 022" in release_script


def test_backup_stdout_is_reserved_for_machine_readable_path() -> None:
    backup_script = (DEPLOY_ROOT / "scripts" / "backup.sh").read_text()
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text()
    restore_script = (DEPLOY_ROOT / "scripts" / "restore.sh").read_text()

    assert "validate_environment >&2" in backup_script
    assert 'BACKUP_PATH=$(bash "$SCRIPT_DIR/backup.sh")' in release_script
    assert 'SAFETY_BACKUP=$(bash "$SCRIPT_DIR/backup.sh")' in restore_script
    assert "printf '%s\\n' \"$BACKUP_PATH\"" in backup_script
    assert "printf '%s  %s\\n' \"$BACKUP_DIGEST\" \"$BACKUP_PATH\"" in backup_script


def test_release_and_restore_use_shared_application_health_gate() -> None:
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text()
    restore_script = (DEPLOY_ROOT / "scripts" / "restore.sh").read_text()
    dockerfile = (DEPLOY_ROOT.parent / "frontend-console" / "Dockerfile").read_text()

    assert "chmod -R a+rX /usr/share/nginx/html" in dockerfile
    assert "umask 022" in restore_script
    assert "wait_for_application_health" in release_script
    assert "wait_for_application_health" in restore_script
    assert "frontend_runtime_healthy" not in release_script
    common_script = COMMON_SCRIPT.read_text()
    for asset in ("/ui/modal.js", "/apiContracts.js", "/router.js"):
        assert asset in common_script


def test_restore_verifies_checksum_before_confirmation_and_database_replacement() -> None:
    restore_script = (DEPLOY_ROOT / "scripts" / "restore.sh").read_text()
    first_check = restore_script.index("verify_backup_checksum")
    second_check = restore_script.index("verify_backup_checksum", first_check + 1)

    assert first_check < restore_script.index("Type RESTORE_PRODUCTION_BACKUP")
    assert second_check > restore_script.index('if [ "$CONFIRMATION"')
    assert second_check < restore_script.index("compose stop api worker frontend")
    assert second_check < restore_script.index("compose exec -T postgres dropdb")
    assert second_check < restore_script.index("    --exit-on-error <")


def test_release_and_restore_commit_state_only_after_shared_health_gate() -> None:
    for script_name in ("release.sh", "restore.sh"):
        script = (DEPLOY_ROOT / "scripts" / script_name).read_text()
        health_gate = script.index("if ! wait_for_application_health; then")
        current_commit = script.index('write_state_file "$STATE_DIR/current-commit"')
        current_backup = script.index('write_state_file "$STATE_DIR/current-backup"')
        current_release = script.index('write_state_file "$STATE_DIR/current-release"')

        assert health_gate < current_commit < current_backup < current_release


def test_common_and_compose_declare_worker_process_health() -> None:
    common_script = COMMON_SCRIPT.read_text()
    compose = (DEPLOY_ROOT / "compose.production.yml").read_text()
    worker_section = compose.split("  worker:", maxsplit=1)[1].split(
        "  frontend:", maxsplit=1
    )[0]

    assert "worker_runtime_healthy" in common_script
    assert "Path('/proc/1/cmdline').read_bytes()" in common_script
    assert "b'run_worker.py'" in common_script
    assert "healthcheck:" in worker_section
    assert "b'run_worker.py'" in worker_section
    for setting in ("interval: 15s", "timeout: 5s", "start_period: 20s", "retries: 8"):
        assert setting in worker_section


def test_atomic_state_write_replaces_content_without_temp_file_residue(tmp_path: Path) -> None:
    state_path = tmp_path / "state" / "current-release"

    for value in ("release-one", "release-two"):
        result = subprocess.run(
            [
                "sh",
                "-c",
                '. "$0"; write_state_file "$1" "$2"',
                str(COMMON_SCRIPT),
                str(state_path),
                value,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert state_path.read_text() == f"{value}\n"
        assert not list(state_path.parent.glob(".current-release.tmp.*"))


def test_public_verification_fetches_declared_frontend_assets() -> None:
    verification_script = (DEPLOY_ROOT / "scripts" / "verify_public.sh").read_text()

    assert "FrontendAssetParser" in verification_script
    assert "frontend-assets.tsv" in verification_script
    assert "--write-out '%{content_type}'" in verification_script


def test_public_bootstrap_passes_named_email_argument() -> None:
    common_script = (DEPLOY_ROOT / "scripts" / "common.sh").read_text()

    assert (
        'claim-legacy \\\n                --email "$bootstrap_email"' in common_script
    )


def test_openresty_renders_loopback_tunnel_origin() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(DEPLOY_ROOT / "scripts" / "render_openresty.py"),
            "--env",
            str(DEPLOY_ROOT / "tests" / "fixtures" / "closed-test.env"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "listen 127.0.0.1:3259;" in result.stdout
    assert "listen 443" not in result.stdout
    assert "ssl_certificate" not in result.stdout
