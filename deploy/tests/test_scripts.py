from pathlib import Path


DEPLOY_ROOT = Path(__file__).parents[1]


def test_public_bootstrap_passes_named_email_argument() -> None:
    common_script = (DEPLOY_ROOT / "scripts" / "common.sh").read_text()

    assert 'claim-legacy \\\n                --email "$bootstrap_email"' in common_script
