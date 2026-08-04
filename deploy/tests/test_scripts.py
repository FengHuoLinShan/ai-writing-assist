import hashlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

DEPLOY_ROOT = Path(__file__).parents[1]
COMMON_SCRIPT = DEPLOY_ROOT / "scripts" / "common.sh"
FRONTEND_ASSET_VALIDATOR = DEPLOY_ROOT / "scripts" / "validate_frontend_assets.py"
RUNTIME_HEALTH_SCRIPT = DEPLOY_ROOT / "scripts" / "runtime_health.sh"
VERIFY_PUBLIC_SCRIPT = DEPLOY_ROOT / "scripts" / "verify_public.sh"
CLOSED_TEST_ENV = DEPLOY_ROOT / "tests" / "fixtures" / "closed-test.env"
EMBEDDING_CHECK_SCRIPT = DEPLOY_ROOT.parent / "backend" / "scripts" / "check_embedding.py"

_RUNTIME_PATHS = [
    "/",
    "/index.html",
    "/asset-manifest.json",
    "/asset-inventory.txt",
    "/shared/esc.js",
    "/ui/toast.js",
    "/ui/modal.js",
    "/stateSlices.js",
    "/state.js",
    "/apiContracts.js",
    "/router.js",
    "/commands.js",
    "/assets/app.js",
]


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


def test_sha256_digest_requires_a_supported_command_and_valid_output(
    tmp_path: Path,
) -> None:
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
        'printf \'%s\\n\' "$*" >>"$FAKE_DOCKER_LOG"\n'
        'case " $* " in\n'
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
    assert "exec -T worker python infrastructure/tasks/liveness.py" in calls

    failed_worker = subprocess.run(
        ["sh", "-c", '. "$0"; wait_for_application_health', str(COMMON_SCRIPT)],
        capture_output=True,
        text=True,
        env=environment | {"FAKE_WORKER_HEALTH": "fail"},
    )

    assert failed_worker.returncode != 0


