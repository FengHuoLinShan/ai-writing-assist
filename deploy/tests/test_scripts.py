import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEPLOY_ROOT = Path(__file__).parents[1]
COMMON_SCRIPT = DEPLOY_ROOT / "scripts" / "common.sh"
FRONTEND_ASSET_VALIDATOR = DEPLOY_ROOT / "scripts" / "validate_frontend_assets.py"

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
