import subprocess
import sys
from pathlib import Path


DEPLOY_ROOT = Path(__file__).parents[1]


def test_runtime_auth_mode_is_shared_by_api_and_worker() -> None:
    compose = (DEPLOY_ROOT / "compose.production.yml").read_text()
    runtime_section, api_and_services = compose.split(
        "x-api-environment:", maxsplit=1
    )

    assert "AUTH_MODE: ${AUTH_MODE:?Choose AUTH_MODE" in runtime_section
    assert "environment: *api-environment" in api_and_services
    assert "environment: *runtime-environment" in api_and_services


def test_release_only_accepts_commits_reachable_from_origin_main() -> None:
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text()

    assert 'if [ "${#RELEASE_REF}" -ne 40 ]; then' in release_script
    assert 'git -C "$REPO_ROOT" fetch --prune origin' in release_script
    assert (
        'git -C "$REPO_ROOT" merge-base --is-ancestor '
        '"$TARGET_COMMIT" origin/main'
    ) in release_script
    assert "umask 022" in release_script


def test_release_checks_frontend_runtime_assets() -> None:
    release_script = (DEPLOY_ROOT / "scripts" / "release.sh").read_text()
    restore_script = (DEPLOY_ROOT / "scripts" / "restore.sh").read_text()
    dockerfile = (DEPLOY_ROOT.parent / "frontend-console" / "Dockerfile").read_text()

    assert "chmod -R a+rX /usr/share/nginx/html" in dockerfile
    assert "umask 022" in restore_script
    assert "frontend_runtime_healthy" in release_script
    for asset in ("/ui/modal.js", "/apiContracts.js", "/router.js"):
        assert asset in release_script


def test_public_verification_fetches_declared_frontend_assets() -> None:
    verification_script = (DEPLOY_ROOT / "scripts" / "verify_public.sh").read_text()

    assert "FrontendAssetParser" in verification_script
    assert "frontend-assets.tsv" in verification_script
    assert "--write-out '%{content_type}'" in verification_script


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
