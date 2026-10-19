"""Run the desktop app from source without freezing an installer."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Desktop development requires macOS or Windows")
    assets = ROOT / "desktop/build/assets"
    postgres = "postgres.exe" if os.name == "nt" else "postgres"
    if not all(
        path.is_file()
        for path in (
            assets / "manifest.json",
            assets / "postgres/bin" / postgres,
            assets / "model/model.onnx",
        )
    ):
        raise SystemExit("Run make desktop-prepare first to prepare local resources")
    os.environ["PYTHONUTF8"] = "1"
    # Keep source development separate from installed user libraries.
    os.environ.setdefault(
        "NOVELCRAFT_DESKTOP_DATA_DIR", str(ROOT / "desktop/build/dev-data")
    )
    subprocess.run(
        ["npm.cmd" if os.name == "nt" else "npm", "run", "build"],
        cwd=ROOT / "frontend-console",
        check=True,
    )
    os.execv(sys.executable, [sys.executable, str(ROOT / "desktop/entry.py")])


if __name__ == "__main__":
    main()
