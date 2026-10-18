"""Build a native desktop bundle on the target OS/architecture."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Build on macOS or Windows")
    subprocess.run([sys.executable, str(ROOT / "desktop/build_assets.py")], check=True)
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
