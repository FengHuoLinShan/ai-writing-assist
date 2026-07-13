"""Start the FastAPI backend in development mode with auto-reload."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from watchfiles import Change, PythonFilter, run_process

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


def _serve(host: str, port: int) -> None:
    """Run one backend process without a nested reload supervisor."""
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


def _log_reload(changes: set[tuple[Change, str]]) -> None:
    changed = ", ".join(
        f"{change.name.lower()}:{Path(path).relative_to(BACKEND_ROOT)}"
        for change, path in sorted(changes, key=lambda item: item[1])
    )
    print(f"Backend changes detected; restarting complete server process: {changed}")


def run_dev_server(host: str, port: int, *, reload_enabled: bool) -> None:
    if not reload_enabled:
        _serve(host, port)
        return

    reload_dirs = _existing_reload_dirs()
    if not reload_dirs:
        raise RuntimeError("No backend reload directories exist")

    # Uvicorn's built-in reloader keeps the listening socket in its parent
    # process.  If the application child fails during a reload, the port can
    # still look alive while no process is able to serve requests.  Let
    # watchfiles own the supervisor instead: it stops the complete Uvicorn
    # process before starting a fresh one, so every reload is a real backend
    # restart and a failed import cannot leave a false-positive listener.
    run_process(
        *reload_dirs,
        target=_serve,
        args=(host, port),
        target_type="function",
        callback=_log_reload,
        watch_filter=PythonFilter(extra_extensions=(".md",)),
        debounce=500,
        sigint_timeout=10,
        sigkill_timeout=2,
    )


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

    run_dev_server(args.host, args.port, reload_enabled=reload_enabled)


if __name__ == "__main__":
    main()