def _run_worker_health_contract(
    tmp_path: Path,
    marker_contents: bytes | None,
    *,
    marker_symlink: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    repo_root = tmp_path / "repo"
    deploy_dir = repo_root / "deploy"
    deploy_dir.mkdir(parents=True)
    marker = deploy_dir / "worker-liveness-contract.version"
    if marker_contents is not None:
        marker.write_bytes(marker_contents)
    if marker_symlink:
        marker_target = tmp_path / "marker-target"
        marker_target.write_bytes(b"1\n")
        marker.symlink_to(marker_target)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_DOCKER_LOG"\n'
        "exit 0\n"
    )
    fake_docker.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
    }
    result = subprocess.run(
        [
            "sh",
            "-c",
            '. "$1"; REPO_ROOT="$2"; worker_runtime_healthy',
            "sh",
            str(COMMON_SCRIPT),
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""


def test_worker_health_contract_uses_legacy_only_when_marker_is_absent(
    tmp_path: Path,
) -> None:
    legacy, legacy_calls = _run_worker_health_contract(tmp_path / "legacy", None)
    v1, v1_calls = _run_worker_health_contract(tmp_path / "v1", b"1\n")

    assert legacy.returncode == 0, legacy.stderr
    assert "exec -T worker python -c" in legacy_calls
    assert "argv = Path('/proc/1/cmdline').read_bytes().split" in legacy_calls
    assert v1.returncode == 0, v1.stderr
    assert "exec -T worker python infrastructure/tasks/liveness.py" in v1_calls


@pytest.mark.parametrize(
    ("marker_contents", "marker_symlink"),
    ((b"2\n", False), (b"1\n1\n", False), (None, True)),
)
def test_worker_health_contract_fails_closed_for_invalid_or_symlink_marker(
    tmp_path: Path,
    marker_contents: bytes | None,
    marker_symlink: bool,
) -> None:
    result, calls = _run_worker_health_contract(
        tmp_path,
        marker_contents,
        marker_symlink=marker_symlink,
    )

    assert result.returncode != 0
    assert calls == ""


def test_runtime_auth_mode_is_shared_by_api_and_worker() -> None:
    compose = (DEPLOY_ROOT / "compose.production.yml").read_text()
    runtime_section, api_and_services = compose.split("x-api-environment:", maxsplit=1)

    assert "AUTH_MODE: ${AUTH_MODE:?Choose AUTH_MODE" in runtime_section
    assert "environment: *api-environment" in api_and_services
    assert "environment: *runtime-environment" in api_and_services


def test_compose_uses_one_bounded_logging_extension_for_every_service() -> None:
    compose = (DEPLOY_ROOT / "compose.production.yml").read_text()
    extension, services_and_below = compose.split("x-runtime-environment:", maxsplit=1)
    services, _ = services_and_below.split("\nvolumes:", maxsplit=1)

    assert "x-bounded-logging: &bounded-logging" in extension
    assert "driver: local" in extension
    assert 'max-size: "10m"' in extension
    assert 'max-file: "10"' in extension

    service_names = (
        "postgres",
        "embedding",
        "api",
        "worker",
        "frontend",
        "migrate",
        "account-maintenance",
    )
    assert compose.count("logging: *bounded-logging") == len(service_names)
    for index, service_name in enumerate(service_names):
        service_start = services.index(f"  {service_name}:\n")
        service_end = (
            services.index(f"  {service_names[index + 1]}:\n", service_start + 1)
            if index + 1 < len(service_names)
            else len(services)
        )
        service_section = services[service_start:service_end]
        assert "logging: *bounded-logging" in service_section


def test_first_party_services_use_the_shared_read_only_runtime_policy() -> None:
    compose_path = DEPLOY_ROOT / "compose.production.yml"
    compose_text = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)
    assert isinstance(compose, dict)

    expected_policy = {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
    }
    assert compose["x-first-party-runtime-hardening"] == expected_policy
    services = compose["services"]
    assert isinstance(services, dict)
    first_party_services = (
        "api",
        "worker",
        "frontend",
        "migrate",
        "account-maintenance",
    )
    backend_services = ("api", "worker", "migrate", "account-maintenance")

    assert compose_text.count("&first-party-runtime-hardening") == 1
    assert compose_text.count("<<: *first-party-runtime-hardening") == len(
        first_party_services
    )
    for service_name in first_party_services:
        service = services[service_name]
        assert isinstance(service, dict)
        assert {key: service[key] for key in expected_policy} == expected_policy
        assert "privileged" not in service

    for service_name in backend_services:
        assert services[service_name]["tmpfs"] == ["/tmp:mode=1777"]
    assert services["frontend"]["tmpfs"] == [
        "/run:mode=0755,uid=101,gid=101",
        "/var/cache/nginx:mode=0755,uid=101,gid=101",
    ]

    for service_name in ("postgres", "embedding"):
        service = services[service_name]
        assert isinstance(service, dict)
        assert not set(expected_policy) & set(service)
        assert "tmpfs" not in service


def test_production_database_image_is_explicitly_tagged_and_digest_pinned() -> None:
    compose = (DEPLOY_ROOT / "compose.production.yml").read_text(encoding="utf-8")
    example = (DEPLOY_ROOT / ".env.production.example").read_text(encoding="utf-8")
    expected = (
        "docker.m.daocloud.io/pgvector/pgvector:0.8.6-pg17-bookworm@sha256:"
        "7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38"
    )

    assert f"image: ${{POSTGRES_IMAGE:-{expected}}}" in compose
    assert f"POSTGRES_IMAGE={expected}" in example


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
    assert 'printf \'%s  %s\\n\' "$BACKUP_DIGEST" "$BACKUP_PATH"' in backup_script


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
    assert second_check < restore_script.index("compose stop api worker frontend", second_check)
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


def test_release_and_restore_restore_the_finalized_state_checkout_on_failure() -> None:
    common_script = COMMON_SCRIPT.read_text(encoding="utf-8")

    assert "resolve_active_deployment_commit()" in common_script
    assert "current-release" in common_script
    assert "current-commit" in common_script

    for script_name in ("release.sh", "restore.sh"):
        script = (DEPLOY_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        previous_commit = script.index(
            "PREVIOUS_COMMIT=$(resolve_active_deployment_commit)"
        )
        cleanup_trap = script.index(
            "trap cleanup_uncommitted_attempt EXIT HUP INT TERM"
        )
        checkout = script.index(
            'git -C "$REPO_ROOT" checkout --detach "$TARGET_COMMIT"'
        )
        current_release = script.index(
            'write_state_file "$STATE_DIR/current-release" "$RELEASE_ID"'
        )
        committed = script.index("DEPLOYMENT_COMMITTED=true")

        assert previous_commit < cleanup_trap < checkout
        assert current_release < committed


def test_release_and_restore_quiesce_before_rollback_or_database_mutation() -> None:
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text()
    restore_script = (DEPLOY_ROOT / "scripts" / "restore.sh").read_text()

    release_quiesce = release_script.index("if ! compose stop api worker frontend; then")
    release_backup = release_script.index('BACKUP_PATH=$(bash "$SCRIPT_DIR/backup.sh")')
    release_migrate = release_script.index("compose --profile ops run --rm migrate")
    release_target_up = release_script.index(
        "compose up -d api worker frontend", release_quiesce
    )
    release_health = release_script.index("if ! wait_for_application_health; then")

    assert release_quiesce < release_backup < release_migrate < release_target_up
    assert release_target_up < release_health
    assert "compose stop api worker frontend >/dev/null 2>&1 || true" not in (
        release_script[release_quiesce:release_backup]
    )

    first_checksum = restore_script.index("verify_backup_checksum")
    second_checksum = restore_script.index("verify_backup_checksum", first_checksum + 1)
    restore_quiesce = restore_script.index(
        "if ! compose stop api worker frontend; then", second_checksum
    )
    safety_backup = restore_script.index('SAFETY_BACKUP=$(bash "$SCRIPT_DIR/backup.sh")')
    drop_database = restore_script.index("compose exec -T postgres dropdb")
    restore_database = restore_script.index("    --exit-on-error <")
    restore_migrate = restore_script.index("compose --profile ops run --rm migrate")

    assert second_checksum < restore_quiesce < safety_backup < drop_database
    assert drop_database < restore_database < restore_migrate
    assert "compose stop api worker frontend >/dev/null 2>&1 || true" not in (
        restore_script[restore_quiesce:safety_backup]
    )


def test_common_and_compose_declare_worker_process_health() -> None:
    common_script = COMMON_SCRIPT.read_text()
    compose_path = DEPLOY_ROOT / "compose.production.yml"
    compose = compose_path.read_text()
    compose_data = yaml.safe_load(compose)
    worker_section = compose.split("  worker:", maxsplit=1)[1].split(
        "  frontend:", maxsplit=1
    )[0]

    assert "worker_runtime_healthy" in common_script
    marker = DEPLOY_ROOT / "worker-liveness-contract.version"
    assert marker.is_file()
    assert not marker.is_symlink()
    assert marker.read_bytes() == b"1\n"
    assert "python infrastructure/tasks/liveness.py" in common_script
    assert "argv = Path('/proc/1/cmdline').read_bytes().split" in common_script
    assert "b'run_worker.py' in Path('/proc/1/cmdline')" not in common_script
    assert "healthcheck:" in worker_section
    assert compose_data["services"]["worker"]["healthcheck"]["test"] == [
        "CMD",
        "python",
        "infrastructure/tasks/liveness.py",
    ]
    assert compose_data["services"]["worker"]["stop_grace_period"] == "2m"
    assert "b'run_worker.py'" not in worker_section
    for setting in ("interval: 15s", "timeout: 5s", "start_period: 20s", "retries: 8"):
        assert setting in worker_section


def test_atomic_state_write_replaces_content_without_temp_file_residue(
    tmp_path: Path,
) -> None:
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
    validator = FRONTEND_ASSET_VALIDATOR.read_text()

    assert "validate_frontend_assets.py" in verification_script
    assert "FrontendAssetParser" in validator
    assert "asset-inventory.txt" in verification_script
    assert "--max-filesize 65536" in verification_script
    assert "Frontend asset inventory has duplicate entries" in validator
    assert "--write-out '%{content_type}'" in verification_script


def _run_frontend_asset_health(
    tmp_path: Path,
    inventory: str | bytes | None,
    marker: str | None = "1\n",
    *,
    missing_path: str | None = None,
    symlink_path: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    repo_root = tmp_path / "repo"
    deploy_dir = repo_root / "deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        (deploy_dir / "frontend-asset-contract.version").write_text(marker)

    html_root = tmp_path / "html"
    html_root.mkdir(exist_ok=True)
    inventory_text = (
        None
        if inventory is None
        else (inventory if isinstance(inventory, str) else inventory.decode("utf-8"))
    )
    public_paths = (
        _RUNTIME_PATHS if inventory_text is None else inventory_text.splitlines()
    )
    for public_path in public_paths:
        if (
            not public_path.startswith("/")
            or ".." in public_path.split("/")
            or public_path.startswith("//")
            or any(ord(character) < 32 for character in public_path)
            or len(public_path) > 200
        ):
            continue
        relative_path = "index.html" if public_path == "/" else public_path.lstrip("/")
        asset_path = html_root / relative_path
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_text("asset")
    if inventory is not None:
        if isinstance(inventory, bytes):
            (html_root / "asset-inventory.txt").write_bytes(inventory)
        else:
            (html_root / "asset-inventory.txt").write_text(inventory)
    else:
        (html_root / "asset-inventory.txt").unlink(missing_ok=True)
    if missing_path:
        missing_file = html_root / (
            "index.html" if missing_path == "/" else missing_path.lstrip("/")
        )
        missing_file.unlink(missing_ok=True)
    if symlink_path:
        linked_file = html_root / (
            "index.html" if symlink_path == "/" else symlink_path.lstrip("/")
        )
        linked_file.unlink(missing_ok=True)
        target = html_root / "symlink-target"
        target.write_text("asset")
        linked_file.symlink_to(target)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fetch_log = tmp_path / "fetch.log"
    fetch_log.write_text("")
    fake_wget = fake_bin / "wget"
    fake_wget.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >>"$FETCH_LOG"\nexit 0\n')
    fake_wget.chmod(0o755)
    environment = os.environ | {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FETCH_LOG": str(fetch_log),
        "TEST_HTML": str(html_root),
    }
    result = subprocess.run(
        [
            "sh",
            "-c",
            """
. "$1"
REPO_ROOT="$2"
compose() {
    test "$1" = exec || exit 1
    command=$(printf '%s' "$6" | sed "s|/usr/share/nginx/html|$TEST_HTML|g")
    sh -ec "$command"
}
frontend_runtime_healthy
""",
            "sh",
            str(COMMON_SCRIPT),
            str(repo_root),
        ],
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, fetch_log.read_text() if fetch_log.exists() else ""


def test_frontend_health_uses_legacy_fallback_only_without_contract_marker(
    tmp_path: Path,
) -> None:
    result, fetches = _run_frontend_asset_health(tmp_path, inventory=None, marker=None)

    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:8080/router.js" in fetches
    assert "asset-inventory.txt" not in fetches


def test_frontend_health_requires_and_fetches_every_v1_inventory_asset(
    tmp_path: Path,
) -> None:
    inventory_paths = _RUNTIME_PATHS
    result, fetches = _run_frontend_asset_health(
        tmp_path,
        "\n".join(inventory_paths) + "\n",
    )

    assert result.returncode == 0, result.stderr
    for path in inventory_paths:
        assert f"http://127.0.0.1:8080{path}" in fetches


def test_frontend_health_rejects_missing_or_symlinked_files_even_when_wget_succeeds(
    tmp_path: Path,
) -> None:
    inventory = "\n".join(_RUNTIME_PATHS) + "\n"
    for keyword, kwargs in (
        ("missing", {"missing_path": "/router.js"}),
        ("symlink", {"symlink_path": "/asset-manifest.json"}),
    ):
        result, fetches = _run_frontend_asset_health(tmp_path, inventory, **kwargs)
        assert result.returncode != 0, keyword
        failed_path = kwargs.get("missing_path") or kwargs.get("symlink_path")
        assert f"http://127.0.0.1:8080{failed_path}" not in fetches


def test_frontend_health_fails_closed_for_invalid_v1_marker_or_inventory(
    tmp_path: Path,
) -> None:
    valid_inventory = "\n".join(_RUNTIME_PATHS) + "\n"
    cases = [
        (None, "1\n"),
        (valid_inventory + "/assets/app.js\n", "1\n"),
        (valid_inventory.replace("/assets/app.js", "/assets/../app.js"), "1\n"),
        ("/assets/app.js\n" * 513, "1\n"),
        (
            "\n".join(_RUNTIME_PATHS + [f"/assets/{index}.js" for index in range(500)]),
            "1\n",
        ),
        (f"/{'a' * 65536}", "1\n"),
        (valid_inventory, "2\n"),
        (valid_inventory, "1\n1\n"),
        (valid_inventory.encode() + b"\x00", "1\n"),
        (valid_inventory.encode() + b"\t", "1\n"),
    ]

    for inventory, marker in cases:
        result, _ = _run_frontend_asset_health(tmp_path, inventory, marker)
        assert result.returncode != 0, (inventory, marker)


def test_current_checkout_requires_the_exact_tracked_frontend_contract_marker() -> None:
    marker = DEPLOY_ROOT / "frontend-asset-contract.version"

    assert marker.is_file()
    assert not marker.is_symlink()
    assert marker.read_bytes() == b"1\n"


def _run_public_asset_validator(
    tmp_path: Path,
    index_html: str,
    inventory: bytes | None = None,
) -> subprocess.CompletedProcess[str]:
    index_path = tmp_path / "index.html"
    index_path.write_text(index_html)
    command = [sys.executable, str(FRONTEND_ASSET_VALIDATOR), "--index", str(index_path)]
    if inventory is not None:
        inventory_path = tmp_path / "asset-inventory.txt"
        inventory_path.write_bytes(inventory)
        command.extend(["--inventory", str(inventory_path)])
    return subprocess.run(command, capture_output=True, text=True)


def test_public_asset_validator_accepts_v1_and_legacy_contracts(tmp_path: Path) -> None:
    index = '<script src="/assets/app.js"></script><script src="https://cdn.example/app.js"></script>'

    legacy = _run_public_asset_validator(tmp_path, index)
    v1 = _run_public_asset_validator(
        tmp_path,
        index,
        "\n".join(_RUNTIME_PATHS).encode() + b"\n",
    )

    assert legacy.returncode == 0, legacy.stderr
    assert legacy.stdout.splitlines() == ["/assets/app.js"]
    assert v1.returncode == 0, v1.stderr
    assert "/asset-manifest.json" in v1.stdout


def test_public_asset_validator_rejects_unsafe_and_incomplete_v1_contracts(
    tmp_path: Path,
) -> None:
    valid_inventory = "\n".join(_RUNTIME_PATHS).encode() + b"\n"
    unsafe_index_references = (
        "//host.example/app.js",
        "/assets/.hidden.js",
        "/assets/../app.js",
        "/assets/app.js?cache=1",
        "/assets/app.js#fragment",
        "/assets\\app.js",
    )
    for reference in unsafe_index_references:
        result = _run_public_asset_validator(
            tmp_path,
            f'<script src="{reference}"></script>',
        )
        assert result.returncode != 0, reference

    invalid_inventories = (
        b"",
        valid_inventory + b"/assets/app.js\n",
        valid_inventory.replace(b"/assets/app.js", b"/assets/.hidden.js"),
        valid_inventory.replace(b"/assets/app.js", b"/assets/../app.js"),
        "\n".join(
            _RUNTIME_PATHS + [f"/assets/{index}.js" for index in range(500)]
        ).encode(),
        b"/" + b"a" * 65536,
        b"\n".join(path.encode() for path in _RUNTIME_PATHS if path != "/router.js")
        + b"\n",
    )
    for inventory in invalid_inventories:
        result = _run_public_asset_validator(
            tmp_path,
            '<script src="/assets/app.js"></script>',
            inventory,
        )
        assert result.returncode != 0, inventory[:80]

    subset = _run_public_asset_validator(
        tmp_path,
        '<script src="/assets/not-listed.js"></script>',
        valid_inventory,
    )
    assert subset.returncode != 0


def test_public_bootstrap_passes_named_email_argument() -> None:
    common_script = (DEPLOY_ROOT / "scripts" / "common.sh").read_text()

    assert 'claim-legacy \\\n                --email "$bootstrap_email"' in common_script


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

    api_location = result.stdout.split("location /api/ {", maxsplit=1)[1].split(
        "location / {", maxsplit=1
    )[0]
    frontend_location = result.stdout.split("location / {", maxsplit=1)[1]
    for location in (api_location, frontend_location):
        assert "proxy_set_header X-Real-IP $http_cf_connecting_ip;" in location
        assert "proxy_set_header X-Forwarded-For $http_cf_connecting_ip;" in location
    assert "$proxy_add_x_forwarded_for" not in result.stdout


def _copy_safe_test_env(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    env_file = tmp_path / ".env.production"
    env_file.write_text(CLOSED_TEST_ENV.read_text(encoding="utf-8"), encoding="utf-8")
    env_file.chmod(0o600)
    return env_file


def _write_runtime_health_fakes(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    event_log = tmp_path / "runtime-health-events.log"
    event_log.write_text("")

    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        'printf "curl:%s\\n" "$*" >>"$FAKE_EVENT_LOG"\n'
        "exit 0\n"
    )
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        'printf "docker:%s\\n" "$*" >>"$FAKE_EVENT_LOG"\n'
        'case "$*" in\n'
        '    *"scripts/check_embedding.py"*) test "${FAKE_EMBEDDING_FAIL:-0}" != 1 ;;\n'
        '    *) test "${FAKE_DOCKER_FAIL:-0}" != 1 ;;\n'
        "esac\n"
    )
    fake_bash = fake_bin / "bash"
    fake_bash.write_text(
        "#!/bin/sh\n"
        'printf "bash:%s\\n" "$*" >>"$FAKE_EVENT_LOG"\n'
        'exit "${FAKE_BASH_STATUS:-0}"\n'
    )
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n")
    for executable in (fake_curl, fake_docker, fake_bash, fake_sleep):
        executable.chmod(0o755)
    return fake_bin, event_log


def _run_runtime_health(
    tmp_path: Path,
    *,
    docker_fails: bool = False,
    embedding_fails: bool = False,
    public_check_status: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    env_file = _copy_safe_test_env(tmp_path)
    fake_bin, event_log = _write_runtime_health_fakes(tmp_path)
    environment = os.environ | {
        "ENV_FILE": str(env_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_EVENT_LOG": str(event_log),
        "FAKE_DOCKER_FAIL": "1" if docker_fails else "0",
        "FAKE_EMBEDDING_FAIL": "1" if embedding_fails else "0",
        "FAKE_BASH_STATUS": str(public_check_status),
    }
    result = subprocess.run(
        ["sh", str(RUNTIME_HEALTH_SCRIPT)],
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, event_log.read_text(encoding="utf-8").splitlines()


def test_runtime_health_script_reports_start_success_and_fail_without_masking_subject_failures(
    tmp_path: Path,
) -> None:
    success, success_events = _run_runtime_health(tmp_path / "success")

    assert success.returncode == 0, success.stderr
    start = next(
        index
        for index, event in enumerate(success_events)
        if event.endswith("/runtime-fixture/start")
    )
    api = next(
        index for index, event in enumerate(success_events) if "exec -T api" in event
    )
    embedding = next(
        index
        for index, event in enumerate(success_events)
        if "scripts/check_embedding.py" in event
    )
    public = next(
        index
        for index, event in enumerate(success_events)
        if event.startswith("bash:") and event.endswith("verify_public.sh --runtime")
    )
    completed = next(
        index
        for index, event in enumerate(success_events)
        if event.endswith("/runtime-fixture")
    )
    assert start < api < embedding < public < completed
    assert not any(event.endswith("/runtime-fixture/fail") for event in success_events)

    local_failure, local_failure_events = _run_runtime_health(
        tmp_path / "local-failure", docker_fails=True
    )

    assert local_failure.returncode != 0
    assert any(event.endswith("/runtime-fixture/fail") for event in local_failure_events)
    assert not any(event.startswith("bash:") for event in local_failure_events)

    embedding_failure, embedding_failure_events = _run_runtime_health(
        tmp_path / "embedding-failure", embedding_fails=True
    )

    assert embedding_failure.returncode != 0
    assert any(
        "scripts/check_embedding.py" in event for event in embedding_failure_events
    )
    assert any(
        event.endswith("/runtime-fixture/fail") for event in embedding_failure_events
    )
    assert not any(event.startswith("bash:") for event in embedding_failure_events)

    public_failure, public_failure_events = _run_runtime_health(
        tmp_path / "public-failure", public_check_status=17
    )

    assert public_failure.returncode == 17
    assert any(event.endswith("/runtime-fixture/fail") for event in public_failure_events)
    assert not any(event.endswith("/runtime-fixture") for event in public_failure_events)


def _write_public_verification_curl(fake_bin: Path) -> Path:
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >>"$FAKE_CURL_LOG"\n'
        "for argument in \"$@\"; do\n"
        '    if [ "$argument" = "--write-out" ]; then\n'
        "        last=\n"
        "        for last; do :; done\n"
        '        case "$last" in\n'
        '            *.js) printf "application/javascript" ;;\n'
        '            *.css) printf "text/css" ;;\n'
        '            *.json) printf "application/json" ;;\n'
        '            *.txt) printf "text/plain" ;;\n'
        '            *) printf "text/html" ;;\n'
        "        esac\n"
        "        exit 0\n"
        "    fi\n"
        "done\n"
        "last=\n"
        "for last; do :; done\n"
        'case "$last" in\n'
        '    */api/health) printf \'{"status":"healthy","database":"connected"}\' ;;\n'
        '    */asset-inventory.txt) cat "$FAKE_INVENTORY" ;;\n'
        '    */) printf \'<div id="app"></div><link rel="stylesheet" href="/assets/app.css"><script src="/assets/app.js"></script>\' ;;\n'
        "esac\n"
    )
    fake_curl.chmod(0o755)
    return fake_curl


def _run_public_verification(
    tmp_path: Path, *arguments: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    env_file = _copy_safe_test_env(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_public_verification_curl(fake_bin)
    curl_log = tmp_path / "curl.log"
    inventory = tmp_path / "asset-inventory.txt"
    inventory.write_text("\n".join(_RUNTIME_PATHS + ["/assets/app.css"]) + "\n")
    environment = os.environ | {
        "ENV_FILE": str(env_file),
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_INVENTORY": str(inventory),
    }
    result = subprocess.run(
        ["sh", str(VERIFY_PUBLIC_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, curl_log.read_text(encoding="utf-8").splitlines()


def test_public_verification_keeps_full_inventory_and_runtime_checks_only_index_assets(
    tmp_path: Path,
) -> None:
    full, full_requests = _run_public_verification(tmp_path / "full")
    runtime, runtime_requests = _run_public_verification(tmp_path / "runtime", "--runtime")

    assert full.returncode == 0, full.stderr
    assert runtime.returncode == 0, runtime.stderr
    assert any(request.endswith("/asset-inventory.txt") for request in full_requests)
    assert not any(request.endswith("/asset-inventory.txt") for request in runtime_requests)
    assert any(request.endswith("/assets/app.js") for request in runtime_requests)
    assert any(request.endswith("/assets/app.css") for request in runtime_requests)
    for request in full_requests + runtime_requests:
        assert "--connect-timeout 5" in request
        assert "--max-time 30" in request
        assert "--proto =https" in request
        assert "--tlsv1.2" in request
    assert any("--max-filesize 65536" in request for request in full_requests)
    assert any("--max-filesize 1048576" in request for request in full_requests)
    assert any("--max-filesize 65536" in request for request in runtime_requests)
    assert any("--max-filesize 1048576" in request for request in runtime_requests)


def test_public_verification_rejects_unknown_or_extra_arguments_before_network_use() -> None:
    for arguments in (("--unexpected",), ("--runtime", "extra")):
        result = subprocess.run(
            ["sh", str(VERIFY_PUBLIC_SCRIPT), *arguments],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
        assert "Usage:" in result.stderr


def test_runtime_health_systemd_units_are_bounded_and_secret_free() -> None:
    service = (
        DEPLOY_ROOT / "systemd" / "ai-writing-runtime-health.service"
    ).read_text(encoding="utf-8")
    timer = (DEPLOY_ROOT / "systemd" / "ai-writing-runtime-health.timer").read_text(
        encoding="utf-8"
    )
    script = RUNTIME_HEALTH_SCRIPT.read_text(encoding="utf-8")

    assert RUNTIME_HEALTH_SCRIPT.stat().st_mode & 0o111
    assert "validate_environment" in script
    assert "load_release_id" in script
    assert "HEALTHCHECKS_RUNTIME_PING_URL" in script
    assert script.index('healthcheck_ping "${HEALTHCHECK_URL}/start"') < script.index(
        "wait_for_application_health"
    ) < script.index("compose exec -T api python scripts/check_embedding.py") < script.index(
        'bash "$SCRIPT_DIR/verify_public.sh" --runtime'
    )
    assert (
        "compose exec -T api python scripts/check_embedding.py \\\n    --timeout-seconds 45 \\\n    --request-timeout-seconds 10 \\\n    --retry-delay-seconds 5"
    ) in script
    assert "RUNTIME_HEALTH_SUCCEEDED" in script
    assert 'healthcheck_ping "${HEALTHCHECK_URL}/fail" || true' in script
    assert "Requires=docker.service" in service
    assert "Wants=network-online.target" in service
    assert "After=network-online.target" in service
    assert "ConditionPathExists=/opt/ai-writing-assist/deploy/.env.production" in service
    assert "Environment=ENV_FILE=/opt/ai-writing-assist/deploy/.env.production" in service
    assert "ExecStart=/bin/bash /opt/ai-writing-assist/deploy/scripts/runtime_health.sh" in service
    assert "TimeoutStartSec=5m" in service
    assert "http" not in service.lower()
    assert "OnBootSec=2m" in timer
    assert "OnUnitInactiveSec=5m" in timer
    assert "AccuracySec=30s" in timer
    assert "RandomizedDelaySec=30s" in timer
    assert "Unit=ai-writing-runtime-health.service" in timer
    assert "Persistent=" not in timer


def _load_embedding_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "deployment_embedding_check", EMBEDDING_CHECK_SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _embedding_environment(expected_dim: int = 3) -> dict[str, str]:
    return {
        "EMBEDDING_BASE_URL": "http://embedding:80/v1",
        "EMBEDDING_MODEL": "bge-base-zh-v1.5",
        "EMBEDDING_API_KEY": "test-api-key",
        "EMBEDDING_DIM": str(expected_dim),
    }


def test_embedding_probe_accepts_the_expected_dimension_and_caps_request_timeout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_embedding_check()
    clock = _FakeClock()
    request_timeouts: list[float] = []

    def urlopen(_request: object, *, timeout: float) -> io.StringIO:
        request_timeouts.append(timeout)
        return io.StringIO('{"data": [{"embedding": [0, 0, 0]}]}')

    result = module.check_embedding(
        timeout_seconds=5,
        request_timeout_seconds=10,
        retry_delay_seconds=1,
        environment=_embedding_environment(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=urlopen,
    )

    assert result == 0
    assert request_timeouts == [5]
    assert capsys.readouterr().out == "Embedding service ready (3 dimensions).\n"


def test_embedding_probe_retries_without_sleeping_or_requesting_past_deadline(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_embedding_check()
    clock = _FakeClock()
    request_timeouts: list[float] = []

    def urlopen(_request: object, *, timeout: float) -> io.StringIO:
        request_timeouts.append(timeout)
        clock.now += 8
        raise module.urllib.error.URLError("private endpoint detail")

    result = module.check_embedding(
        timeout_seconds=10,
        request_timeout_seconds=7,
        retry_delay_seconds=5,
        environment=_embedding_environment(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=urlopen,
    )

    assert result == 1
    assert request_timeouts == [7]
    assert clock.sleeps == [2]
    assert clock.now == 10
    output = capsys.readouterr().out
    assert output == "Embedding service did not become ready: URLError\n"
    assert "private endpoint detail" not in output


def test_embedding_probe_caps_later_request_timeout_to_the_remaining_budget(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_embedding_check()
    clock = _FakeClock()
    request_timeouts: list[float] = []

    def urlopen(_request: object, *, timeout: float) -> io.StringIO:
        request_timeouts.append(timeout)
        clock.now += 1 if len(request_timeouts) == 1 else timeout
        raise module.urllib.error.URLError("private endpoint detail")

    result = module.check_embedding(
        timeout_seconds=10,
        request_timeout_seconds=8,
        retry_delay_seconds=2,
        environment=_embedding_environment(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=urlopen,
    )

    assert result == 1
    assert request_timeouts == [8, 7]
    assert clock.sleeps == [2]
    assert capsys.readouterr().out == "Embedding service did not become ready: URLError\n"


def test_embedding_probe_reports_dimension_failure_without_dynamic_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_embedding_check()
    clock = _FakeClock()

    def urlopen(_request: object, *, timeout: float) -> io.StringIO:
        return io.StringIO('{"data": [{"embedding": [0, 0]}]}')

    result = module.check_embedding(
        timeout_seconds=5,
        request_timeout_seconds=5,
        retry_delay_seconds=5,
        environment=_embedding_environment(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=urlopen,
    )

    assert result == 1
    assert capsys.readouterr().out == "Embedding service did not become ready: ValueError\n"


def test_embedding_probe_reports_malformed_json_structure_as_type_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_embedding_check()
    clock = _FakeClock()

    def urlopen(_request: object, *, timeout: float) -> io.StringIO:
        return io.StringIO('{"data": null, "detail": "private response detail"}')

    result = module.check_embedding(
        timeout_seconds=5,
        request_timeout_seconds=5,
        retry_delay_seconds=5,
        environment=_embedding_environment(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=urlopen,
    )

    assert result == 1
    output = capsys.readouterr().out
    assert output == "Embedding service did not become ready: TypeError\n"
    assert "private response detail" not in output


def test_embedding_probe_rejects_oversized_responses_without_reading_body_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_embedding_check()
    clock = _FakeClock()

    class OversizedPayload:
        def __len__(self) -> int:
            return module.MAX_RESPONSE_BYTES + 1

    class OversizedResponse:
        def __enter__(self) -> "OversizedResponse":
            return self

        def __exit__(self, *_arguments: object) -> None:
            return None

        def read(self, limit: int) -> OversizedPayload:
            assert limit == module.MAX_RESPONSE_BYTES + 1
            return OversizedPayload()

    def urlopen(_request: object, *, timeout: float) -> OversizedResponse:
        return OversizedResponse()

    result = module.check_embedding(
        timeout_seconds=5,
        request_timeout_seconds=5,
        retry_delay_seconds=5,
        environment=_embedding_environment(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        urlopen=urlopen,
    )

    assert result == 1
    assert capsys.readouterr().out == "Embedding service did not become ready: ValueError\n"


def test_embedding_probe_cli_rejects_non_positive_time_budgets() -> None:
    module = _load_embedding_check()

    for arguments in (
        ("--timeout-seconds", "0"),
        ("--request-timeout-seconds", "-1"),
        ("--retry-delay-seconds", "0"),
    ):
        with pytest.raises(SystemExit) as error:
            module.main(list(arguments))

        assert error.value.code == 2


def test_embedding_probe_keeps_release_defaults_and_runtime_budget_contract() -> None:
    module = _load_embedding_check()
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text(
        encoding="utf-8"
    )
    runtime_script = RUNTIME_HEALTH_SCRIPT.read_text(encoding="utf-8")

    assert module.DEFAULT_TIMEOUT_SECONDS == 900
    assert module.DEFAULT_REQUEST_TIMEOUT_SECONDS == 30
    assert module.DEFAULT_RETRY_DELAY_SECONDS == 5
    assert "if ! compose run --rm api python scripts/check_embedding.py; then" in release_script
    assert (
        "compose exec -T api python scripts/check_embedding.py \\\n    --timeout-seconds 45 \\\n    --request-timeout-seconds 10 \\\n    --retry-delay-seconds 5"
    ) in runtime_script
