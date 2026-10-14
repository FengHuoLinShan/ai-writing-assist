"""G4b cross-language acceptance: browser packer output feeds object_backup.

The fixture ZIPs are produced by ``frontend-console/scripts/
generate-image-export-fixture.mjs``, which imports the exact browser packing
module (fflate streaming store + sha256 manifests) used by the export panel.
Filename coverage: Chinese, emoji, duplicates, >255-byte segments and
case-insensitive collisions. The test is skipped when node or the frontend
``fflate`` dependency is unavailable (the browser-produced archive is then
validated wherever both toolchains exist, e.g. the local gate and the G4b
restore drill).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "scripts" / "object_backup.py"
spec = importlib.util.spec_from_file_location("object_backup", SCRIPT)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)

NODE = shutil.which("node")


def _fflate_available() -> bool:
    return (ROOT / "frontend-console" / "node_modules" / "fflate").is_dir()


@pytest.fixture
def browser_packages(tmp_path: Path) -> tuple[Path, dict]:
    if NODE is None or not _fflate_available():
        # 覆盖边界：后端 CI 无 node，此跨语言合同在那里不生效；本地门禁与
        # G4b 恢复演练（run_browser_export_restore_drill.py）承担实际验证。
        pytest.skip("node or frontend-console fflate dependency unavailable")
    target = tmp_path / "fixture"
    result = subprocess.run(
        [NODE, "scripts/generate-image-export-fixture.mjs", str(target)],
        cwd=ROOT / "frontend-console",
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads((target / "fixture.json").read_text())
    packages = [target / entry["name"] for entry in metadata["packages"]]
    assert packages, result.stdout
    for package in packages:
        package.chmod(0o600)
    return target, metadata


def test_browser_package_passes_unpack_and_manifest(browser_packages, tmp_path):
    fixture_dir, metadata = browser_packages
    buckets = metadata["buckets"]
    restored = 0
    seen_files = set()
    for package in sorted(fixture_dir.glob("package-*.zip")):
        info = package.stat()
        assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
        target = tmp_path / f"unpacked-{package.stem}"
        target.mkdir(mode=0o700)
        timestamp = backup.unpack_package(package, target, buckets)
        manifest = backup.read_manifest(target / "snapshots" / timestamp, buckets)
        assert manifest["schema"] == backup.SCHEMA
        assert manifest["source_kind"] == "author_export"
        assert manifest["status"] == "complete"
        assert manifest["db_timestamp"] is None
        # unpack_package already hashes and PIL-decodes every object; verify_local
        # re-checks the on-disk mirror against each manifest row.
        backup.verify_local(target / "objects", manifest)
        restored += len(manifest["objects"])
        seen_files.update(row["file"] for row in manifest["objects"])
    assert restored == metadata["expected_objects"]
    # 部分失败语义：损坏项（hash 不符）不入包，仍是 author_export 可恢复包。
    assert metadata["expected_failures"] == 1
    joined = "\n".join(seen_files)
    for expected in ("主世界.png", "主世界-2.png", "ABC.png", "abc-2.png", "完整图.webp"):
        assert expected in joined, joined
    assert any("🗺️" in name for name in seen_files)
    assert any("龙🐉岛" in name for name in seen_files)
    for name in seen_files:
        for segment in name.split("/"):
            assert 0 < len(segment.encode()) <= 255
