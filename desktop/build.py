"""Build a native desktop bundle on the target OS/architecture."""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=["macos-arm64", "macos-x64", "windows-x64"],
        default="macos-arm64",
    )
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Build on macOS or Windows")
    architecture = platform.machine().lower()
    host = {
        ("darwin", "arm64"): "macos-arm64",
        ("darwin", "x86_64"): "macos-x64",
        ("win32", "amd64"): "windows-x64",
        ("win32", "x86_64"): "windows-x64",
    }.get((sys.platform, architecture))
    if args.target != host:
        raise SystemExit(
            f"Target {args.target} requires its native host; this host is {host}"
        )
    os.environ["PYTHONUTF8"] = "1"
    subprocess.run([sys.executable, str(ROOT / "desktop/build_assets.py")], check=True)
    sys.path.insert(0, str(ROOT))
    from desktop.release import build_metadata

    metadata = build_metadata()
    assets = ROOT / "desktop/build/assets"
    (assets / "build.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (assets / "version.iss").write_text(
        '#define NovelCraftVersion "' + metadata["version"] + '"\n'
        '#define NovelCraftNumericVersion "' + metadata["version"].split("-")[0] + '"\n'
    )
    npm = "npm.cmd" if os.name == "nt" else "npm"
    subprocess.run([npm, "ci", "--prefix", str(ROOT / "frontend-console")], check=True)
    subprocess.run(
        [npm, "run", "build", "--prefix", str(ROOT / "frontend-console")], check=True
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(ROOT / "desktop/dist"),
            "--workpath",
            str(ROOT / "desktop/build/pyinstaller"),
            str(ROOT / "desktop/NovelCraft.spec"),
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
