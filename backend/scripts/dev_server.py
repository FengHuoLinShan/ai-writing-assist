"""Start the FastAPI backend in development mode with auto-reload."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELOAD_DIRS = (
    "app",
    "core",
    "shared",
    "infrastructure",
    "modules",
    "prompts",
)


def _existing_reload_dirs() -> list[str]:
    return [
        str(BACKEND_ROOT / name)
        for name in DEFAULT_RELOAD_DIRS
        if (BACKEND_ROOT / name).exists()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start backend API with development auto-reload.",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable file watching. Intended only for debugging the dev server itself.",
    )
    args = parser.parse_args()

    reload_enabled = not args.no_reload
    print(
        "Backend dev server starting "
        f"on http://{args.host}:{args.port} "
        f"({'auto-reload enabled' if reload_enabled else 'auto-reload disabled'})"
    )

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=reload_enabled,
        reload_dirs=_existing_reload_dirs() if reload_enabled else None,
        reload_includes=["*.py", "*.md"] if reload_enabled else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
