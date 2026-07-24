import subprocess
import sys
from pathlib import Path


DEPLOY_ROOT = Path(__file__).parents[1]


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
