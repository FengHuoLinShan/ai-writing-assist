import json
import os
import subprocess
import sys

import pytest

from desktop import release


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    (root / "desktop/changes").mkdir(parents=True)
    (root / "desktop/VERSION").write_text("0.1.0-alpha.1\n")
    (root / "desktop/INSTALL.txt").write_text("Install instructions\n")
    (root / "desktop/changes/0.1.0-alpha.1.md").write_text("Preview notes\n")
    (root / ".gitignore").write_text("desktop/build/\nartifacts/\ncollected/\n")
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    for args in [
        ("add", "."),
        (
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "synthetic release fixture",
        ),
    ]:
        release.git(*args, root=root)
    release.git("update-ref", "refs/remotes/origin/main", "HEAD", root=root)
    return root


@pytest.mark.parametrize(
    "invalid", ["../bad", "v1.0.0", "01.0.0", "1.0.0-rc.0", "65536.0.0", "1.0.0\nother"]
)
def test_version_rejects_invalid_native_versions(source, invalid):
    (source / "desktop/VERSION").write_text(invalid)
    with pytest.raises(ValueError):
        release.version(source)


def test_fixed_main_source_rejects_dirty_or_mismatched_checkout(source):
    sha = release.git("rev-parse", "HEAD", root=source)
    assert release.verify_source(sha, source)["version"] == "0.1.0-alpha.1"
    with pytest.raises(ValueError, match="40-character"):
        release.verify_source("main", source)
    with pytest.raises(ValueError, match="does not match"):
        release.verify_source("a" * 40, source)
    (source / "desktop/INSTALL.txt").write_text("uncommitted edit")
    with pytest.raises(ValueError, match="clean"):
        release.verify_source(sha, source)


def test_ci_requires_the_exact_sha_and_latest_main_push_run():
    sha = "a" * 40
    runs = [
        {
            "id": i,
            "head_sha": sha,
            "event": "push",
            "conclusion": "success",
            "path": ".github/workflows/" + path,
        }
        for i, path in enumerate(release.REQUIRED_WORKFLOWS)
    ]
    release.verify_ci(runs, sha)
    for changed in (
        {"conclusion": "failure"},
        {"conclusion": None},
        {"head_sha": "b" * 40},
        {"event": "pull_request"},
    ):
        bad = [{**runs[0], **changed}, *runs[1:]]
        with pytest.raises(ValueError, match="missing/not green"):
            release.verify_ci(bad, sha)
    with pytest.raises(ValueError, match="missing/not green"):
        release.verify_ci([*runs, {**runs[0], "id": 999, "conclusion": "failure"}], sha)


def artifacts(root):
    metadata = release.build_metadata(root)
    assets = root / "desktop/build/assets"
    assets.mkdir(parents=True)
    (assets / "build.json").write_text(json.dumps(metadata))
    payload = assets / "synthetic-installer"
    payload.write_bytes(b"synthetic artifact, no executable code")
    directory = root / "artifacts"
    for platform in release.PLATFORMS:
        release.package(payload, platform, False, directory / platform, root)
    return metadata, directory


def test_assembly_emits_three_packages_checksums_and_instructions(source):
    metadata, directory = artifacts(source)
    release.assemble(directory, metadata["commit"], source)
    output = directory / "release"
    manifest = json.loads((output / "release.json").read_text())
    assert len(manifest["artifacts"]) == 3
    for artifact in manifest["artifacts"]:
        assert release.digest(output / artifact["file"]) == artifact["sha256"]
    assert len((output / "SHA256SUMS.txt").read_text().splitlines()) == 3
    assert (output / "安装说明.txt").read_text() == "Install instructions\n"


@pytest.mark.parametrize("fault", ["checksum", "commit", "missing", "stable-unsigned"])
def test_assembly_fails_closed_on_mixed_damaged_or_unsigned_stable_artifacts(
    source, fault
):
    metadata, directory = artifacts(source)
    sidecar = directory / "macos-arm64/macos-arm64.json"
    record = json.loads(sidecar.read_text())
    if fault == "checksum":
        (sidecar.parent / record["file"]).write_bytes(b"damaged download")
    elif fault == "commit":
        record["commit"] = "b" * 40
        sidecar.write_text(json.dumps(record))
    elif fault == "missing":
        sidecar.unlink()
    else:
        (source / "desktop/VERSION").write_text("0.1.0")
        for path in directory.rglob("*.json"):
            item = json.loads(path.read_text())
            old = path.parent / item["file"]
            item["version"] = "0.1.0"
            item["file"] = release.artifact_name("0.1.0", item["platform"])
            old.rename(path.parent / item["file"])
            path.write_text(json.dumps(item))
    with pytest.raises(ValueError):
        release.assemble(directory, metadata["commit"], source)
    assert not (directory / "release").exists()


def test_apple_signing_without_credentials_stops_before_using_keychain(tmp_path):
    script = release.ROOT / "desktop/sign_macos.py"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("APPLE_", "MACOS_", "NOVELCRAFT_CODESIGN"))
    }
    result = subprocess.run(
        [sys.executable, str(script), "prepare"],
        env={**env, "RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "requires all documented Apple signing secrets" in result.stderr
    assert not list(tmp_path.iterdir())
